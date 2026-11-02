import asyncio
from types import SimpleNamespace

from fincrime_autopilot import instance_tokens
from fincrime_autopilot.instance_tokens import (
    FLOW_AGENT_IDENTITY,
    FLOW_AGENT_USER,
    FLOW_CONTAINER,
    FLOW_SESSION_IDENTITY,
    InstanceTokenProvider,
    TurnIdentity,
    normalize_flow,
)
from test_token_debug import AGENT_APP_ID, AGENT_IDENTITY_TOKEN, AGENT_USER_OID, AGENT_USER_TOKEN, CONTAINER_TOKEN

TENANT = "5b26daf8-1d7a-47f5-bb8d-cbee1e80a381"


def identity():
    return TurnIdentity(instance_name="BankingBids", agentic_app_id=AGENT_APP_ID, agentic_user_id=AGENT_USER_OID, tenant_id=TENANT)


class FakeConnection:
    def __init__(self):
        self.calls = []

    async def get_agentic_application_token(self, tenant_id, instance_id):
        self.calls.append((tenant_id, instance_id))
        return "T1-exchange-token"


class FakeConnectionManager:
    def __init__(self):
        self.connection = FakeConnection()

    def get_token_provider(self, claims_identity, service_url):
        assert service_url == "agentic"
        return self.connection


class FakeCca:
    created = []

    def __init__(self, client_id, authority, assertion, payload):
        self.client_id, self.authority, self.assertion, self.payload = client_id, authority, assertion, payload
        self.scopes = None
        FakeCca.created.append(self)

    def acquire_token_for_client(self, scopes):
        self.scopes = scopes
        return self.payload


def factory(payload):
    return lambda client_id, authority, assertion: FakeCca(client_id, authority, assertion, payload)


def test_normalize_flow():
    assert normalize_flow(None) == FLOW_AGENT_IDENTITY
    assert normalize_flow("agent-user") == FLOW_AGENT_USER
    assert normalize_flow("identity") == FLOW_AGENT_IDENTITY
    assert normalize_flow("container") == FLOW_CONTAINER
    assert normalize_flow("bogus", FLOW_AGENT_USER) == FLOW_AGENT_USER


def test_agent_identity_flow_uses_t1_as_client_assertion_and_caches():
    FakeCca.created.clear()
    manager = FakeConnectionManager()
    provider = InstanceTokenProvider(
        connection_manager=manager, msal_factory=factory({"access_token": AGENT_IDENTITY_TOKEN}), clock=lambda: 1_000,
    )
    context = SimpleNamespace(identity=object())
    first = asyncio.run(provider.get(FLOW_AGENT_IDENTITY, "https://search.azure.com", context=context, identity=identity()))
    assert first.ok and first.scope == "https://search.azure.com/.default"
    cca = FakeCca.created[0]
    assert cca.client_id == AGENT_APP_ID
    assert cca.assertion == "T1-exchange-token"
    assert cca.authority.endswith(TENANT)
    assert cca.scopes == ["https://search.azure.com/.default"]
    assert first.summary["kind"] == "agent-identity" and first.summary["instance"] == "BankingBids"
    assert manager.connection.calls == [(TENANT, AGENT_APP_ID)]

    asyncio.run(provider.get(FLOW_AGENT_IDENTITY, "https://search.azure.com", context=context, identity=identity()))
    assert len(manager.connection.calls) == 1, "second call is served from the per-instance cache"


def test_agent_identity_flow_reports_entra_errors_without_raising():
    provider = InstanceTokenProvider(
        connection_manager=FakeConnectionManager(),
        msal_factory=factory({"error": "invalid_client", "error_codes": [700016], "error_description": "app not found"}),
    )
    result = asyncio.run(provider.get(FLOW_AGENT_IDENTITY, "https://search.azure.com", context=SimpleNamespace(identity=None), identity=identity()))
    assert not result.ok
    assert "invalid_client" in result.error and "700016" in result.error
    assert result.summary["kind"] == "no-token"


