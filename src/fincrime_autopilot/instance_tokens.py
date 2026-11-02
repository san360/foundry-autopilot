"""Per-instance Entra tokens for Azure resources (for example Azure AI Search).

One hosted container serves every hired instance. The container's own credential
(the default instance identity) is shared, so calls that must be authorised per
instance use the identity of the instance that received the activity:

* ``agent_identity`` (autonomous, app-only): the blueprint exchange token (T1, from
  the Agents SDK connection) is the client assertion of the instance's agent identity,
  which requests ``<resource>/.default``. Azure RBAC is assigned to the agent identity
  service principal. No OAuth consent is needed for Azure data-plane roles.
  https://learn.microsoft.com/entra/agent-id/agent-autonomous-app-oauth-flow
* ``agent_user`` (the agent's own user account, delegated): the same exchange the
  Microsoft 365 MCP tokens use. Needs a delegated grant for the resource on the agent
  identity, and Azure RBAC on the agent user.
* ``session_identity``: the hosted-agent token service called without a client ID
  returns a token for the agent identity of the instance the current session serves
  (same identity as ``agent_identity``, obtained by the platform instead of the SDK).
* ``container``: the shared container credential, for comparison in ``/whoami``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from . import token_debug

logger = logging.getLogger(__name__)

FLOW_AGENT_IDENTITY = "agent_identity"
FLOW_AGENT_USER = "agent_user"
FLOW_SESSION_IDENTITY = "session_identity"
FLOW_CONTAINER = "container"
FLOWS = (FLOW_AGENT_IDENTITY, FLOW_AGENT_USER, FLOW_SESSION_IDENTITY, FLOW_CONTAINER)

_REFRESH_MARGIN_SECONDS = 300


def normalize_flow(value: Optional[str], default: str = FLOW_AGENT_IDENTITY) -> str:
    text = (value or "").strip().lower().replace("-", "_")
    aliases = {"identity": FLOW_AGENT_IDENTITY, "app": FLOW_AGENT_IDENTITY, "user": FLOW_AGENT_USER, "session": FLOW_SESSION_IDENTITY}
    text = aliases.get(text, text)
    return text if text in FLOWS else default


def resource_scope(resource: str) -> str:
    return resource.rstrip("/") + "/.default"


@dataclass
class TurnIdentity:
    """Who received this activity: the hired instance's names and IDs."""

    instance_name: str = ""
    agentic_app_id: str = ""
    agentic_user_id: str = ""
    tenant_id: str = ""

    @classmethod
    def from_context(cls, context: Any) -> "TurnIdentity":
        activity = getattr(context, "activity", None)
        recipient = getattr(activity, "recipient", None)
        conversation = getattr(activity, "conversation", None)

        def call(name: str) -> str:
            method = getattr(activity, name, None)
            if callable(method):
                try:
                    return str(method() or "")
                except Exception:  # noqa: BLE001 - optional SDK helpers
                    return ""
            return ""

        return cls(
            instance_name=str(getattr(recipient, "name", "") or ""),
            agentic_app_id=call("get_agentic_instance_id") or str(getattr(recipient, "agentic_app_id", "") or ""),
            agentic_user_id=call("get_agentic_user") or str(getattr(recipient, "agentic_user_id", "") or ""),
            tenant_id=call("get_agentic_tenant_id")
            or str(getattr(recipient, "tenant_id", "") or getattr(conversation, "tenant_id", "") or ""),
        )

    def debug_kwargs(self) -> dict[str, Any]:
        return {
            "instance_name": self.instance_name or None,
            "agentic_user_id": self.agentic_user_id or None,
            "agentic_app_id": self.agentic_app_id or None,
        }


@dataclass
class InstanceToken:
    flow: str
    scope: str
    token: Optional[str] = field(default=None, repr=False)
    error: Optional[str] = None
    summary: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.token)


def _default_msal_factory(client_id: str, authority: str, assertion: str) -> Any:
    import msal

    return msal.ConfidentialClientApplication(
        client_id=client_id,
        authority=authority,
        client_credential={"client_assertion": assertion},
    )


def _exp(token: str) -> float:
    claims = token_debug.decode_claims(token) or {}
    exp = claims.get("exp")
    return float(exp) if isinstance(exp, (int, float)) else 0.0


