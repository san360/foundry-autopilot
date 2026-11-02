"""Scenario switch: one container image, two autopilots (AUTOPILOT_SCENARIO=fincrime | rfp)."""

from __future__ import annotations

import html
import os
import re
from typing import Optional

SCENARIO_FINCRIME = "fincrime"
SCENARIO_RFP = "rfp"

_MENTION_TAG = re.compile(r"<at\b[^>]*>.*?</at>", re.IGNORECASE | re.DOTALL)
_HTML_TAG = re.compile(r"<[^>]+>")
_LEADING_MENTIONS = re.compile(r"^(?:@\S+\s*)+")
_WHOAMI = re.compile(r"^/whoami\b(?P<args>[^\n]*)", re.IGNORECASE)
_REPLY_PREFIX = re.compile(r"^\s*(?:re|fw|fwd|aw|wg|sv|vs)\s*:", re.IGNORECASE)


def current_scenario() -> str:
    value = os.getenv("AUTOPILOT_SCENARIO", SCENARIO_FINCRIME).strip().lower()
    return SCENARIO_RFP if value in ("rfp", "biddesk", "bid-desk", "rfp-bid-desk") else SCENARIO_FINCRIME


def _command_text(text: Optional[str]) -> str:
    """The start of the newest message: mentions, HTML and leading @names removed."""
    value = _MENTION_TAG.sub(" ", text or "")
    value = html.unescape(_HTML_TAG.sub(" ", value)).strip()
    return _LEADING_MENTIONS.sub("", value).strip()


def parse_whoami(*texts: Optional[str]) -> Optional[str]:
    """Return "probe" or "" when a text starts with the /whoami command, else None.

    Only the start of the message counts (after mentions), so quoted email history or a
    sentence that mentions /whoami never triggers it.
    """
    for text in texts:
        match = _WHOAMI.match(_command_text(text))
        if match:
            return "probe" if re.match(r"\s*probe\b", match.group("args"), re.IGNORECASE) else ""
    return None


def parse_whoami_subject(subject: Optional[str]) -> Optional[str]:
    """/whoami in an email subject; replies and forwards (RE:, FW:) never count."""
    if not subject or _REPLY_PREFIX.match(subject):
        return None
    return parse_whoami(subject)


HELP_TEXT = {
    SCENARIO_FINCRIME: (
        "👋 **Hi!** I'm your **FinCrime Alert Triage autopilot** (Contoso Bank, synthetic demo data).\n\n"
        "I triage AML, sanctions and KYC alerts and draft evidence-based recommendations for "
        "human review. I never close alerts or file SARs.\n\n"
        "Try: *What's in my alert queue?* · *Triage ALR-2026-1043* · "
        "*Create a case note for ALR-2026-1045*"
    ),
    SCENARIO_RFP: (
        "👋 **Hi!** I'm your **RFP Bid Desk autopilot** (Fabrikam Cloud Services, synthetic demo data).\n\n"
        "I turn RFPs into a compliance matrix and a first draft, reusing our team's approved past answers "
        "with citations, and I track what is still open. Humans own submission, pricing and commitments.\n\n"
        "Try: *What did we commit on data residency last year?* · *What's still open?* · "
        "email me an RFP · *@me make 4.2 stronger* in a Word comment · */whoami*"
    ),
}

INSTALL_TEXT = {
    SCENARIO_FINCRIME: (
        "Thank you for hiring me! I'm ready to work as your team's AML alert triage analyst. "
        "To onboard me: add me to your FinCrime Ops group chat, tell me who the L1/L2 "
        "reviewers are, and send alert notifications to my mailbox. Type /help to see what I can do."
    ),
    SCENARIO_RFP: (
        "Thank you for hiring me! I'm ready to work on your bid desk. To onboard me: add me to your "
        "bid team's group chat, email me RFPs (text in the body or a link to the Word document), and "
        "@mention me in Word comments on bid drafts. Type /help to see what I can do."
    ),
}


def help_text(scenario: Optional[str] = None) -> str:
    return HELP_TEXT[scenario or current_scenario()]


def install_text(scenario: Optional[str] = None) -> str:
    return INSTALL_TEXT[scenario or current_scenario()]
