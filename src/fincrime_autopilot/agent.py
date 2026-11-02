# Copyright (c) Microsoft. All rights reserved.

"""FinCrime Alert Triage autopilot - Contoso Bank (synthetic demo).

Forked from the official Microsoft Foundry autopilot sample
(microsoft-foundry/foundry-samples, samples/python/foundry-autopilot-agent).
The activity handling, notification routing and per-turn agentic token
exchange are kept from the sample; the "brain" is replaced with:

* FinCrime instructions (``prompts.py``),
* read-only, deterministic FSI function tools over synthetic bank data
  (``fsi_tools.py``) executed locally through a Responses API tool loop
  (``tool_loop.py``), alongside the Microsoft 365 MCP servers and the
  Foundry Toolbox that Foundry executes server-side,
* code-level guardrails (``guardrails.py``): NO_REPLY, sender-domain and
  cross-tenant filtering, tipping-off detection and per-instance segment
  entitlement.
"""

from __future__ import annotations

import base64
import html
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, urlparse

from azure.ai.projects.aio import AIProjectClient
from azure.identity.aio import (
    AzureCliCredential,
    DefaultAzureCredential,
    ManagedIdentityCredential,
)
from openai import APIStatusError, AsyncOpenAI

from microsoft_agents.hosting.core import Authorization, TurnContext

from .request_correlation import set_current_span_response

try:
    from microsoft_agents_a365.notifications.agent_notification import NotificationTypes
except Exception:  # pragma: no cover - optional dependency
    NotificationTypes = None  # type: ignore[assignment]

from .agent_interface import AgentInterface
from . import token_debug
from .email_channel_compat import is_email_activity, is_email_notification, raw_conversation_topic
from .fsi_data import load_bank_data
from .fsi_tools import TOOL_SCHEMAS, ToolContext, execute_tool
from .guardrails import (
    NO_REPLY,
    detect_tipping_off_request,
    is_cross_tenant,
    is_no_reply,
    parse_domains,
    resolve_allowed_segments,
    sender_allowed,
)
from .instance_tokens import (
    FLOW_AGENT_IDENTITY,
    FLOW_AGENT_USER,
    FLOW_CONTAINER,
    FLOW_SESSION_IDENTITY,
    InstanceToken,
    InstanceTokenProvider,
    TurnIdentity,
    normalize_flow,
)
from .prompts import CONTENT_FILTER_MESSAGE, TIPPING_OFF_NOTICE, build_instructions, is_content_filter_error
from .rfp_prompts import COMMENT_GUIDANCE, build_rfp_instructions, is_daily_check
from .rfp_tools import RFP_TOOL_SCHEMAS, BidContext, execute_rfp_tool, load_bid_teams, resolve_home_team
from .scenario import SCENARIO_RFP, current_scenario, parse_whoami, parse_whoami_subject
from .search_client import SEARCH_RESOURCE, SearchAccessDenied, SearchClient, SearchError
from .tool_loop import FunctionExecutor, function_calls, run_responses_with_tools

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants — mirrors the values in the C# ResponsesApiAgentLogicService
# ---------------------------------------------------------------------------

# Audience used to acquire the agentic-user token that the MCP servers accept.
# Matches the C# ResponsesApiAgentLogicServiceFactory.
MCP_SCOPE = "ea9ffc3e-8a23-4a7d-836d-234d7c7565c1/.default"
TOOLBOX_SCOPE = "https://ai.azure.com/.default"


@dataclass
class _Turn:
    """Per-turn tool wiring for the active scenario."""

    tool_schemas: list[dict[str, Any]]
    execute: FunctionExecutor
    scope_label: str
    calls: list[dict[str, Any]]
    trail: token_debug.TokenTrail = field(default_factory=token_debug.TokenTrail)
    identity: TurnIdentity = field(default_factory=TurnIdentity)


