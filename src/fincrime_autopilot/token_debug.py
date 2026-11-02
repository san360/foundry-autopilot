"""Token inspector: shows which Entra identity each outgoing call uses.

Enabled with ``TOKEN_DEBUG=true``. Only the JWT payload is base64url-decoded, for
learning and troubleshooting. The signature is never checked (the resource server
does that) and the raw token or signature is never logged or returned.

Claims follow https://learn.microsoft.com/entra/agent-id/agent-token-claims:
``idtyp=user`` with ``xms_sub_fct`` 13 is the agent's own user account,
``idtyp=app`` with ``xms_sub_fct`` 11 is the agent identity acting autonomously.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

KIND_AGENT_USER = "agent-user"
KIND_AGENT_IDENTITY = "agent-identity"
KIND_CONTAINER = "container-default-identity"
KIND_HUMAN_DELEGATED = "human-user-delegated"
KIND_APP = "app"
KIND_UNKNOWN = "unknown"

_SUMMARY_CLAIMS = (
    "oid", "azp", "appid", "xms_par_app_azp", "idtyp", "xms_sub_fct", "xms_act_fct",
    "scp", "roles", "aud", "tid", "exp",
)


def enabled() -> bool:
    return os.getenv("TOKEN_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")


def decode_claims(token: Optional[str]) -> Optional[dict[str, Any]]:
    """Return the JWT payload as a dict, or None when the value is not a JWT."""
    if not token or not isinstance(token, str):
        return None
    parts = token.split(".")
    if len(parts) != 3 or not parts[1]:
        return None
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    except (ValueError, UnicodeError):
        return None
    return claims if isinstance(claims, dict) else None


def _facets(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, (list, tuple)):
        return {str(v) for v in value}
    return set(str(value).split())


def _actor(claims: dict[str, Any]) -> str:
    return str(claims.get("azp") or claims.get("appid") or "")


def classify(claims: dict[str, Any], *, default_instance_client_id: Optional[str] = None) -> str:
    idtyp = str(claims.get("idtyp") or "").lower()
    subject_facets = _facets(claims.get("xms_sub_fct"))
    actor_facets = _facets(claims.get("xms_act_fct"))
    actor = _actor(claims).lower()
    if default_instance_client_id and actor == default_instance_client_id.lower():
        return KIND_CONTAINER
    if idtyp == "user" and "13" in subject_facets:
        return KIND_AGENT_USER
    if idtyp == "app" and "11" in subject_facets:
        return KIND_AGENT_IDENTITY
    if idtyp == "user":
        return KIND_HUMAN_DELEGATED if "11" in actor_facets else "user"
    if idtyp == "app":
        return KIND_APP
    return KIND_UNKNOWN


def _match_instance(
    claims: dict[str, Any],
    instance_name: Optional[str],
    agentic_user_id: Optional[str],
    agentic_app_id: Optional[str],
) -> Optional[str]:
    if not instance_name:
        return None
    oid = str(claims.get("oid") or "").lower()
    actor = _actor(claims).lower()
    if agentic_user_id and oid == agentic_user_id.lower():
        return instance_name
    if agentic_app_id and actor == agentic_app_id.lower():
        return instance_name
    return None


def summarize(
    token: Optional[str],
    *,
    label: str,
    instance_name: Optional[str] = None,
    agentic_user_id: Optional[str] = None,
    agentic_app_id: Optional[str] = None,
    default_instance_client_id: Optional[str] = None,
    now: Optional[float] = None,
) -> dict[str, Any]:
    """Summarise a token's identity claims. Never includes the token itself."""
    claims = decode_claims(token)
    if claims is None:
        return {"label": label, "kind": "not-a-jwt" if token else "no-token"}
    default_instance_client_id = default_instance_client_id or os.getenv("FOUNDRY_AGENT_DEFAULT_INSTANCE_CLIENT_ID")
    summary: dict[str, Any] = {
        "label": label,
        "kind": classify(claims, default_instance_client_id=default_instance_client_id),
    }
    matched = _match_instance(claims, instance_name, agentic_user_id, agentic_app_id)
    if matched:
        summary["instance"] = matched
    for name in _SUMMARY_CLAIMS:
        if name in claims and claims[name] not in (None, "", []):
            summary[name] = claims[name]
    exp = claims.get("exp")
    if isinstance(exp, (int, float)):
        summary["expires_in_min"] = int((exp - (now if now is not None else time.time())) // 60)
    return summary


def format_summary(summary: dict[str, Any]) -> str:
    parts = [f"token[{summary.get('label', '?')}]", f"kind={summary.get('kind')}"]
    if summary.get("instance"):
        parts.append(f"instance={summary['instance']}")
    for name in _SUMMARY_CLAIMS:
        if name == "exp":
            continue
        if name in summary:
            value = summary[name]
            if isinstance(value, (list, tuple)):
                value = ",".join(str(v) for v in value)
            parts.append(f"{name}={value}")
    if "expires_in_min" in summary:
        parts.append(f"exp_in={summary['expires_in_min']}m")
    return " ".join(parts)


def footer_enabled() -> bool:
    return os.getenv("TOKEN_FOOTER", "").strip().lower() in ("1", "true", "yes", "on")


def dimensions(summary: dict[str, Any]) -> dict[str, str]:
    """Flat, queryable attributes (Application Insights customDimensions). No token material."""
    names = {
        "label": "token_label", "kind": "token_kind", "instance": "token_instance", "oid": "token_oid",
        "azp": "token_azp", "appid": "token_appid", "xms_par_app_azp": "token_parent_app", "idtyp": "token_idtyp",
        "xms_sub_fct": "token_sub_fct", "xms_act_fct": "token_act_fct", "aud": "token_aud", "tid": "token_tid",
        "scp": "token_scp", "roles": "token_roles", "expires_in_min": "token_expires_in_min",
    }
    out: dict[str, str] = {}
    for key, dim in names.items():
        if key in summary:
            value = summary[key]
            out[dim] = ",".join(str(v) for v in value) if isinstance(value, (list, tuple)) else str(value)
    return out


def _record_span(summary: dict[str, Any]) -> None:
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        if not span or not span.is_recording():
            return
        prefix = "agent.token." + str(summary.get("label", "token")).replace(" ", "_")
        for dim, value in dimensions(summary).items():
            span.set_attribute(f"{prefix}.{dim.removeprefix('token_')}", value)
    except Exception:  # noqa: BLE001 - telemetry must never break a turn
        pass


def log_token(token: Optional[str], *, label: str, **identity: Any) -> Optional[dict[str, Any]]:
    """Log a one-line claim summary (with structured dimensions) when TOKEN_DEBUG is on."""
    if not enabled():
        return None
    summary = summarize(token, label=label, **identity)
    logger.info("🔑 %s", format_summary(summary), extra=dimensions(summary))
    _record_span(summary)
    return summary


def short_id(value: Any) -> str:
    text = str(value or "")
    return text[:8] if text else "?"


def footer(summary: Optional[dict[str, Any]], instance_name: str = "") -> str:
    """One-line attribution for a reply: which identity acted and for which audience."""
    if not summary or summary.get("kind") in (None, "no-token", "not-a-jwt"):
        return ""
    who = summary.get("instance") or instance_name or "this instance"
    kind = summary.get("kind")
    if kind == KIND_AGENT_USER:
        subject = f"agent user {short_id(summary.get('oid'))}"
    elif kind == KIND_AGENT_IDENTITY:
        subject = f"agent identity {short_id(summary.get('azp') or summary.get('appid'))}"
    elif kind == KIND_CONTAINER:
        subject = f"shared container identity {short_id(summary.get('azp') or summary.get('appid'))}"
    else:
        subject = f"{kind} {short_id(summary.get('oid'))}"
    return f"Acted as: {who} · {subject} · token for {summary.get('aud', '?')}"


class TokenTrail:
    """Token summaries collected during one turn (for /whoami and the optional footer)."""

    def __init__(self) -> None:
        self.summaries: list[dict[str, Any]] = []

    def add(self, summary: Optional[dict[str, Any]]) -> None:
        if summary and summary.get("kind") not in (None, "no-token", "not-a-jwt"):
            self.summaries.append(summary)

    def last(self) -> Optional[dict[str, Any]]:
        return self.summaries[-1] if self.summaries else None

    def preferred(self) -> Optional[dict[str, Any]]:
        """The most telling identity: a per-instance data-plane token, else the last one used."""
        for summary in reversed(self.summaries):
            if summary.get("kind") in (KIND_AGENT_IDENTITY, KIND_AGENT_USER) and "search" in str(summary.get("aud", "")):
                return summary
        return self.last()


class LoggingTokenCredential:
    """Async credential wrapper that logs each newly issued token's claims."""

    def __init__(self, inner: Any, label: str = "container") -> None:
        self._inner = inner
        self._label = label
        self._seen: set[tuple[str, int]] = set()

    async def get_token(self, *scopes: str, **kwargs: Any) -> Any:
        access_token = await self._inner.get_token(*scopes, **kwargs)
        if enabled():
            token = getattr(access_token, "token", None)
            claims = decode_claims(token) or {}
            key = (str(claims.get("aud", "")), int(claims.get("exp", 0) or 0))
            if key not in self._seen:
                self._seen.add(key)
                log_token(token, label=f"{self._label}:{','.join(scopes)}")
        return access_token

    async def close(self) -> None:
        close = getattr(self._inner, "close", None)
        if close is not None:
            await close()

    async def __aenter__(self) -> "LoggingTokenCredential":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
