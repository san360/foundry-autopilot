"""Deterministic guardrails that run in code, independent of the model.

The model is instructed to follow the same rules, but these checks make the
important ones hold even if the model is talked round (defence in depth).
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Iterable, Optional

NO_REPLY = "NO_REPLY"

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+'-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")

_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ignore_instructions", re.compile(r"\b(ignore|disregard|forget)\b.{0,30}\b(previous|prior|above|all|earlier)\b.{0,20}\b(instructions?|rules?|prompts?)\b", re.I | re.S)),
    ("addressed_to_ai", re.compile(r"\b(system (notice|message|prompt)|note) to (the )?(ai|assistant|agent|model)\b", re.I)),
    ("role_override", re.compile(r"\byou are now\b|\bact as\b.{0,30}\b(admin|system|developer)\b", re.I)),
    ("pre_approval_claim", re.compile(r"\b(already|pre)[- ]?approved by (compliance|the mlro|l2|management)\b", re.I)),
    ("force_disposition", re.compile(r"\b(mark|close|clear|classify)\b.{0,30}\b(alert|case|this)\b.{0,30}\b(false positive|closed|cleared|no risk)\b", re.I | re.S)),
    ("exfiltration_request", re.compile(r"\b(email|send|forward|upload)\b.{0,60}\b(file|data|records?|account numbers?|customer)\b.{0,60}@", re.I | re.S)),
)

_CONTACT_VERB = r"(email|e-mail|mail|message|contact|call|phone|text|notify|inform|tell|ask|write to|reach out to)"
_CUSTOMER_NOUN = r"(customer|client|account holder|beneficiary|the person|mr\.?|ms\.?|mrs\.?)"
_MONITORING_NOUN = r"(alert|investigation|sar|str|suspicious|aml|money laundering|structuring|sanction|monitoring|flagged|why (the|their|his|her) payment)"


def is_no_reply(text: Optional[str]) -> bool:
    """True when the model chose to stay silent (exact token, tolerant of whitespace/markdown)."""
    if not text:
        return False
    cleaned = text.strip().strip("`*_ .").upper()
    return cleaned == NO_REPLY


def extract_email_domain(value: Any) -> str:
    match = _EMAIL_RE.search(str(value or ""))
    return match.group(1).lower() if match else ""


def parse_domains(raw: Optional[str]) -> set[str]:
    return {d.strip().lower().lstrip("@") for d in (raw or "").split(",") if d.strip()}


def sender_allowed(sender_values: Iterable[Any], allowed_domains: set[str]) -> bool:
    """Allow when no domain allow-list is configured, or any sender value has an allowed domain."""
    if not allowed_domains:
        return True
    for value in sender_values:
        domain = extract_email_domain(value)
        if domain and (domain in allowed_domains or any(domain.endswith("." + d) for d in allowed_domains)):
            return True
    return False


def is_cross_tenant(activity_tenant_id: Optional[str], expected_tenant_id: Optional[str]) -> bool:
    if not activity_tenant_id or not expected_tenant_id:
        return False
    return activity_tenant_id.strip().lower() != expected_tenant_id.strip().lower()


def detect_tipping_off_request(text: Optional[str]) -> bool:
    """Heuristic: a request to contact a customer that also references monitoring activity."""
    if not text:
        return False
    lowered = text.lower()
    contact_customer = re.search(rf"\b{_CONTACT_VERB}\b.{{0,60}}\b{_CUSTOMER_NOUN}", lowered, re.S)
    customer_contact = re.search(rf"\b{_CUSTOMER_NOUN}\b.{{0,40}}\b(know|aware|explain|told)\b", lowered, re.S)
    mentions_monitoring = re.search(rf"\b{_MONITORING_NOUN}", lowered)
    return bool((contact_customer or customer_contact) and mentions_monitoring)


def detect_injection(text: Optional[str]) -> list[str]:
    """Return the names of manipulation patterns found in untrusted free text."""
    if not text:
        return []
    return [name for name, pattern in _INJECTION_PATTERNS if pattern.search(text)]


DEFAULT_SEGMENT_RULES: dict[str, list[str]] = {
    "retail": ["Retail", "Wealth"],
    "wealth": ["Retail", "Wealth"],
    "corporate": ["Corporate & SME"],
    "corp": ["Corporate & SME"],
    "sme": ["Corporate & SME"],
    "cib": ["Corporate & SME"],
}

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def load_segment_rules() -> dict[str, list[str]]:
    raw = os.getenv("SEGMENT_SCOPE_RULES", "").strip()
    if not raw:
        return DEFAULT_SEGMENT_RULES
    try:
        parsed = json.loads(raw)
        return {str(k).lower(): [str(s) for s in v] for k, v in parsed.items()}
    except (ValueError, AttributeError, TypeError):
        return DEFAULT_SEGMENT_RULES


def resolve_allowed_segments(
    instance_hints: Iterable[Optional[str]],
    rules: Optional[dict[str, list[str]]] = None,
) -> Optional[set[str]]:
    """Map the hired instance's name/UPN to the segments it may see.

    Demo-grade entitlement: an instance whose display name or alias contains
    "retail" sees Retail and Wealth alerts, "corporate"/"sme" sees Corporate &
    SME. Unmatched instances (for example the developer test instance) see all
    segments. In production the core-banking API enforces this against the
    instance's own Entra identity instead.
    """
    rules = rules or load_segment_rules()
    # Agent 365 advises against spaces and special characters in instance names, so
    # split CamelCase names ("MiraRetail" -> "Mira Retail") before matching.
    haystack = " ".join(_CAMEL_BOUNDARY.sub(" ", str(h or "")) for h in instance_hints).lower()
    allowed: set[str] = set()
    for keyword, segments in rules.items():
        # Long keywords may sit inside lower-case aliases ("miraretail@..."); short ones
        # ("sme", "cib") must start a word to avoid false positives such as "assessment".
        escaped = re.escape(keyword)
        pattern = escaped if len(keyword) >= 6 else rf"(?<![a-z]){escaped}"
        if re.search(pattern, haystack):
            allowed.update(segments)
    return allowed or None
