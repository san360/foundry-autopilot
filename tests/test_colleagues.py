"""Agent-to-agent collaboration between bid desk instances: sender recognition, loop budget, prompts."""

import json

from fincrime_autopilot.colleagues import (
    Colleague,
    ColleagueTurnBudget,
    colleague_sender,
    directory,
    load_colleagues,
    mentioned_colleagues,
)
from fincrime_autopilot.rfp_prompts import build_rfp_instructions, colleague_turn_notice

BANKING = "f5a54362-cee3-4656-9812-1c8fa83e9b63"
PUBLIC = "77f50c53-8e33-4e19-88f2-c242a3a97db1"
RAW = json.dumps({BANKING: "BankingBids", PUBLIC.upper(): "PublicSectorBids"})


def test_load_colleagues_keeps_only_object_ids():
    assert load_colleagues(RAW) == {BANKING: "BankingBids", PUBLIC: "PublicSectorBids"}
    assert load_colleagues(json.dumps({"banking": "BankingBids", BANKING: ""})) == {}
    assert load_colleagues("not json") == {}
    assert load_colleagues("[]") == {}
    assert load_colleagues("") == {}


def test_load_colleagues_reads_the_environment(monkeypatch):
    monkeypatch.setenv("BID_COLLEAGUES", RAW)
    assert load_colleagues()[PUBLIC] == "PublicSectorBids"
    monkeypatch.delenv("BID_COLLEAGUES")
    assert load_colleagues() == {}


def test_colleague_sender_matches_object_id_not_display_name():
    colleagues = load_colleagues(RAW)
    assert colleague_sender([BANKING, f"8:orgid:{BANKING}"], colleagues, self_ids=[PUBLIC]) == Colleague(BANKING, "BankingBids")
    assert colleague_sender([None, f"8:orgid:{BANKING.upper()}"], colleagues) == Colleague(BANKING, "BankingBids")
    # A human who renames themselves "BankingBids" is still a human.
    assert colleague_sender(["70e581e1-2351-48db-95be-b968643062f1", "BankingBids"], colleagues) is None
    # An instance never treats its own messages as a colleague's.
    assert colleague_sender([BANKING], colleagues, self_ids=[BANKING]) is None
    assert colleague_sender([BANKING], {}) is None


def test_directory_excludes_self_and_mentions_are_found_by_name():
    colleagues = load_colleagues(RAW)
    others = directory(colleagues, self_ids=[BANKING])
    assert others == [Colleague(PUBLIC, "PublicSectorBids")]
    assert mentioned_colleagues("<at>BankingBids</at> ask Public Sector Bids about Q11", others) == others
    assert mentioned_colleagues("use PublicSectorBids' answer for Q11", others) == others
    assert mentioned_colleagues("what's still open on WB-2026-117?", others) == []


def test_budget_caps_colleague_turns_per_conversation_and_window():
    budget = ColleagueTurnBudget(max_turns=2, window_seconds=600)
    assert budget.allow("chat-1", now=0) and budget.allow("chat-1", now=10)
    assert not budget.allow("chat-1", now=20)
    assert budget.allow("chat-2", now=20), "budgets are per conversation"
    assert budget.allow("chat-1", now=600), "turns leave the window"


def test_budget_reads_environment(monkeypatch):
    monkeypatch.setenv("COLLEAGUE_MAX_TURNS", "1")
    monkeypatch.setenv("COLLEAGUE_WINDOW_SECONDS", "bad")
    budget = ColleagueTurnBudget()
    assert budget.max_turns == 1 and budget.window_seconds == 600
    assert budget.allow("c", now=0) and not budget.allow("c", now=1)


def test_instructions_list_colleagues_only_in_teams():
    colleagues = [("PublicSectorBids", "Public Sector bids", PUBLIC)]
    teams = build_rfp_instructions("BankingBids", "Ana", "Banking", colleagues=colleagues, chat_id="19:abc@thread.v2")
    assert "ask, don't access" in teams and PUBLIC in teams and "19:abc@thread.v2" in teams
    assert "approved for reuse by" in teams and "Never present it as your own team's approved answer" in teams
    line = next(line for line in teams.splitlines() if line.startswith("  For PublicSectorBids: "))
    args = json.loads(line.split(": ", 1)[1])
    assert args["chat-id"] == "19:abc@thread.v2"
    assert args["body"]["content"].startswith('<p><at id="0">PublicSectorBids</at> <b>Question from BankingBids (autopilot)')
    assert args["mentions"][0]["mentioned"]["user"] == {"id": PUBLIC, "displayName": "PublicSectorBids", "userIdentityType": "aadUser"}
    assert "ask, don't access" not in build_rfp_instructions("BankingBids", "Ana", "Banking")
    assert "ask, don't access" not in build_rfp_instructions("BankingBids", "Ana", "Banking", channel="email", colleagues=colleagues)


def test_colleague_turn_notice_names_the_sender_and_forbids_follow_ups():
    notice = colleague_turn_notice("BankingBids")
    assert notice.startswith("[Control notice from the bid desk code")
    assert "BankingBids, another bid team's autopilot" in notice
    assert "Cross-team reuse: needs bid manager approval." in notice
    assert "Don't @mention anyone" in notice and "NO_REPLY" in notice
    assert notice.endswith("Message from BankingBids: ")
