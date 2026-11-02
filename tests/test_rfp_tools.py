import asyncio
import json

import httpx
import pytest

from fincrime_autopilot.instance_tokens import InstanceToken
from fincrime_autopilot.rfp_tools import (
    DEFAULT_BID_TEAMS,
    RFP_TOOL_SCHEMAS,
    BidContext,
    execute_rfp_tool,
    load_bid_teams,
    normalize_team,
    resolve_home_team,
)
from fincrime_autopilot.search_client import SearchClient
from test_token_debug import AGENT_IDENTITY_TOKEN

BANKING_DOC = {
    "id": "bnk-003", "question": "Describe your information security certifications.",
    "answer": "ISO/IEC 27001:2022, recertified March 2025.", "client": "Woodgrove Bank", "industry": "Banking",
    "bid_name": "Woodgrove Bank Core Platform Hosting RFP", "bid_year": 2025, "section": "4.2",
    "source_doc": "Woodgrove-RFP-2025-response-v4.docx", "owner": "Priya Raman (Security & Compliance)",
    "last_reviewed": "2025-04-02", "tags": ["ISO 27001"], "@search.score": 3.2, "@search.rerankerScore": 2.71,
}


def make_search(readable: set[str], requests: list):
    def handler(request: httpx.Request) -> httpx.Response:
        index = request.url.path.split("/")[2]
        requests.append((index, json.loads(request.content), request.headers.get("authorization")))
        if index not in readable:
            return httpx.Response(403, json={"error": {"message": "Forbidden"}})
        return httpx.Response(200, json={"value": [BANKING_DOC]})

    return SearchClient("https://srch.search.windows.net", http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def make_ctx(home="banking", readable=("bids-banking",), token=AGENT_IDENTITY_TOKEN, requests=None):
    requests = requests if requests is not None else []
    issued = []

    async def get_token():
        issued.append(1)
        return InstanceToken(
            flow="agent_identity", scope="https://search.azure.com/.default", token=token,
            error=None if token else "no token",
            summary={"label": "search", "kind": "agent-identity", "instance": "BankingBids", "aud": "https://search.azure.com"} if token else {"kind": "no-token"},
        )

    ctx = BidContext(teams=dict(DEFAULT_BID_TEAMS), home_team=home, instance_label="BankingBids",
                     get_token=get_token, search=make_search(set(readable), requests))
    return ctx, requests, issued


def run(name, args, ctx):
    return asyncio.run(execute_rfp_tool(name, json.dumps(args), ctx))


def test_schemas_are_strict_functions():
    assert {s["name"] for s in RFP_TOOL_SCHEMAS} == {"search_past_answers", "search_past_answers_batch", "list_bid_teams"}
    for schema in RFP_TOOL_SCHEMAS:
        assert schema["strict"] is True and schema["parameters"]["additionalProperties"] is False


@pytest.mark.parametrize(
    ("hints", "team"),
    [
        (["BankingBids", "bankingbids@contoso.onmicrosoft.com"], "banking"),
        (["PublicSectorBids"], "publicsector"),
        (["Public Sector Bids"], "publicsector"),
        (["MiraRetail"], None),
    ],
)
def test_home_team_from_instance_name(hints, team):
    assert resolve_home_team(hints, DEFAULT_BID_TEAMS) == team


def test_normalize_team_accepts_labels_and_index_names():
    teams = dict(DEFAULT_BID_TEAMS)
    assert normalize_team("Banking", teams) == "banking"
    assert normalize_team("bids-publicsector", teams) == "publicsector"
    assert normalize_team("public sector", teams) == "publicsector"
    assert normalize_team("government", teams) == "publicsector"
    assert normalize_team("retail", teams) is None


def test_search_own_library_returns_cited_matches_with_bearer_token():
    ctx, requests, _ = make_ctx()
    result = run("search_past_answers", {"question": "ISO 27001 certification", "team": None}, ctx)
    assert result["library"] == "bids-banking"
    match = result["matches"][0]
    assert match["citation"] == "Woodgrove Bank Core Platform Hosting RFP (Woodgrove Bank, 2025), section 4.2"
    assert match["relevance"] == 2.71 and match["sme_owner"].startswith("Priya")
    index, body, auth = requests[0]
    assert index == "bids-banking" and body["queryType"] == "semantic"
    assert auth == f"Bearer {AGENT_IDENTITY_TOKEN}"
    assert ctx.calls[-1] == {"tool": "search_past_answers", "arguments": {"question": "ISO 27001 certification"}, "error": None}
    assert ctx.trail.preferred()["kind"] == "agent-identity"


def test_other_team_library_returns_azure_403_with_acting_identity():
    ctx, requests, _ = make_ctx(home="publicsector", readable=("bids-publicsector",))
    result = run("search_past_answers", {"question": "data residency commitments to banks", "team": "banking"}, ctx)
    assert result["error"] == "access_denied" and result["http_status"] == 403
    assert result["library"] == "bids-banking"
    assert result["acting_identity"]["kind"] == "agent-identity"
    assert "Azure RBAC" in result["message"]
    assert requests[0][0] == "bids-banking", "the call really reached Azure; the agent did not pre-filter it"


def test_batch_searches_each_question_once_with_one_token():
    ctx, requests, issued = make_ctx()
    questions = [f"q{i}" for i in range(20)]
    result = run("search_past_answers_batch", {"questions": questions, "team": None}, ctx)
    assert len(result["results"]) == 15
    assert len(requests) == 15 and len(issued) == 1
    assert all(r["reusable_answer_found"] for r in result["results"])


def test_batch_denied_short_circuits():
    ctx, _, _ = make_ctx(home="publicsector", readable=())
    result = run("search_past_answers_batch", {"questions": ["a", "b"], "team": None}, ctx)
    assert result["error"] == "access_denied" and result["library"] == "bids-publicsector"


def test_no_token_means_no_answers():
    ctx, requests, _ = make_ctx(token=None)
    result = run("search_past_answers", {"question": "x", "team": None}, ctx)
    assert result["error"] == "token_unavailable" and not requests


def test_unknown_team_and_missing_home_team():
    ctx, _, _ = make_ctx(home=None)
    assert run("search_past_answers", {"question": "x", "team": None}, ctx)["error"] == "no_home_team"
    assert run("search_past_answers", {"question": "x", "team": "retail"}, ctx)["error"] == "unknown_team"
    assert run("nope", {}, ctx)["error"] == "unknown_tool"


def test_search_not_configured():
    ctx = BidContext(teams=dict(DEFAULT_BID_TEAMS), home_team="banking")
    assert run("search_past_answers", {"question": "x", "team": None}, ctx)["error"] == "search_not_configured"


def test_list_bid_teams_reads_no_data():
    ctx, requests, issued = make_ctx()
    result = run("list_bid_teams", {}, ctx)
    assert result["your_team"] == "banking" and len(result["teams"]) == 2
    assert not requests and not issued


def test_semantic_fallback_to_keyword():
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body.get("queryType"))
        if body.get("queryType") == "semantic":
            return httpx.Response(400, json={"error": {"message": "Semantic search is not enabled for this service."}})
        return httpx.Response(200, json={"value": []})

    client = SearchClient("https://s", http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert asyncio.run(client.search("bids-banking", "q", "t")) == []
    assert seen == ["semantic", None]


def test_bid_teams_env_override(monkeypatch):
    monkeypatch.setenv("BID_TEAMS", json.dumps({"Banking": {"index": "x-bank", "label": "Bank"}}))
    assert load_bid_teams() == {"banking": {"index": "x-bank", "label": "Bank"}}
    monkeypatch.setenv("BID_TEAMS", "not json")
    assert load_bid_teams()["publicsector"]["index"] == "bids-publicsector"
