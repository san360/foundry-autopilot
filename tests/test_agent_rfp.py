"""Agent-level tests for the RFP Bid Desk scenario and /whoami, with Azure and the Agents SDK faked."""

import asyncio
import importlib
import json
from types import SimpleNamespace

import httpx
import pytest

from fincrime_autopilot.instance_tokens import InstanceTokenProvider
from fincrime_autopilot.search_client import SearchClient
from test_instance_tokens import FakeConnectionManager, factory
from test_token_debug import (
    AGENT_APP_ID,
    AGENT_IDENTITY_TOKEN,
    AGENT_USER_OID,
    AGENT_USER_TOKEN,
    CONTAINER_TOKEN,
    DEFAULT_INSTANCE,
    SIGNATURE,
)

TENANT = "5b26daf8-1d7a-47f5-bb8d-cbee1e80a381"


def _require_runtime_deps():
    """These tests need the container's runtime dependencies (pip install -r src/fincrime_autopilot/requirements.txt)."""
    for module in ("microsoft_agents.hosting.core", "microsoft_agents.hosting.aiohttp", "opentelemetry", "aiohttp"):
        pytest.importorskip(module, reason="runtime dependencies not installed")


@pytest.fixture
def make_agent(monkeypatch):
    _require_runtime_deps()
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://acct.services.ai.azure.com/api/projects/proj")
    monkeypatch.setenv("ModelDeployment", "gpt-test")
    monkeypatch.setenv("FOUNDRY_AGENT_DEFAULT_INSTANCE_CLIENT_ID", DEFAULT_INSTANCE)
    monkeypatch.setenv("SEARCH_ENDPOINT", "https://srch.search.windows.net")
    monkeypatch.setenv("TOKEN_DEBUG", "true")
    monkeypatch.delenv("TOKEN_FOOTER", raising=False)
    monkeypatch.delenv("SEARCH_TOKEN_FLOW", raising=False)
    agent_module = importlib.import_module("fincrime_autopilot.agent")

    def build(scenario="rfp", readable=("bids-banking",)):
        monkeypatch.setenv("AUTOPILOT_SCENARIO", scenario)
        agent = agent_module.FinCrimeTriageAgent()
        agent._expected_tenant_id = TENANT

        def handler(request):
            index = request.url.path.split("/")[2]
            token = request.headers["authorization"].split(" ", 1)[1]
            if index in readable and token != CONTAINER_TOKEN:
                return httpx.Response(200, json={"value": [{"id": "1", "question": "q", "answer": "a"}]})
            return httpx.Response(403, json={"error": {"message": "Forbidden"}})

        agent._search = SearchClient("https://srch", http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))

        class Credential:
            async def get_token(self, *scopes, **kwargs):
                return SimpleNamespace(token=CONTAINER_TOKEN)

        class SessionCredential:
            async def get_token(self, *scopes, **kwargs):
                return SimpleNamespace(token=AGENT_IDENTITY_TOKEN)

        agent._token_provider = InstanceTokenProvider(
            connection_manager=FakeConnectionManager(),
            container_credential=Credential(),
            session_credential=SessionCredential(),
            msal_factory=factory({"access_token": AGENT_IDENTITY_TOKEN}),
        )
        return agent

    return build


class FakeAuth:
    async def exchange_token(self, context, scopes, auth_handler_id):
        return SimpleNamespace(token=AGENT_USER_TOKEN)


def context(name="BankingBids", channel_id="msteams", text="", subject=""):
    recipient = SimpleNamespace(name=name, id=f"{name.lower()}@zava", agentic_app_id=AGENT_APP_ID,
                                agentic_user_id=AGENT_USER_OID, tenant_id=TENANT, role="agenticUser")
    activity = SimpleNamespace(
        recipient=recipient,
        from_property=SimpleNamespace(name="Ana Bid", id="ana@zava.example", aad_object_id="human-oid"),
        channel_id=channel_id,
        conversation=SimpleNamespace(id="conv-1", tenant_id=TENANT, conversation_type="personal"),
        channel_data={"subject": subject} if subject else None,
        text=text,
        attachments=[],
    )
    return SimpleNamespace(activity=activity, identity=None)


def test_whoami_in_teams_shows_all_identities_and_live_rbac_results(make_agent):
    agent = make_agent()
    reply = asyncio.run(agent.process_user_message("<at>BankingBids</at> /whoami probe", FakeAuth(), "AGENTIC", context()))
    assert reply.startswith("**/whoami - BankingBids")
    assert "kind=agent-user" in reply and "kind=agent-identity" in reply and "kind=container-default-identity" in reply
    assert "as agent_identity: bids-banking -> HTTP 200" in reply
    assert "as agent_identity: bids-publicsector -> HTTP 403 refused by Azure RBAC" in reply
    assert "flow session_identity" in reply and "as session_identity: bids-banking -> HTTP 200" in reply
    assert "flow agent_user" in reply
    assert "as shared container: bids-banking -> HTTP 403" in reply
    assert SIGNATURE not in reply and AGENT_USER_TOKEN not in reply and AGENT_IDENTITY_TOKEN not in reply