class FinCrimeTriageAgent(AgentInterface):
    """Contoso Bank FinCrime Alert Triage autopilot (Foundry hosted agent)."""

    # Kept for compatibility with the sample's helpers; per-turn instructions
    # are built by ``prompts.build_instructions``.
    AGENT_PROMPT = build_instructions("the FinCrime Alert Triage autopilot", "a colleague", "all segments")

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)

        self._project_endpoint = (
            os.getenv("FOUNDRY_PROJECT_ENDPOINT")
            or os.getenv("AZURE_AI_PROJECT_ENDPOINT")
        )
        self._deployment = (
            os.getenv("ModelDeployment") or os.getenv("AZURE_OPENAI_DEPLOYMENT")
        )
        if not self._project_endpoint:
            raise ValueError(
                "FOUNDRY_PROJECT_ENDPOINT (or AZURE_AI_PROJECT_ENDPOINT) is required"
            )
        if not self._deployment:
            raise ValueError(
                "ModelDeployment (or AZURE_OPENAI_DEPLOYMENT) is required"
            )

        self._instance_client_id = os.getenv("FOUNDRY_AGENT_DEFAULT_INSTANCE_CLIENT_ID")
        self._scenario = current_scenario()

        # The container credential is the shared default instance identity. The wrapper
        # only logs claim summaries when TOKEN_DEBUG=true.
        self._credential = token_debug.LoggingTokenCredential(self._build_credential(), label="container")
        self._project_client = AIProjectClient(
            endpoint=self._project_endpoint,
            credential=self._credential,
        )
        self._openai_client: AsyncOpenAI = self._project_client.get_openai_client()

        self._mcp_servers = self._load_mcp_servers()
        self._toolbox_endpoint = os.getenv("TOOLBOX_ENDPOINT", "").strip()
        self._enforce_mcp_allowlist = os.getenv("MCP_ENFORCE_ALLOWLIST", "true").strip().lower() != "false"
        self._logged_mcp_tool_lists: set[str] = set()

        # Per-instance tokens (the connection manager is attached by the host).
        self._token_provider = InstanceTokenProvider(container_credential=self._credential)
        self._footer_enabled = token_debug.footer_enabled()

        # RFP Bid Desk configuration (AUTOPILOT_SCENARIO=rfp).
        search_endpoint = os.getenv("SEARCH_ENDPOINT", "").strip()
        self._search: Optional[SearchClient] = SearchClient(search_endpoint) if search_endpoint else None
        self._search_token_flow = normalize_flow(os.getenv("SEARCH_TOKEN_FLOW"), FLOW_AGENT_IDENTITY)
        self._bid_teams = load_bid_teams()
        self._team_chat_name = os.getenv("BID_TEAM_CHAT_NAME", "").strip() or None

        # FinCrime brain configuration.
        self._bank_data = load_bank_data()
        self._allowed_sender_domains = parse_domains(os.getenv("ALLOWED_SENDER_DOMAINS"))
        self._expected_tenant_id = (
            os.getenv("CONNECTIONS__SERVICE_CONNECTION__SETTINGS__TENANTID")
            or os.getenv("TENANT_ID")
            or ""
        ).strip()
        self._notify_chat_name = os.getenv("TRIAGE_NOTIFY_CHAT_NAME", "").strip() or None
        self._max_tool_rounds = int(os.getenv("MAX_TOOL_ROUNDS", "8"))

        # Persisted previous_response_id store (mirrors C# behaviour).
        self._response_store_dir = Path.home() / ".a365agent"

        logger.info(
            "✅ %s autopilot ready (project_endpoint=%s, deployment=%s, "
            "mcp_servers=%d, toolbox_enabled=%s, function_tools=%d, allowed_sender_domains=%s, "
            "search=%s, search_token_flow=%s, token_debug=%s)",
            self._scenario,
            self._project_endpoint,
            self._deployment,
            len(self._mcp_servers),
            bool(self._toolbox_endpoint),
            len(RFP_TOOL_SCHEMAS if self._scenario == SCENARIO_RFP else TOOL_SCHEMAS),
            sorted(self._allowed_sender_domains) or "any",
            bool(self._search),
            self._search_token_flow,
            token_debug.enabled(),
        )

    def attach_connection_manager(self, connection_manager: Any) -> None:
        """Called by the host: the Agents SDK connections issue the per-instance exchange tokens."""
        self._token_provider.connection_manager = connection_manager

    def _build_credential(self):
        if self._instance_client_id:
            logger.info(
                "Using managed identity (client_id=%s) for Foundry",
                self._instance_client_id,
            )
            return ManagedIdentityCredential(client_id=self._instance_client_id)
        try:
            logger.info("Using DefaultAzureCredential for Foundry")
            return DefaultAzureCredential()
        except Exception:
            logger.info("Falling back to AzureCliCredential for Foundry")
            return AzureCliCredential()

    def _load_mcp_servers(self) -> list[dict[str, Any]]:
        package_dir = Path(__file__).resolve().parent
        manifest_path = package_dir / "ToolingManifest.json"
        scenario_manifest = package_dir / f"ToolingManifest.{self._scenario}.json"
        if scenario_manifest.exists():
            manifest_path = scenario_manifest
        if not manifest_path.exists():
            logger.warning("ToolingManifest.json not found at %s", manifest_path)
            return []
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to parse ToolingManifest.json")
            return []
        configured_servers = payload.get("mcpServers") or []
        servers: list[dict[str, Any]] = []
        azure_devops_organization = os.getenv(
            "AZURE_DEVOPS_ORGANIZATION", ""
        ).strip()

        for configured_server in configured_servers:
            server = dict(configured_server)
            url = server.get("url", "")
            if "{organization}" in url:
                if not azure_devops_organization:
                    logger.info(
                        "Azure DevOps MCP server is disabled. Set "
                        "AZURE_DEVOPS_ORGANIZATION to enable it."
                    )
                    continue
                url = url.replace(
                    "{organization}",
                    quote(azure_devops_organization, safe=""),
                )
                server["url"] = url
            servers.append(server)

        logger.info("Loaded %d MCP server(s) from %s", len(servers), manifest_path.name)
        return servers

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        logger.info("Agent initialized")

    async def cleanup(self) -> None:
        try:
            await self._openai_client.close()
            await self._project_client.close()
            await self._credential.close()
            logger.info("Agent cleanup completed")
        except Exception:
            logger.exception("Cleanup error")

    # ------------------------------------------------------------------
    # Message processing
    # ------------------------------------------------------------------

    async def process_user_message(
        self,
        message: str,
        auth: Authorization,
        auth_handler_name: Optional[str],
        context: TurnContext,
    ) -> str:
        from_prop = context.activity.from_property
        logger.info(
            "Turn received from user — DisplayName: '%s', UserId: '%s', AadObjectId: '%s'",
            getattr(from_prop, "name", None) or "(unknown)",
            getattr(from_prop, "id", None) or "(unknown)",
            getattr(from_prop, "aad_object_id", None) or "(none)",
        )

        if self._is_cross_tenant(context):
            logger.warning("Ignoring cross-tenant activity (expected tenant %s)", self._expected_tenant_id)
            return NO_REPLY

        display_name = getattr(from_prop, "name", None) or "a colleague"
        turn = self._build_turn(context, auth, auth_handler_name)
        include_teams_mcp = True
        channel = "teams"
        daily_check = False
        channel_id = str(getattr(context.activity, "channel_id", "") or "")
        # Agent 365 delivers email as a message on the "agents" channel with a productInfo
        # "email" entity and the subject in conversation.topic; older payloads used "email".
        is_email_channel, subject, email_message_id = self._email_context(context.activity)
        sender_id = getattr(from_prop, "id", "") if from_prop else ""

        if is_email_channel and not sender_allowed([sender_id, getattr(from_prop, "name", "")], self._allowed_sender_domains):
            logger.warning("Ignoring email from sender outside allowed domains: %s", sender_id)
            return NO_REPLY

        whoami = parse_whoami(message)
        if whoami is None and is_email_channel:
            whoami = parse_whoami_subject(subject)
        if whoami is not None:
            report = await self._whoami_lines(auth, auth_handler_name, context, probe=whoami == "probe")
            if not is_email_channel:
                return self._render_lines(report, "teams")
            # On this path the host does not send the return value: the Mail tool sends the report.
            message = (
                f"Reply to the email from {sender_id} (subject: {subject or '/whoami'}) with the Mail tool"
                f"{self._reply_hint(email_message_id)}. "
                "The reply body must be exactly the HTML below, unchanged. Do not call any other tool. "
                f"Then answer exactly {NO_REPLY}.\n\n{self._render_lines(report, 'email')}"
            )
            return await self._invoke_responses_api(
                input_text=message,
                conversation_id=f"whoami:{getattr(getattr(context.activity, 'conversation', None), 'id', '')}",
                instructions=self._instructions(context, display_name, turn, "email"),
                auth=auth,
                auth_handler_name=auth_handler_name,
                context=context,
                turn=turn,
                function_tools=False,
                channel="email",
            )

        # Reshape incoming email text so the model can reply through the email tool.
        # Ordinary Teams replies are returned to the host; only explicit outbound
        # messaging requests receive the Teams MCP tool.
        # Mirrors ResponsesApiAgentLogicService.NewActivityReceived.
        if is_email_channel:
            channel = "email"
            daily_check = self._scenario == SCENARIO_RFP and is_daily_check(subject, message)
            # On this path the host does not send the return value (unlike email
            # notifications), so any reply must go out through the Mail tool.
            if daily_check:
                message = (
                    f"Scheduled email From: {sender_id}\nSubject: {subject}\nMessage: {message}\n\n"
                    f"This is the scheduler, not a person: do not reply by email. Answer exactly {NO_REPLY} when done."
                )
            else:
                message = (
                    f"Please respond to this email From: {sender_id}\n"
                    f"Subject: {subject}\nMessage: {message}\n\n"
                    f"Send your reply to the sender with the Mail tool{self._reply_hint(email_message_id)}, "
                    "formatted as simple HTML. "
                    f"If no reply is appropriate, answer exactly {NO_REPLY} and send nothing."
                )
        elif channel_id.lower() == "msteams":
            include_teams_mcp = self._is_outbound_teams_request(message)
            if not include_teams_mcp:
                message = (
                    "Reply directly to the current Teams conversation. Do not use "
                    f"the Teams MCP tool.\nUser message: {message}"
                )

        if self._scenario != SCENARIO_RFP and detect_tipping_off_request(message):
            logger.info("Tipping-off control notice added to the turn")
            message = TIPPING_OFF_NOTICE + message

        instructions = self._instructions(context, display_name, turn, channel, daily_check=daily_check)

        conversation = getattr(context.activity, "conversation", None)
        conversation_id = getattr(conversation, "id", "") or "default"

        try:
            response = await self._invoke_responses_api(
                input_text=message,
                conversation_id=conversation_id,
                instructions=instructions,
                auth=auth,
                auth_handler_name=auth_handler_name,
                context=context,
                include_teams_mcp=include_teams_mcp,
                turn=turn,
                channel=channel,
            )
            return response or "Done."
        except Exception as ex:
            logger.exception("Error processing message")
            return f"Sorry, I encountered an error: {ex}"

    # ------------------------------------------------------------------
    # Scenario wiring
    # ------------------------------------------------------------------

    def _build_turn(self, context: TurnContext, auth: Optional[Authorization], auth_handler_name: Optional[str]) -> _Turn:
        identity = TurnIdentity.from_context(context)
        if self._scenario != SCENARIO_RFP:
            tool_ctx = self._build_tool_context(context)
            return _Turn(
                tool_schemas=TOOL_SCHEMAS,
                execute=lambda name, args: execute_tool(name, args, tool_ctx, self._bank_data),
                scope_label=tool_ctx.scope_label(),
                calls=tool_ctx.calls,
                identity=identity,
            )

        hints = self._instance_hints(context)
        cached: dict[str, InstanceToken] = {}

        async def get_token() -> InstanceToken:
            if "search" not in cached:
                cached["search"] = await self._token_provider.get(
                    self._search_token_flow,
                    SEARCH_RESOURCE,
                    context=context,
                    identity=identity,
                    auth=auth,
                    auth_handler_name=auth_handler_name,
                    label="search",
                )
            return cached["search"]

        bid_ctx = BidContext(
            teams=self._bid_teams,
            home_team=resolve_home_team(hints, self._bid_teams),
            instance_label=identity.instance_name or " | ".join(hints),
            get_token=get_token,
            search=self._search,
        )
        logger.info("Instance hints=%s -> home bid team=%s", hints, bid_ctx.home_team)
        return _Turn(
            tool_schemas=RFP_TOOL_SCHEMAS,
            execute=lambda name, args: execute_rfp_tool(name, args, bid_ctx),
            scope_label=bid_ctx.scope_label(),
            calls=bid_ctx.calls,
            trail=bid_ctx.trail,
            identity=identity,
        )

    def _instructions(
        self,
        context: TurnContext,
        user_name: str,
        turn: _Turn,
        channel: str = "teams",
        *,
        daily_check: bool = False,
    ) -> str:
        agent_name = self._agent_display_name(context)
        if self._scenario == SCENARIO_RFP:
            return build_rfp_instructions(
                agent_name,
                user_name,
                turn.scope_label,
                channel=channel,
                team_chat_name=self._team_chat_name,
                daily_check=daily_check,
            )
        return build_instructions(
            agent_name,
            user_name,
            turn.scope_label,
            channel=channel,
            notify_chat_name=self._notify_chat_name,
        )

    # ------------------------------------------------------------------
    # Token inspector (/whoami)
    # ------------------------------------------------------------------

    async def _whoami_lines(
        self,
        auth: Optional[Authorization],
        auth_handler_name: Optional[str],
        context: TurnContext,
        *,
        probe: bool = False,
    ) -> list[str]:
        """Claims of every identity this instance uses, plus live Search checks. Never raw tokens."""
        if not token_debug.enabled():
            return ["The token inspector is off. An admin can enable it with TOKEN_DEBUG=true on the agent version."]

        identity = TurnIdentity.from_context(context)
        lines = [
            f"/whoami - {identity.instance_name or 'this instance'} (claims only; raw tokens are never shown)",
            f"Agent identity (actor, azp): {identity.agentic_app_id or '?'}",
            f"Agent user (oid): {identity.agentic_user_id or '?'}",
            f"Tenant: {identity.tenant_id or '?'}",
        ]

        mcp_token = await self._acquire_mcp_token(auth, auth_handler_name, context, scope=MCP_SCOPE)
        mcp_summary = token_debug.summarize(mcp_token, label="mcp", **identity.debug_kwargs())
        lines.append("1. Microsoft 365 tools (MCP): " + token_debug.format_summary(mcp_summary))

        container = await self._token_provider.get(
            FLOW_CONTAINER, SEARCH_RESOURCE if self._search else "https://ai.azure.com",
            context=context, identity=identity, label="container",
        )
        lines.append("2. Shared container credential (Foundry calls): " + (
            token_debug.format_summary(container.summary) if container.ok else f"unavailable ({container.error})"
        ))

        if self._search is None:
            lines.append("3. Azure AI Search: not configured for this agent (SEARCH_ENDPOINT).")
            return lines

        flows = [self._search_token_flow]
        if probe:
            flows += [f for f in (FLOW_AGENT_IDENTITY, FLOW_SESSION_IDENTITY, FLOW_AGENT_USER) if f not in flows]
        for flow in flows:
            token = await self._token_provider.get(
                flow, SEARCH_RESOURCE, context=context, identity=identity,
                auth=auth, auth_handler_name=auth_handler_name, label=f"search:{flow}",
            )
            marker = " (configured)" if flow == self._search_token_flow else ""
            if not token.ok:
                lines.append(f"3. Search token, flow {flow}{marker}: unavailable ({token.error})")
                continue
            lines.append(f"3. Search token, flow {flow}{marker}: " + token_debug.format_summary(token.summary))
            lines.extend(await self._probe_libraries(token, f"   as {flow}"))
        if probe:
            lines.extend(await self._probe_libraries(container, "   as shared container"))
        return lines

    async def _probe_libraries(self, token: InstanceToken, prefix: str) -> list[str]:
        if not token.ok or self._search is None:
            return []
        results = []
        for team, cfg in self._bid_teams.items():
            try:
                hits = await self._search.search(cfg["index"], "*", token.token or "", top=1, semantic=False)
                results.append(f"{prefix}: {cfg['index']} -> HTTP 200 (readable, {len(hits)} sample)")
            except SearchAccessDenied as ex:
                results.append(f"{prefix}: {cfg['index']} -> HTTP {ex.status} refused by Azure RBAC")
            except SearchError as ex:
                results.append(f"{prefix}: {cfg['index']} -> HTTP {ex.status} {ex.code}")
            except Exception as ex:  # noqa: BLE001 - diagnostics only
                results.append(f"{prefix}: {cfg['index']} -> error {type(ex).__name__}")
        return results

    @staticmethod
    def _render_lines(lines: list[str], channel: str) -> str:
        if channel == "email":
            return "<p>" + "<br>".join(html.escape(line) for line in lines) + "</p>"
        if channel == "comment":
            return "\n".join(lines)
        head, *rest = lines
        return f"**{head}**\n\n" + "\n".join(f"- {line.strip()}" for line in rest)

    def _with_footer(self, text: str, turn: _Turn, channel: str) -> str:
        if not self._footer_enabled or not text or is_no_reply(text):
            return text
        line = token_debug.footer(turn.trail.preferred(), turn.identity.instance_name)
        if not line:
            return text
        if channel == "email":
            return f"{text}<p><small><em>{html.escape(line)}</em></small></p>"
        return f"{text}\n\n_{line}_"

    # ------------------------------------------------------------------
    # FinCrime helpers
    # ------------------------------------------------------------------

    def _is_cross_tenant(self, context: TurnContext) -> bool:
        conversation = getattr(context.activity, "conversation", None)
        tenant_id = getattr(conversation, "tenant_id", None)
        if not tenant_id:
            recipient = getattr(context.activity, "recipient", None)
            tenant_id = getattr(recipient, "tenant_id", None)
        return is_cross_tenant(tenant_id, self._expected_tenant_id)

    @staticmethod
    def _agent_display_name(context: TurnContext) -> str:
        recipient = getattr(context.activity, "recipient", None)
        return getattr(recipient, "name", None) or ""

    @staticmethod
    def _instance_hints(context: TurnContext) -> list[str]:
        recipient = getattr(context.activity, "recipient", None)
        hints = [
            getattr(recipient, "name", None),
            getattr(recipient, "id", None),
            getattr(recipient, "agentic_user_id", None),
            getattr(recipient, "agentic_user", None),
            getattr(recipient, "role", None),
        ]
        return [str(h) for h in hints if h]

    def _build_tool_context(self, context: TurnContext) -> ToolContext:
        hints = self._instance_hints(context)
        allowed = resolve_allowed_segments(hints)
        ctx = ToolContext(allowed_segments=allowed, instance_label=" | ".join(hints))
        logger.info("Instance hints=%s -> entitled segments=%s", hints, ctx.scope_label())
        return ctx

    @staticmethod
    def _email_context(activity: Any) -> tuple[bool, str, str]:
        """(is_email, subject, Exchange message ID) for an incoming message activity."""
        entities = getattr(activity, "entities", None) or []

        def entity_value(entity: Any, name: str) -> Any:
            if isinstance(entity, dict):
                return entity.get(name)
            value = getattr(entity, name, None)
            if value is None:
                extra = getattr(entity, "model_extra", None) or {}
                value = extra.get(name)
            return value

        notification = next(
            (e for e in entities if str(entity_value(e, "type") or "").lower() == "emailnotification"), None
        )
        is_email = is_email_activity(activity) or notification is not None
        if not is_email:
            return False, "", ""

        subject = ""
        channel_data = getattr(activity, "channel_data", None)
        if isinstance(channel_data, dict):
            subject = str(channel_data.get("subject", "") or "")
        if not subject:
            subject = str(getattr(getattr(activity, "conversation", None), "topic", "") or "")
        if not subject:
            subject = raw_conversation_topic()
        message_id = str(entity_value(notification, "id") or "") if notification is not None else ""
        return True, subject, message_id

    @staticmethod
    def _reply_hint(message_id: str) -> str:
        return f" (ReplyToMessage on message ID {message_id})" if message_id else ""

    @staticmethod
    def _email_subject(notification_activity: Any, context: TurnContext) -> str:
        """Best-effort subject of an email notification (shape varies by SDK version)."""
        candidates = [
            getattr(getattr(notification_activity, "email", None), "subject", None),
            getattr(notification_activity, "subject", None),
        ]
        channel_data = getattr(getattr(context, "activity", None), "channel_data", None)
        if isinstance(channel_data, dict):
            candidates.append(channel_data.get("subject"))
        candidates.append(getattr(getattr(getattr(context, "activity", None), "conversation", None), "topic", None))
        candidates.append(raw_conversation_topic())
        for value in candidates:
            if isinstance(value, str) and value.strip():
                return value
        return ""

    @staticmethod
    def _is_outbound_teams_request(message: str) -> bool:
        action = r"\b(?:send|post|forward|message|notify)\b"
        destination = r"\b(?:teams|chat|channel)\b"
        return bool(
            re.search(rf"{action}.{{0,80}}{destination}", message, re.IGNORECASE)
            or re.search(rf"{destination}.{{0,80}}{action}", message, re.IGNORECASE)
        )

    # ------------------------------------------------------------------
    # Notification handling
    # ------------------------------------------------------------------

    async def handle_agent_notification_activity(
        self,
        notification_activity,
        auth: Authorization,
        auth_handler_name: Optional[str],
        context: TurnContext,
    ) -> str:
        """Handle email, Word, Excel, and PowerPoint agentic notifications."""

        try:
            notification_type = notification_activity.notification_type
            logger.info("📬 Processing notification: %s", notification_type)

            if self._is_cross_tenant(context):
                logger.warning("Ignoring cross-tenant notification")
                return NO_REPLY

            conversation = getattr(context.activity, "conversation", None)
            conversation_id = (
                getattr(conversation, "id", "") or f"notification:{notification_type}"
            )

            is_email = is_email_notification(notification_activity)
            is_wpx_comment = self._is_wpx_comment_notification(notification_type)
            turn = self._build_turn(context, auth, auth_handler_name)

            if is_email:
                from_prop = getattr(
                    notification_activity, "from_property", None
                ) or getattr(notification_activity, "from", None)
                from_email = (
                    getattr(from_prop, "id", "") or getattr(from_prop, "name", "")
                )
                if not sender_allowed(
                    [from_email, getattr(from_prop, "name", "")],
                    self._allowed_sender_domains,
                ):
                    logger.warning("Ignoring email from sender outside allowed domains: %s", from_email)
                    return NO_REPLY
                email_details = self._serialize_notification(notification_activity)
                # Email notifications: the host sends the returned HTML as the reply. Only the newest
                # message body or the subject counts, never quoted history.
                whoami = parse_whoami(getattr(notification_activity, "text", ""))
                if whoami is None:
                    whoami = parse_whoami_subject(self._email_subject(notification_activity, context))
                if whoami is not None:
                    lines = await self._whoami_lines(auth, auth_handler_name, context, probe=whoami == "probe")
                    return self._render_lines(lines, "email")
                daily_check = self._scenario == SCENARIO_RFP and is_daily_check(email_details)
                msg = (
                    "You received a new email in your own mailbox. Read it and return "
                    "your reply in simple HTML (or exactly NO_REPLY when no reply is appropriate). "
                    f"From: {from_email}\nEmail details:\n{email_details}"
                )
                if self._scenario != SCENARIO_RFP and detect_tipping_off_request(email_details):
                    msg = TIPPING_OFF_NOTICE + msg
                return await self._invoke_responses_api(
                    input_text=msg,
                    conversation_id=conversation_id,
                    instructions=self._instructions(
                        context,
                        str(getattr(from_prop, "name", "") or from_email or "a colleague"),
                        turn,
                        "email",
                        daily_check=daily_check,
                    ),
                    auth=auth,
                    auth_handler_name=auth_handler_name,
                    context=context,
                    turn=turn,
                    channel="email",
                ) or NO_REPLY

            if is_wpx_comment:
                return await self._handle_comment_notification(
                    notification_activity,
                    auth,
                    auth_handler_name,
                    context,
                )

            notification_message = (
                getattr(notification_activity, "text", "")
                or f"Notification received: {notification_type}"
            )
            return await self._invoke_responses_api(
                input_text=notification_message,
                conversation_id=conversation_id,
                instructions=self._instructions(context, "a colleague", turn),
                auth=auth,
                auth_handler_name=auth_handler_name,
                context=context,
                turn=turn,
            ) or "Notification processed successfully."
        except Exception as ex:
            logger.exception("Error processing notification")
            return f"Sorry, I encountered an error processing the notification: {ex}"

    async def _handle_comment_notification(
        self,
        notification_activity: Any,
        auth: Authorization,
        auth_handler_name: Optional[str],
        context: TurnContext,
    ) -> str:
        logger.info("Processing comment notification (Responses API)")

        comment = self._get_comment_payload(notification_activity)
        if comment is None:
            logger.warning("Comment notification received without WpxComment payload")
            return ""

        document_id = self._get_first_value(comment, "document_id", "documentId")
        comment_id = self._get_first_value(
            comment,
            "comment_id",
            "commentId",
            "initiating_comment_id",
            "initiatingCommentId",
        )
        parent_comment_id = self._get_first_value(
            comment,
            "parent_comment_id",
            "parentCommentId",
        )

        content_url = self._get_first_attachment_content_url(context)
        if not content_url:
            logger.warning(
                "Comment notification for CommentId=%s on DocumentId=%s has no attachment ContentUrl",
                comment_id,
                document_id,
            )
            return ""

        product_label, mcp_server_name = self._infer_product_from_activity(
            context.activity,
            content_url,
        )
        from_prop = getattr(
            notification_activity, "from_property", None
        ) or getattr(notification_activity, "from", None)
        commenter = (
            getattr(from_prop, "name", "")
            or getattr(from_prop, "id", "")
            or "the commenter"
        )
        comment_text = (
            getattr(context.activity, "text", "")
            or getattr(notification_activity, "text", "")
            or ""
        ).strip()
        comment_snippet = comment_text or "(no comment text)"
        document_id_for_prompt = document_id or "unknown-doc"
        comment_id_for_prompt = comment_id or "unknown-comment"
        parent_comment = parent_comment_id or "(none - this is a top-level comment)"
        conversation_id = f"comment:{document_id_for_prompt}:{comment_id_for_prompt}"
        turn = self._build_turn(context, auth, auth_handler_name)

        whoami = parse_whoami(comment_text)
        if whoami is not None:
            lines = await self._whoami_lines(auth, auth_handler_name, context, probe=whoami == "probe")
            reply_text = self._render_lines(lines, "comment")
            task = (
                f'  2. Call ReplyToComment with commentId="{comment_id_for_prompt}" and post EXACTLY the reply\n'
                "     text between the markers below, unchanged. Do not call any other tool.\n"
                f"<<<REPLY\n{reply_text}\nREPLY>>>"
            )
            function_tools = False
        else:
            task = (
                f'  2. Call ReplyToComment with commentId="{comment_id_for_prompt}" to post your\n'
                "     reply directly on the thread. Do NOT respond via chat or email - the reply\n"
                f"     must be posted through the {mcp_server_name} ReplyToComment tool so it\n"
                "     shows up on the comment thread in the document."
            )
            function_tools = True
        guidance = COMMENT_GUIDANCE.strip() if self._scenario == SCENARIO_RFP and function_tools else ""

        prompt = f"""
You have been @-mentioned in a {product_label} comment and must reply to it.

Use the {mcp_server_name} MCP tools to do the following, in order:
  1. Call GetDocumentContent with the sharing URL below to read the document and
     locate the text that the comment refers to (and the IDs needed to reply).
{task}

Keep the reply concise, helpful, and grounded in the actual document content.
Format the reply as plain text because the comment thread does not render HTML.
{guidance}

Document URL: {content_url}
DocumentId:   {document_id_for_prompt}
CommentId:    {comment_id_for_prompt}
ParentCommentId: {parent_comment}
Commenter:    {commenter}
Comment text: {comment_snippet}
""".strip()

        response = await self._invoke_responses_api(
            input_text=prompt,
            conversation_id=conversation_id,
            instructions=self._instructions(context, str(commenter), turn),
            auth=auth,
            auth_handler_name=auth_handler_name,
            context=context,
            turn=turn,
            function_tools=function_tools,
        )

        logger.info(
            "Comment reply flow finished for %s CommentId=%s. Model output (for diagnostics only): %s",
            product_label,
            comment_id_for_prompt,
            response.strip() if response and response.strip() else "(empty)",
        )
        return ""

    @staticmethod
    def _is_wpx_comment_notification(notification_type: Any) -> bool:
        if (
            NotificationTypes is not None
            and notification_type == NotificationTypes.WPX_COMMENT
        ):
            return True

        value = getattr(notification_type, "value", notification_type)
        normalized = str(value or "").lower()
        return "comment" in normalized and (
            "wpx" in normalized
            or "word" in normalized
            or "excel" in normalized
            or "powerpoint" in normalized
        )

    @staticmethod
    def _get_comment_payload(notification_activity: Any) -> Any:
        for name in (
            "wpx_comment_notification",
            "wpx_comment",
            "wpxCommentNotification",
            "wpxComment",
        ):
            value = FinCrimeTriageAgent._get_first_value(
                notification_activity,
                name,
            )
            if value:
                return value
        return None

    @staticmethod
    def _get_first_attachment_content_url(context: TurnContext) -> str:
        activity = getattr(context, "activity", None)
        attachments = getattr(activity, "attachments", None) or []
        for attachment in attachments:
            content_url = FinCrimeTriageAgent._get_first_value(
                attachment,
                "content_url",
                "contentUrl",
            )
            if content_url:
                return content_url
        return ""

    @staticmethod
    def _infer_product_from_activity(
        activity: Any,
        content_url: str,
    ) -> tuple[str, str]:
        sub_channel = ""
        channel_id = getattr(activity, "channel_id", None)
        if channel_id is not None:
            sub_channel = str(getattr(channel_id, "sub_channel", "") or "")
            if not sub_channel:
                _, _, sub_channel = str(channel_id).partition(":")

        normalized = sub_channel.lower()
        if "word" in normalized:
            return "Word", "mcp_WordServer"
        if "excel" in normalized:
            return "Excel", "mcp_ExcelServer"
        if "powerpoint" in normalized or "ppt" in normalized:
            return "PowerPoint", "mcp_PowerPointServer"

        return FinCrimeTriageAgent._infer_product_from_url(content_url)

    @staticmethod
    def _infer_product_from_url(url: str) -> tuple[str, str]:
        lower = str(url).lower()
        if ".xlsx" in lower or ".xlsm" in lower or ".xlsb" in lower:
            return "Excel", "mcp_ExcelServer"
        if ".pptx" in lower or ".ppt" in lower:
            return "PowerPoint", "mcp_PowerPointServer"
        return "Word", "mcp_WordServer"

    @staticmethod
    def _get_first_value(value: Any, *names: str) -> Any:
        if value is None:
            return ""
        if isinstance(value, dict):
            for name in names:
                item = value.get(name)
                if item is not None and item != "":
                    return item
            return ""

        for name in names:
            item = getattr(value, name, None)
            if item is not None and item != "":
                return item
        return ""

    @staticmethod
    def _serialize_notification(notification_activity: Any) -> str:
        try:
            dump_json = getattr(notification_activity, "model_dump_json", None)
            if callable(dump_json):
                return dump_json(indent=2)
        except Exception as ex:
            logger.warning(
                "Failed to serialize notification via model_dump_json: %s", ex
            )

        try:
            return json.dumps(
                notification_activity,
                default=FinCrimeTriageAgent._json_default,
                indent=2,
            )
        except Exception as ex:
            logger.warning("Failed to serialize notification via json.dumps: %s", ex)
            return str(notification_activity)

    @staticmethod
    def _json_default(value: Any) -> Any:
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            return model_dump(mode="json", by_alias=True, exclude_none=True)
        if hasattr(value, "__dict__"):
            return value.__dict__
        return str(value)

    # ------------------------------------------------------------------
    # Foundry Responses API
    # ------------------------------------------------------------------

    async def _invoke_responses_api(
        self,
        *,
        input_text: str,
        conversation_id: str,
        instructions: str,
        auth: Authorization,
        auth_handler_name: Optional[str],
        context: TurnContext,
        include_teams_mcp: bool = True,
        turn: Optional[_Turn] = None,
        function_tools: bool = True,
        channel: str = "teams",
    ) -> str:
        """Call the Foundry Responses API with the MCP bundle and the scenario's function tools.

        Extends :meth:`ResponsesApiAgentLogicService.InvokeResponsesApiAsync`
        from the sample with a local function-tool loop.
        """

        turn = turn or self._build_turn(context, auth, auth_handler_name)
        mcp_tools = await self._build_mcp_tools(
            auth,
            auth_handler_name,
            context,
            include_teams_mcp=include_teams_mcp,
            trail=turn.trail,
        )
        schemas = turn.tool_schemas if function_tools else []
        logger.info(
            "Invoking Responses API with %d MCP tool server(s) and %d function tool(s)",
            len(mcp_tools),
            len(schemas),
        )

        previous_response_id = self._load_previous_response_id(conversation_id)
        if previous_response_id:
            logger.info(
                "Continuing conversation %s with previous_response_id=%s",
                conversation_id,
                previous_response_id,
            )

        request_args: dict[str, Any] = {
            "model": self._deployment,
            "instructions": instructions,
            "input": input_text,
            "tools": [*mcp_tools, *schemas],
        }
        if previous_response_id is not None:
            request_args["previous_response_id"] = previous_response_id

        execute_function = turn.execute

        try:
            response = await run_responses_with_tools(
                self._openai_client,
                request_args=request_args,
                execute_function=execute_function,
                max_rounds=self._max_tool_rounds,
            )
        except APIStatusError as ex:
            if is_content_filter_error(ex):
                logger.warning(
                    "Request blocked by Azure AI Content Safety (status %s); returning the policy message",
                    ex.status_code,
                )
                set_current_span_response(None, CONTENT_FILTER_MESSAGE)
                return CONTENT_FILTER_MESSAGE
            logger.error(
                "Responses API call failed with status %s: %s",
                ex.status_code,
                ex.response.text,
            )
            if previous_response_id and ex.status_code in (400, 404):
                # A stale previous_response_id (for example after a model change)
                # should not break the conversation: retry once without it.
                logger.info("Retrying without previous_response_id")
                request_args.pop("previous_response_id", None)
                response = await run_responses_with_tools(
                    self._openai_client,
                    request_args=request_args,
                    execute_function=execute_function,
                    max_rounds=self._max_tool_rounds,
                )
            else:
                return (
                    "I encountered an error processing your request. "
                    f"Status: {ex.status_code}"
                )

        response_json = response.model_dump(mode="json")
        self._log_mcp_tool_lists(response_json)
        self._save_response_id(conversation_id, response_json)
        if function_calls(response):
            output_text = (
                "I could not finish gathering the evidence for this request within my tool budget. "
                "Please ask again with a narrower question."
            )
        else:
            output_text = response.output_text or self._extract_output_text(response_json)
        if is_no_reply(output_text):
            logger.info("Model chose NO_REPLY (tools used: %s)", [c["tool"] for c in turn.calls])
            set_current_span_response(response_json.get("id"), NO_REPLY)
            return NO_REPLY
        output_text = self._append_citations(
            output_text,
            self._extract_url_citations(response_json),
        )
        output_text = self._with_footer(output_text, turn, channel)
        logger.info("Function tools used this turn: %s", [c["tool"] for c in turn.calls])
        response_id = response_json.get("id")
        if not isinstance(response_id, str) or not response_id:
            logger.warning(
                "Responses API response did not include an id; "
                "the trace will not be available for evaluation."
            )
            response_id = None
        set_current_span_response(response_id, output_text)
        return output_text

    def _log_mcp_tool_lists(self, response_json: dict[str, Any]) -> None:
        """Log the tool names each MCP server offered (once per server), to verify allowlists."""
        for item in response_json.get("output") or []:
            if not isinstance(item, dict) or item.get("type") != "mcp_list_tools":
                continue
            label = str(item.get("server_label") or "?")
            if label in self._logged_mcp_tool_lists:
                continue
            self._logged_mcp_tool_lists.add(label)
            names = [t.get("name") for t in item.get("tools") or [] if isinstance(t, dict)]
            if not names:
                logger.warning(
                    "MCP server %s offered no tools: its allowedTools in the scenario manifest match none of "
                    "the server's tool names (or MCP_ENFORCE_ALLOWLIST should be false)", label
                )
            logger.info("MCP tools offered by %s: %s", label, names)

    async def _build_mcp_tools(
        self,
        auth: Authorization,
        auth_handler_name: Optional[str],
        context: TurnContext,
        *,
        include_teams_mcp: bool = True,
        trail: Optional[token_debug.TokenTrail] = None,
    ) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        token_cache: dict[str, str | None] = {}
        for server in self._mcp_servers:
            name = server.get("mcpServerName", "") or server.get("name", "")
            url = server.get("url", "")
            if not url:
                continue
            if name == "mcp_TeamsServer" and not include_teams_mcp:
                logger.info(
                    "Teams MCP server omitted for a direct conversation reply"
                )
                continue

            token_scope = server.get("tokenScope") or MCP_SCOPE
            if token_scope not in token_cache:
                token_cache[token_scope] = await self._acquire_mcp_token(
                    auth,
                    auth_handler_name,
                    context,
                    scope=token_scope,
                    trail=trail,
                )
            bearer = token_cache[token_scope]
            if not bearer:
                logger.warning(
                    "No bearer token available for MCP server %s (scope=%s); "
                    "the server is likely to reject the request.",
                    name,
                    token_scope,
                )

            tool: dict[str, Any] = {
                "type": "mcp",
                "server_label": name,
                "server_url": url,
                "server_description": f"MCP server: {name}",
                "require_approval": "never",
            }
            allowed = server.get("allowedTools")
            if self._enforce_mcp_allowlist and isinstance(allowed, list) and allowed:
                # Only these tools are offered to the model (no delete/move/admin tools).
                tool["allowed_tools"] = [str(t) for t in allowed]
            if bearer:
                tool["headers"] = {"Authorization": f"Bearer {bearer}"}
            tools.append(tool)

        if self._toolbox_endpoint:
            toolbox_token = await self._credential.get_token(TOOLBOX_SCOPE)
            tools.append(
                {
                    "type": "mcp",
                    "server_label": "foundry_toolbox",
                    "server_url": self._toolbox_endpoint,
                    "server_description": (
                        "Foundry Toolbox with web search and code interpreter"
                    ),
                    "require_approval": "never",
                    "headers": {
                        "Authorization": f"Bearer {toolbox_token.token}",
                    },
                }
            )
        return tools

    async def _acquire_mcp_token(
        self,
        auth: Authorization,
        auth_handler_name: Optional[str],
        context: TurnContext,
        *,
        scope: str,
        trail: Optional[token_debug.TokenTrail] = None,
    ) -> Optional[str]:
        if not auth or not auth_handler_name:
            return None

        try:
            exchanged = await auth.exchange_token(
                context,
                scopes=[scope],
                auth_handler_id=auth_handler_name,
            )
            token = getattr(exchanged, "token", None) or getattr(
                exchanged, "access_token", None
            )
            if token and (token_debug.enabled() or self._footer_enabled):
                identity = TurnIdentity.from_context(context).debug_kwargs()
                summary = token_debug.log_token(token, label="mcp", **identity) or token_debug.summarize(
                    token, label="mcp", **identity
                )
                if trail is not None:
                    trail.add(summary)
            return token
        except Exception:
            logger.exception(
                "Failed to acquire MCP bearer token via auth handler (scope=%s)",
                scope,
            )
            return None

    # ------------------------------------------------------------------
    # previous_response_id persistence
    # ------------------------------------------------------------------

    def _response_id_path(self, conversation_id: str) -> Path:
        safe = (
            base64.urlsafe_b64encode(conversation_id.encode("utf-8"))
            .decode("ascii")
            .rstrip("=")
        )
        return self._response_store_dir / f"{safe}.responseid"

    def _load_previous_response_id(self, conversation_id: str) -> Optional[str]:
        try:
            path = self._response_id_path(conversation_id)
            if path.exists():
                value = path.read_text(encoding="utf-8").strip()
                return value or None
        except Exception as ex:
            logger.warning(
                "Failed to load previous_response_id for %s: %s", conversation_id, ex
            )
        return None

    def _save_response_id(self, conversation_id: str, response_json: dict[str, Any]) -> None:
        response_id = response_json.get("id") if isinstance(response_json, dict) else None
        if not response_id:
            return
        try:
            self._response_store_dir.mkdir(parents=True, exist_ok=True)
            self._response_id_path(conversation_id).write_text(
                str(response_id), encoding="utf-8"
            )
        except Exception as ex:
            logger.warning(
                "Failed to save response_id for %s: %s", conversation_id, ex
            )

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_output_text(response_json: dict[str, Any]) -> str:
        if not isinstance(response_json, dict):
            return ""

        output = response_json.get("output")
        if isinstance(output, list):
            parts: list[str] = []
            for item in output:
                if not isinstance(item, dict) or item.get("type") != "message":
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for entry in content:
                    if (
                        isinstance(entry, dict)
                        and entry.get("type") == "output_text"
                        and isinstance(entry.get("text"), str)
                    ):
                        parts.append(entry["text"])
            if parts:
                return "".join(parts)

        simple = response_json.get("output_text")
        if isinstance(simple, str):
            return simple

        logger.warning("Could not extract output text from Responses API response")
        return ""

    @staticmethod
    def _extract_url_citations(
        response_json: dict[str, Any],
    ) -> list[tuple[str, str]]:
        citations: list[tuple[str, str]] = []
        seen_urls: set[str] = set()

        def add_citation(annotation: dict[str, Any]) -> None:
            citation = annotation.get("url_citation", annotation)
            if not isinstance(citation, dict):
                return

            url = citation.get("url")
            if not isinstance(url, str):
                return
            url = url.strip()
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                return
            if url in seen_urls:
                return

            title = citation.get("title")
            if not isinstance(title, str) or not title.strip():
                title = parsed.netloc
            seen_urls.add(url)
            citations.append((title.strip(), url))

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                if value.get("type") == "url_citation":
                    add_citation(value)

                for key, nested in value.items():
                    if key in {"output", "result"} and isinstance(nested, str):
                        stripped = nested.strip()
                        if stripped.startswith(("{", "[")):
                            try:
                                visit(json.loads(stripped))
                            except json.JSONDecodeError:
                                pass
                    elif isinstance(nested, (dict, list)):
                        visit(nested)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        visit(response_json)
        return citations

    @staticmethod
    def _append_citations(
        output_text: str,
        citations: list[tuple[str, str]],
    ) -> str:
        markdown_link_pattern = re.compile(
            r"\[([^\]]+)\]\((https?://[^\s)]+)\)"
        )
        raw_url_pattern = re.compile(r"https?://[^\s<>\"]+")

        merged: list[tuple[str, str]] = []
        seen_urls: set[str] = set()

        def add(title: str, url: str) -> None:
            if url in seen_urls or len(merged) >= 20:
                return
            seen_urls.add(url)
            merged.append((title.strip() or urlparse(url).netloc, url))

        for title, url in citations:
            add(title, url)
        for match in markdown_link_pattern.finditer(output_text):
            add(match.group(1), match.group(2))
        for match in raw_url_pattern.finditer(output_text):
            url = match.group(0).rstrip(".,;:!?)]}")
            if url:
                add(urlparse(url).netloc, url)

        if not merged:
            return output_text

        formatted = output_text
        references: list[str] = []
        markers: list[str] = []
        for position, (title, url) in enumerate(merged, start=1):
            marker = f"[{position}]"
            formatted = re.sub(
                rf"\[([^\]]+)\]\({re.escape(url)}\)",
                rf"\1{marker}",
                formatted,
            )
            formatted = formatted.replace(url, marker)
            safe_title = title.replace('"', "'")[:80]
            references.append(f'{marker}: {url} "{safe_title}"')
            markers.append(marker)

        if not any(marker in formatted for marker in markers):
            formatted = f"{formatted.rstrip()}\n\nSources: {' '.join(markers)}"

        return f"{formatted.rstrip()}\n\n" + "\n".join(references)


def _now_epoch() -> int:
    import time

    return int(time.time())