class InstanceTokenProvider:
    def __init__(
        self,
        *,
        connection_manager: Any = None,
        container_credential: Any = None,
        session_credential: Any = None,
        msal_factory: Callable[[str, str, str], Any] = _default_msal_factory,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.connection_manager = connection_manager
        self._container_credential = container_credential
        self._session_credential = session_credential
        self._msal_factory = msal_factory
        self._clock = clock
        self._cache: dict[tuple[str, str, str], tuple[str, float]] = {}

    async def get(
        self,
        flow: str,
        resource: str,
        *,
        context: Any,
        identity: TurnIdentity,
        auth: Any = None,
        auth_handler_name: Optional[str] = None,
        label: str = "",
    ) -> InstanceToken:
        flow = normalize_flow(flow)
        scope = resource_scope(resource)
        result = InstanceToken(flow=flow, scope=scope)
        key = (flow, identity.agentic_user_id if flow == FLOW_AGENT_USER else identity.agentic_app_id, scope)
        cached = self._cache.get(key)
        uncached = (FLOW_CONTAINER, FLOW_SESSION_IDENTITY)
        try:
            if flow not in uncached and cached and cached[1] - _REFRESH_MARGIN_SECONDS > self._clock():
                result.token = cached[0]
            elif flow == FLOW_AGENT_IDENTITY:
                result.token = await self._agent_identity_token(context, identity, scope)
            elif flow == FLOW_AGENT_USER:
                result.token = await self._agent_user_token(auth, auth_handler_name, context, scope)
            elif flow == FLOW_SESSION_IDENTITY:
                result.token = await self._session_token(scope)
            else:
                result.token = await self._container_token(scope)
            if not result.token:
                result.error = result.error or "no token returned"
            elif flow not in uncached:
                self._cache[key] = (result.token, _exp(result.token))
        except Exception as ex:  # noqa: BLE001 - report, never crash the turn
            logger.warning("Token acquisition failed (flow=%s, scope=%s): %s", flow, scope, ex)
            result.token = None
            result.error = f"{type(ex).__name__}: {str(ex)[:300]}"
        result.summary = token_debug.summarize(result.token, label=label or f"{flow}:{resource}", **identity.debug_kwargs())
        if result.token:
            token_debug.log_token(result.token, label=label or f"{flow}:{resource}", **identity.debug_kwargs())
        return result

    def _connection(self, context: Any) -> Any:
        if self.connection_manager is None:
            raise RuntimeError("No Agents SDK connection manager is attached to the agent.")
        try:
            return self.connection_manager.get_token_provider(getattr(context, "identity", None), "agentic")
        except Exception:  # noqa: BLE001 - fall back to the default connection
            return self.connection_manager.get_default_connection()

    async def _agent_identity_token(self, context: Any, identity: TurnIdentity, scope: str) -> Optional[str]:
        if not identity.agentic_app_id or not identity.tenant_id:
            raise RuntimeError("The activity has no agentic instance ID or tenant ID (not an agentic request).")
        connection = self._connection(context)
        exchange_token = await connection.get_agentic_application_token(identity.tenant_id, identity.agentic_app_id)
        if not exchange_token:
            raise RuntimeError("The blueprint exchange token (T1) was not issued.")
        authority = f"https://login.microsoftonline.com/{identity.tenant_id}"
        app = self._msal_factory(identity.agentic_app_id, authority, exchange_token)
        payload = await asyncio.to_thread(app.acquire_token_for_client, [scope])
        payload = payload or {}
        if not payload.get("access_token"):
            codes = payload.get("error_codes") or []
            raise RuntimeError(f"{payload.get('error', 'no_token')} {codes} {str(payload.get('error_description', ''))[:200]}")
        return payload["access_token"]

    @staticmethod
    async def _agent_user_token(auth: Any, auth_handler_name: Optional[str], context: Any, scope: str) -> Optional[str]:
        if not auth or not auth_handler_name:
            raise RuntimeError("No agentic auth handler is configured (AUTH_HANDLER_NAME).")
        exchanged = await auth.exchange_token(context, scopes=[scope], auth_handler_id=auth_handler_name)
        return getattr(exchanged, "token", None) or getattr(exchanged, "access_token", None)

    async def _container_token(self, scope: str) -> Optional[str]:
        if self._container_credential is None:
            raise RuntimeError("No container credential.")
        access_token = await self._container_credential.get_token(scope)
        return getattr(access_token, "token", None)

    async def _session_token(self, scope: str) -> Optional[str]:
        # The hosted-agent token service scopes this to the session's instance; outside a hosted
        # session (local runs) it fails, which /whoami reports. azure-identity caches tokens per
        # credential by resource only, so never share one credential between instances: a fresh
        # credential per call keeps one instance from receiving another's cached token.
        if self._session_credential is not None:
            access_token = await self._session_credential.get_token(scope)
            return getattr(access_token, "token", None)
        from azure.identity.aio import ManagedIdentityCredential

        async with ManagedIdentityCredential() as credential:
            access_token = await credential.get_token(scope)
        return getattr(access_token, "token", None)