def test_whoami_is_off_without_token_debug(make_agent, monkeypatch):
    agent = make_agent()
    monkeypatch.setenv("TOKEN_DEBUG", "false")
    reply = asyncio.run(agent.process_user_message("/whoami", FakeAuth(), "AGENTIC", context()))
    assert "token inspector is off" in reply


def test_whoami_by_email_is_sent_through_the_mail_tool(make_agent, monkeypatch):
    agent = make_agent()
    captured = {}

    async def fake_invoke(**kwargs):
        captured.update(kwargs)
        return "NO_REPLY"

    monkeypatch.setattr(agent, "_invoke_responses_api", fake_invoke)
    monkeypatch.setattr(agent, "_allowed_sender_domains", set())
    result = asyncio.run(agent.process_user_message("hi", FakeAuth(), "AGENTIC",
                                                    context(channel_id="email", subject="/whoami")))
    assert result == "NO_REPLY"
    assert captured["function_tools"] is False
    assert "<p>/whoami - BankingBids" in captured["input_text"]
    assert SIGNATURE not in captured["input_text"]


def test_replies_in_a_whoami_email_thread_are_processed_normally(make_agent, monkeypatch):
    agent = make_agent(scenario="fincrime")
    captured = {}

    async def fake_invoke(**kwargs):
        captured.update(kwargs)
        return "NO_REPLY"

    monkeypatch.setattr(agent, "_invoke_responses_api", fake_invoke)
    monkeypatch.setattr(agent, "_allowed_sender_domains", set())
    body = "Thanks, can you now triage ALR-2026-1043?\n\n> /whoami - MiraRetail (claims only)"
    asyncio.run(agent.process_user_message(body, FakeAuth(), "AGENTIC", context(name="MiraRetail", channel_id="email", subject="RE: /whoami")))
    assert captured.get("function_tools", True) is True
    assert "triage ALR-2026-1043" in captured["input_text"]


def test_isolation_through_the_agent_turn(make_agent):
    agent = make_agent(readable=("bids-publicsector",))
    ctx = context(name="PublicSectorBids")
    turn = agent._build_turn(ctx, FakeAuth(), "AGENTIC")
    assert "bids-publicsector" in turn.scope_label
    own = asyncio.run(turn.execute("search_past_answers", json.dumps({"question": "data residency", "team": None})))
    assert own["library"] == "bids-publicsector" and own["matches"]
    other = asyncio.run(turn.execute("search_past_answers", json.dumps({"question": "data residency", "team": "banking"})))
    assert other["error"] == "access_denied" and other["http_status"] == 403
    assert other["acting_identity"]["kind"] == "agent-identity"
    assert agent._with_footer("Answer", turn, "teams") == "Answer"


def test_footer_names_the_acting_identity(make_agent, monkeypatch):
    agent = make_agent()
    monkeypatch.setattr(agent, "_footer_enabled", True)
    turn = agent._build_turn(context(), FakeAuth(), "AGENTIC")
    asyncio.run(turn.execute("search_past_answers", json.dumps({"question": "ISO", "team": None})))
    text = agent._with_footer("Answer", turn, "teams")
    assert text.startswith("Answer\n\n_Acted as: BankingBids · agent identity")
    assert "token for https://search.azure.com" in text
    assert agent._with_footer("NO_REPLY", turn, "teams") == "NO_REPLY"
    assert "<small>" in agent._with_footer("<p>Hi</p>", turn, "email")


def test_rfp_scenario_loads_scoped_manifest_and_fincrime_is_unchanged(make_agent):
    rfp = make_agent()
    assert {s["mcpServerName"] for s in rfp._mcp_servers} == {"mcp_WordServer", "mcp_MailTools", "mcp_ODSPRemoteServer", "mcp_TeamsServer"}
    fincrime = make_agent(scenario="fincrime")
    assert len(fincrime._mcp_servers) == 6
    turn = fincrime._build_turn(context(name="MiraRetail"), FakeAuth(), "AGENTIC")
    assert turn.tool_schemas[0]["name"] == "list_open_alerts"
    assert turn.execute("get_policy", json.dumps({"query": "POL-08"}))["policies"]


def test_mcp_tools_carry_allowlists(make_agent):
    agent = make_agent()
    tools = asyncio.run(agent._build_mcp_tools(FakeAuth(), "AGENTIC", context()))
    by_label = {t["server_label"]: t for t in tools}
    assert "allowed_tools" not in by_label["mcp_MailTools"]
    assert "deleteFileOrFolder" not in by_label["mcp_ODSPRemoteServer"]["allowed_tools"]
    assert "allowed_tools" not in by_label["mcp_TeamsServer"], "live Teams tool names are unverified; a wrong list removes every tool"
    assert by_label["mcp_WordServer"]["headers"]["Authorization"].endswith(AGENT_USER_TOKEN)