def test_agent_identity_flow_needs_agentic_request():
    provider = InstanceTokenProvider(connection_manager=FakeConnectionManager())
    result = asyncio.run(provider.get(FLOW_AGENT_IDENTITY, "https://search.azure.com", context=SimpleNamespace(), identity=TurnIdentity()))
    assert not result.ok and "agentic" in result.error


def test_agent_user_flow_uses_the_agentic_auth_handler():
    calls = []

    class Auth:
        async def exchange_token(self, context, scopes, auth_handler_id):
            calls.append((scopes, auth_handler_id))
            return SimpleNamespace(token=AGENT_USER_TOKEN)

    provider = InstanceTokenProvider()
    result = asyncio.run(provider.get(
        FLOW_AGENT_USER, "https://search.azure.com", context=SimpleNamespace(), identity=identity(),
        auth=Auth(), auth_handler_name="AGENTIC",
    ))
    assert result.ok and result.summary["kind"] == "agent-user"
    assert calls == [(["https://search.azure.com/.default"], "AGENTIC")]


def test_container_flow_uses_shared_credential():
    class Credential:
        async def get_token(self, scope):
            return SimpleNamespace(token=CONTAINER_TOKEN)

    provider = InstanceTokenProvider(container_credential=Credential())
    result = asyncio.run(provider.get(FLOW_CONTAINER, "https://search.azure.com", context=None, identity=identity()))
    assert result.ok and result.flow == FLOW_CONTAINER


def test_session_identity_flow_asks_the_token_service_without_client_id():
    scopes = []

    class Credential:
        async def get_token(self, scope):
            scopes.append(scope)
            return SimpleNamespace(token=AGENT_IDENTITY_TOKEN)

    provider = InstanceTokenProvider(session_credential=Credential())
    result = asyncio.run(provider.get("session", "https://search.azure.com", context=None, identity=identity()))
    assert result.ok and result.flow == FLOW_SESSION_IDENTITY
    assert result.summary["kind"] == "agent-identity" and result.summary["instance"] == "BankingBids"
    assert scopes == ["https://search.azure.com/.default"]


def test_session_identity_uses_a_fresh_credential_per_call(monkeypatch):
    """azure-identity caches by resource only: a shared credential would hand one instance another's token."""
    import azure.identity.aio as aio

    created = []

    class FakeMiCredential:
        def __init__(self, *args, **kwargs):
            self.closed = False
            created.append(self)

        async def get_token(self, scope):
            return SimpleNamespace(token=f"{AGENT_IDENTITY_TOKEN}{len(created)}")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            self.closed = True

    monkeypatch.setattr(aio, "ManagedIdentityCredential", FakeMiCredential)
    provider = InstanceTokenProvider()
    first = asyncio.run(provider.get("session_identity", "https://search.azure.com", context=None, identity=identity()))
    other = TurnIdentity(instance_name="PublicSectorBids", agentic_app_id="other-app", agentic_user_id="other-user", tenant_id=TENANT)
    second = asyncio.run(provider.get("session_identity", "https://search.azure.com", context=None, identity=other))
    assert len(created) == 2 and all(c.closed for c in created)
    assert first.token != second.token


def test_turn_identity_from_activity():
    recipient = SimpleNamespace(name="BankingBids", agentic_app_id=AGENT_APP_ID, agentic_user_id=AGENT_USER_OID, tenant_id=TENANT)
    context = SimpleNamespace(activity=SimpleNamespace(recipient=recipient, conversation=None))
    ident = TurnIdentity.from_context(context)
    assert (ident.instance_name, ident.agentic_app_id, ident.agentic_user_id, ident.tenant_id) == (
        "BankingBids", AGENT_APP_ID, AGENT_USER_OID, TENANT,
    )
    assert instance_tokens.resource_scope("https://search.azure.com/") == "https://search.azure.com/.default"
