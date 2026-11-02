import json
from pathlib import Path

import pytest

from fincrime_autopilot import scenario
from fincrime_autopilot.rfp_prompts import DAILY_CHECK_TAG, build_rfp_instructions, is_daily_check

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "fincrime_autopilot"
LIBRARY = Path(__file__).resolve().parents[1] / "demo" / "rfp" / "library"


@pytest.mark.parametrize(
    ("texts", "expected"),
    [
        (("/whoami",), ""),
        (("<at>BankingBids</at> /whoami",), ""),
        (("@BankingBids /whoami probe",), "probe"),
        (("<p>/WhoAmI probe</p>",), "probe"),
        (("  /whoami\nmore text",), ""),
        (("Hello", "/whoami"), ""),
        (("what is /whoami?",), None),
        (("/whoamiX",), None),
        (("see https://x/whoami",), None),
        (("who am I?",), None),
        (("Thanks, can you now triage ALR-2026-1043?",), None),
        (("<p>Please triage ALR-1</p><hr><p>/whoami - BankingBids (claims only)</p>",), None),
        (('{"text": "/whoami probe please"}',), None),
        ((None, ""), None),
    ],
)
def test_parse_whoami(texts, expected):
    assert scenario.parse_whoami(*texts) == expected


@pytest.mark.parametrize(
    ("subject", "expected"),
    [("/whoami", ""), ("/whoami probe", "probe"), ("RE: /whoami", None), ("Fw: /whoami", None),
     ("AW: /whoami probe", None), ("Question about /whoami", None), ("", None), (None, None)],
)
def test_parse_whoami_subject_ignores_replies_and_forwards(subject, expected):
    assert scenario.parse_whoami_subject(subject) == expected


def test_scenario_switch(monkeypatch):
    monkeypatch.delenv("AUTOPILOT_SCENARIO", raising=False)
    assert scenario.current_scenario() == scenario.SCENARIO_FINCRIME
    monkeypatch.setenv("AUTOPILOT_SCENARIO", "RFP")
    assert scenario.current_scenario() == scenario.SCENARIO_RFP
    assert "RFP Bid Desk" in scenario.help_text() and "bid" in scenario.install_text()
    assert "FinCrime" in scenario.help_text(scenario.SCENARIO_FINCRIME)


def test_rfp_instructions_cover_controls():
    text = build_rfp_instructions("BankingBids", "Ana", "Banking & Financial Services bids (index bids-banking)", channel="email")
    assert "BankingBids" in text and "bids-banking" in text
    assert "access_denied" in text and "Never answer from memory" in text
    assert "cannot open email attachments" in text
    assert "Human decision" in text
    daily = build_rfp_instructions("BankingBids", "scheduler", "x", channel="email", daily_check=True, team_chat_name="Woodgrove bid team")
    assert "Woodgrove bid team" in daily and "Do not reply" in daily
    assert is_daily_check(f"{DAILY_CHECK_TAG} Monday")
    assert is_daily_check("[Bid-Desk:Daily-Check]".lower())
    assert not is_daily_check("RFP from Woodgrove")


def test_rfp_manifest_offers_no_destructive_tools():
    manifest = json.loads((PACKAGE / "ToolingManifest.rfp.json").read_text(encoding="utf-8"))
    names = {s["mcpServerName"] for s in manifest["mcpServers"]}
    assert names == {"mcp_WordServer", "mcp_MailTools", "mcp_ODSPRemoteServer", "mcp_TeamsServer"}
    for server in manifest["mcpServers"]:
        for tool in server.get("allowedTools", []):
            assert not any(word in tool.lower() for word in ("delete", "move", "rename", "createchannel", "addchatmember"))
    odsp = next(s for s in manifest["mcpServers"] if s["mcpServerName"] == "mcp_ODSPRemoteServer")
    assert "shareFileOrFolder" in odsp["allowedTools"] and "deleteFileOrFolder" not in odsp["allowedTools"]


def test_libraries_are_synthetic_and_well_formed():
    schema = json.loads((LIBRARY / "index-schema.json").read_text(encoding="utf-8"))
    fields = {f["name"] for f in schema["fields"]}
    for name in ("banking", "publicsector"):
        docs = json.loads((LIBRARY / f"{name}.json").read_text(encoding="utf-8"))
        assert len(docs) >= 15
        ids = [d["id"] for d in docs]
        assert len(ids) == len(set(ids))
        for doc in docs:
            assert set(doc) <= fields and doc["answer"] and doc["owner"]
        assert any("data residency" in d["tags"] for d in docs), "shared topic for the isolation beat"
    assert not (PACKAGE / "data" / "rfp").exists(), "the answer libraries must not ship in the container image"