# Shape of the email Agent 365 delivered to BankingBids on 2026-11-02 (channel "agents", productInfo "email",
# subject only in conversation.topic). It was mistaken for a chat, so the daily check never ran.
LIVE_EMAIL_ACTIVITY = {
    "type": "message",
    "id": "AAMkADFmZTNhYTBkMSG=",
    "channelId": "agents",
    "serviceUrl": "https://smba.trafficmanager.net/amer/tenant/",
    "recipient": {"agenticUserId": AGENT_USER_OID, "agenticAppId": AGENT_APP_ID, "tenantId": TENANT,
                  "role": "agenticUser", "id": "bankingbids@diax07991363.onmicrosoft.com", "name": "BankingBids"},
    "from": {"id": "sanjaytest@diax07991363.onmicrosoft.com", "name": "sanjaytest", "role": "user", "tenantId": TENANT},
    "conversation": {"tenantId": TENANT, "id": "x5Fj0g-email-conv", "topic": "[bid-desk:daily-check] 2026-11-02"},
    "textFormat": "plain",
    "text": "Scheduled daily deadline check from the bid desk scheduler. Post reminders for bids due within 7 days to the bid team chat.",
    "entities": [
        {"type": "productInfo", "id": "email"},
        {"type": "emailNotification", "id": "AAMkADFmZTNhYTBkMSG=", "conversationId": "AAQkAD",
         "htmlBody": "<body>Scheduled daily deadline check</body>"},
    ],
    "channelData": {"tenant": {"id": TENANT}, "productContext": "email"},
}


def _live_email_context(**overrides):
    from microsoft_agents.activity import Activity

    from fincrime_autopilot.email_channel_compat import capture_raw_conversation_topic

    payload = json.loads(json.dumps(LIVE_EMAIL_ACTIVITY))
    payload.update(overrides)
    capture_raw_conversation_topic(json.dumps(payload))  # what the host does with the raw request body
    return SimpleNamespace(activity=Activity.model_validate(payload), identity=None)


def test_agents_channel_email_runs_the_daily_check(make_agent, monkeypatch):
    agent = make_agent()
    captured = {}

    async def fake_invoke(**kwargs):
        captured.update(kwargs)
        return "NO_REPLY"

    monkeypatch.setattr(agent, "_invoke_responses_api", fake_invoke)
    ctx = _live_email_context()
    assert agent._email_context(ctx.activity) == (True, "[bid-desk:daily-check] 2026-11-02", "AAMkADFmZTNhYTBkMSG=")
    result = asyncio.run(agent.process_user_message(ctx.activity.text, FakeAuth(), "AGENTIC", ctx))
    assert result == "NO_REPLY"
    assert captured["channel"] == "email" and captured["include_teams_mcp"] is True
    assert "Scheduled deadline check" in captured["instructions"] and "Woodgrove" not in captured["instructions"]
    assert "do not reply by email" in captured["input_text"]


def test_agents_channel_rfp_email_is_answered_with_reply_to_message(make_agent, monkeypatch):
    agent = make_agent()
    captured = {}

    async def fake_invoke(**kwargs):
        captured.update(kwargs)
        return "NO_REPLY"

    monkeypatch.setattr(agent, "_invoke_responses_api", fake_invoke)
    ctx = _live_email_context(conversation={"tenantId": TENANT, "id": "c2", "topic": "RFP WB-2026-117"},
                              text="1. Where will our data be stored?")
    asyncio.run(agent.process_user_message(ctx.activity.text, FakeAuth(), "AGENTIC", ctx))
    assert captured["channel"] == "email"
    assert "Subject: RFP WB-2026-117" in captured["input_text"]
    assert "ReplyToMessage on message ID AAMkADFmZTNhYTBkMSG=" in captured["input_text"]
    assert "# Email" in captured["instructions"]


def test_agents_channel_email_from_outside_domain_is_ignored(make_agent, monkeypatch):
    agent = make_agent()
    monkeypatch.setattr(agent, "_allowed_sender_domains", {"diax07991363.onmicrosoft.com"})
    ctx = _live_email_context(**{"from": {"id": "mallory@evil.example", "name": "Mallory"}})
    assert asyncio.run(agent.process_user_message("hi", FakeAuth(), "AGENTIC", ctx)) == "NO_REPLY"


def test_agents_channel_whoami_subject_is_honoured(make_agent, monkeypatch):
    agent = make_agent()
    captured = {}

    async def fake_invoke(**kwargs):
        captured.update(kwargs)
        return "NO_REPLY"

    monkeypatch.setattr(agent, "_invoke_responses_api", fake_invoke)
    ctx = _live_email_context(conversation={"tenantId": TENANT, "id": "c3", "topic": "/whoami"}, text="hello")
    asyncio.run(agent.process_user_message("hello", FakeAuth(), "AGENTIC", ctx))
    assert captured["function_tools"] is False and "<p>/whoami - BankingBids" in captured["input_text"]
