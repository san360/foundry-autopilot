import base64
import json
import logging

import pytest

from fincrime_autopilot import token_debug

AGENT_USER_OID = "aaaaaaaa-0000-1111-2222-bbbbbbbbbbbb"
AGENT_APP_ID = "11112222-bbbb-3333-cccc-4444dddd5555"
BLUEPRINT_ID = "069c4c09-3c03-44fb-b365-f02c72c9afde"
DEFAULT_INSTANCE = "e5a51dc4-bed4-4348-b41d-2cafebe52d12"
SIGNATURE = "SIGNATURE-must-never-appear"


def b64(obj) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")


def jwt(**claims) -> str:
    return f"{b64({'alg': 'RS256', 'typ': 'JWT'})}.{b64(claims)}.{SIGNATURE}"


AGENT_USER_TOKEN = jwt(
    aud="https://search.azure.com", tid="tenant-1", oid=AGENT_USER_OID, azp=AGENT_APP_ID, idtyp="user",
    xms_sub_fct="1 13", xms_act_fct="3 11", xms_par_app_azp=BLUEPRINT_ID, scp="user_impersonation", exp=4_000,
)
AGENT_IDENTITY_TOKEN = jwt(
    aud="https://search.azure.com", tid="tenant-1", oid="sp-oid", appid=AGENT_APP_ID, idtyp="app",
    xms_sub_fct="9 3 11", xms_act_fct="3 9 11", xms_par_app_azp=BLUEPRINT_ID, exp=4_000,
)
CONTAINER_TOKEN = jwt(aud="https://ai.azure.com", oid="mi-oid", appid=DEFAULT_INSTANCE, idtyp="app", xms_sub_fct="11", exp=4_000)


def test_decode_claims_reads_payload_only_and_rejects_non_jwts():
    assert token_debug.decode_claims(AGENT_USER_TOKEN)["oid"] == AGENT_USER_OID
    for bad in (None, "", "abc", "a.b", "a.!!!.c", f"{b64('not-a-dict')}.{b64('x')}.s"):
        assert token_debug.decode_claims(bad) is None


@pytest.mark.parametrize(
    ("token", "kind"),
    [
        (AGENT_USER_TOKEN, token_debug.KIND_AGENT_USER),
        (AGENT_IDENTITY_TOKEN, token_debug.KIND_AGENT_IDENTITY),
        (CONTAINER_TOKEN, token_debug.KIND_CONTAINER),
        (jwt(idtyp="user", oid="human", azp=AGENT_APP_ID, xms_act_fct="11"), token_debug.KIND_HUMAN_DELEGATED),
        (jwt(idtyp="app", appid="some-app"), token_debug.KIND_APP),
    ],
)
def test_classify_agent_token_kinds(token, kind):
    claims = token_debug.decode_claims(token)
    assert token_debug.classify(claims, default_instance_client_id=DEFAULT_INSTANCE) == kind


def test_summary_maps_instance_and_never_contains_token_material():
    summary = token_debug.summarize(
        AGENT_USER_TOKEN, label="search", instance_name="BankingBids",
        agentic_user_id=AGENT_USER_OID, agentic_app_id=AGENT_APP_ID, now=1_000,
    )
    assert summary["kind"] == token_debug.KIND_AGENT_USER
    assert summary["instance"] == "BankingBids"
    assert summary["xms_par_app_azp"] == BLUEPRINT_ID
    assert summary["expires_in_min"] == 50
    line = token_debug.format_summary(summary)
    assert "kind=agent-user" in line and "instance=BankingBids" in line and "aud=https://search.azure.com" in line
    rendered = json.dumps(summary) + line + json.dumps(token_debug.dimensions(summary))
    assert SIGNATURE not in rendered and AGENT_USER_TOKEN not in rendered
    assert AGENT_USER_TOKEN.split(".")[1] not in rendered


def test_summary_for_missing_or_opaque_tokens():
    assert token_debug.summarize(None, label="x")["kind"] == "no-token"
    assert token_debug.summarize("opaque", label="x")["kind"] == "not-a-jwt"


def test_instance_not_claimed_for_another_identity():
    summary = token_debug.summarize(
        AGENT_IDENTITY_TOKEN, label="search", instance_name="PublicSectorBids",
        agentic_user_id="other-user", agentic_app_id="other-app",
    )
    assert "instance" not in summary


def test_log_token_is_silent_unless_enabled(monkeypatch, caplog):
    monkeypatch.delenv("TOKEN_DEBUG", raising=False)
    with caplog.at_level(logging.INFO):
        assert token_debug.log_token(AGENT_USER_TOKEN, label="mcp") is None
    assert not caplog.records

    monkeypatch.setenv("TOKEN_DEBUG", "true")
    with caplog.at_level(logging.INFO):
        summary = token_debug.log_token(AGENT_USER_TOKEN, label="mcp")
    assert summary["kind"] == token_debug.KIND_AGENT_USER
    record = caplog.records[-1]
    assert getattr(record, "token_kind") == "agent-user"
    assert getattr(record, "token_oid") == AGENT_USER_OID
    assert SIGNATURE not in record.getMessage()


def test_dimensions_are_flat_strings():
    dims = token_debug.dimensions(token_debug.summarize(AGENT_IDENTITY_TOKEN, label="search"))
    assert dims["token_kind"] == "agent-identity"
    assert dims["token_sub_fct"] == "9 3 11"
    assert all(isinstance(v, str) for v in dims.values())


def test_footer_and_trail_prefer_per_instance_search_token():
    trail = token_debug.TokenTrail()
    trail.add(token_debug.summarize(jwt(aud="ea9ffc3e-mcp", idtyp="user", xms_sub_fct="13", oid=AGENT_USER_OID), label="mcp"))
    trail.add(token_debug.summarize(AGENT_IDENTITY_TOKEN, label="search", instance_name="BankingBids", agentic_app_id=AGENT_APP_ID))
    trail.add(token_debug.summarize(CONTAINER_TOKEN, label="container", default_instance_client_id=DEFAULT_INSTANCE))
    trail.add(token_debug.summarize(None, label="ignored"))
    preferred = trail.preferred()
    assert preferred["label"] == "search"
    line = token_debug.footer(preferred)
    assert line == f"Acted as: BankingBids · agent identity {AGENT_APP_ID[:8]} · token for https://search.azure.com"
    assert token_debug.footer(None) == ""


def test_footer_flag(monkeypatch):
    monkeypatch.delenv("TOKEN_FOOTER", raising=False)
    assert not token_debug.footer_enabled()
    monkeypatch.setenv("TOKEN_FOOTER", "true")
    assert token_debug.footer_enabled()


def test_logging_credential_wrapper_passes_through(monkeypatch, caplog):
    import asyncio
    from types import SimpleNamespace

    class Inner:
        calls = 0

        async def get_token(self, *scopes, **kwargs):
            Inner.calls += 1
            return SimpleNamespace(token=CONTAINER_TOKEN, expires_on=4_000)

    monkeypatch.setenv("TOKEN_DEBUG", "true")
    credential = token_debug.LoggingTokenCredential(Inner())
    with caplog.at_level(logging.INFO):
        first = asyncio.run(credential.get_token("https://ai.azure.com/.default"))
        asyncio.run(credential.get_token("https://ai.azure.com/.default"))
    assert first.token == CONTAINER_TOKEN and Inner.calls == 2
    token_lines = [r for r in caplog.records if "token[container" in r.getMessage()]
    assert len(token_lines) == 1
