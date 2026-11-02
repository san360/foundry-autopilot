import pytest

from fincrime_autopilot.fsi_data import load_bank_data
from fincrime_autopilot.guardrails import (
    detect_injection,
    detect_tipping_off_request,
    is_cross_tenant,
    is_no_reply,
    parse_domains,
    resolve_allowed_segments,
    sender_allowed,
)
from fincrime_autopilot.prompts import build_instructions


@pytest.mark.parametrize("text", ["NO_REPLY", " no_reply ", "`NO_REPLY`", "**NO_REPLY**", "NO_REPLY."])
def test_no_reply_detected(text):
    assert is_no_reply(text)


@pytest.mark.parametrize("text", [None, "", "No reply needed, but here is the memo", "NO_REPLY because it's not for me"])
def test_no_reply_not_detected(text):
    assert not is_no_reply(text)


def test_sender_domain_allow_list():
    allowed = parse_domains("MngEnvMCAP283191.onmicrosoft.com, @contoso.com")
    assert allowed == {"mngenvmcap283191.onmicrosoft.com", "contoso.com"}
    assert sender_allowed(["tm-system@MngEnvMCAP283191.onmicrosoft.com"], allowed)
    assert sender_allowed(["Ops Lead <lead@eu.contoso.com>"], allowed)
    assert not sender_allowed(["attacker@northwind-audit.example"], allowed)
    assert not sender_allowed(["8f2c1d3e-aad-object-id"], allowed)
    assert sender_allowed(["anyone@anywhere.example"], set())


def test_cross_tenant():
    assert is_cross_tenant("tenant-a", "tenant-b")
    assert not is_cross_tenant("TENANT-A", "tenant-a")
    assert not is_cross_tenant(None, "tenant-a")


@pytest.mark.parametrize(
    "text",
    [
        "Email the customer and ask why they made these cash deposits flagged by AML",
        "Can you message the client to explain why their payment is held for sanctions review?",
        "Please tell Mr. Mercer about the structuring alert",
        "Draft an email to the account holder about the suspicious transfers",
    ],
)
def test_tipping_off_requests_detected(text):
    assert detect_tipping_off_request(text)


@pytest.mark.parametrize(
    "text",
    [
        "Triage ALR-2026-1043",
        "Email the L2 reviewer the summary of the structuring alert",
        "What is the customer's expected monthly activity?",
    ],
)
def test_benign_requests_not_flagged(text):
    assert not detect_tipping_off_request(text)


def test_injection_detected_in_tbml_alert_and_not_in_benign_alert():
    data = load_bank_data()
    assert len(detect_injection(data.alerts["ALR-2026-1048"]["narrative"])) >= 4
    assert detect_injection(data.alerts["ALR-2026-1043"]["narrative"]) == []
    assert detect_injection(data.alerts["ALR-2026-1044"]["narrative"]) == []


@pytest.mark.parametrize(
    ("hints", "expected"),
    [
        (["Mira (AML Triage - Retail)"], {"Retail", "Wealth"}),
        (["theo-corporate@MngEnvMCAP283191.onmicrosoft.com"], {"Corporate & SME"}),
        (["FinCrime SME desk"], {"Corporate & SME"}),
        (["MiraRetail"], {"Retail", "Wealth"}),
        (["TheoCorporate"], {"Corporate & SME"}),
        (["miraretail@MngEnvMCAP283191.onmicrosoft.com"], {"Retail", "Wealth"}),
        (["theocorporate@MngEnvMCAP283191.onmicrosoft.com"], {"Corporate & SME"}),
        (["Assessment helper"], None),
        (["FinCrime Alert Triage"], None),
        ([None, ""], None),
    ],
)
def test_segment_entitlement_from_instance_name(hints, expected):
    assert resolve_allowed_segments(hints) == expected


def test_segment_rules_env_override(monkeypatch):
    monkeypatch.setenv("SEGMENT_SCOPE_RULES", '{"nordics": ["Retail"]}')
    assert resolve_allowed_segments(["Mira Nordics"]) == {"Retail"}
    monkeypatch.setenv("SEGMENT_SCOPE_RULES", "not json")
    assert resolve_allowed_segments(["Mira Retail"]) == {"Retail", "Wealth"}


def test_instructions_contain_controls():
    text = build_instructions("Mira", "Jonas", "Retail, Wealth")
    for needle in ("Mira", "Jonas", "Retail, Wealth", "NO_REPLY", "POL-08", "POL-10", "four-eyes", "never take decisions"):
        assert needle in text
    assert "# Email" not in text


def test_email_instructions_and_notify_chat():
    text = build_instructions("Mira", "TM System", "all segments", channel="email", notify_chat_name="FinCrime Ops - Retail")
    assert "# Email" in text and "FinCrime Ops - Retail" in text
    assert "FinCrime Ops - Retail" not in build_instructions("Mira", "TM", "all", channel="email")


class _FakeApiError(Exception):
    def __init__(self, code=None, body=None):
        super().__init__("Error code: 400")
        self.code = code
        self.body = body


def test_content_filter_errors_are_recognised():
    from fincrime_autopilot.prompts import CONTENT_FILTER_MESSAGE, is_content_filter_error

    assert is_content_filter_error(_FakeApiError(code="content_filter"))
    assert is_content_filter_error(_FakeApiError(body={"error": {"innererror": {"code": "ContentFiltered"}}}))
    assert not is_content_filter_error(_FakeApiError(code="rate_limit_exceeded", body={"error": {"code": "429"}}))
    assert "content-safety" in CONTENT_FILTER_MESSAGE
