"""Deterministic, explainable risk indicators per alert rule (synthetic rules)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from .fsi_data import BankData, name_similarity
from .fsi_screening import screen_party
from .guardrails import detect_injection

_OUTBOUND_TYPES = {"wire_out", "instant_out"}
_EXCLUDED_CREDIT_TYPES = {"internal_transfer"}


def _d(value: str) -> date:
    return date.fromisoformat(value)


def _indicator(ind_id: str, description: str, value: Any, threshold: Any, triggered: bool, weight: int) -> dict[str, Any]:
    return {
        "id": ind_id,
        "description": description,
        "value": value,
        "threshold": threshold,
        "triggered": bool(triggered),
        "weight": weight if triggered else 0,
    }


def profile_deviation(data: BankData, customer: dict[str, Any], days: int = 30) -> float:
    start = data.as_of - timedelta(days=days)
    credits = sum(
        t["amount"]
        for t in data.customer_transactions(customer["customer_id"])
        if t["direction"] == "credit" and t["type"] not in _EXCLUDED_CREDIT_TYPES and _d(t["date"]) > start
    )
    expected = float(customer.get("expected_activity", {}).get("monthly_credits_eur") or 0)
    return round(credits / expected, 2) if expected else 0.0


def _structuring(data: BankData, alert: dict, customer: dict, th: dict) -> list[dict]:
    txns = data.customer_transactions(customer["customer_id"])
    band = [
        t for t in txns
        if t["type"] == "cash_deposit" and th["structuring_band_low"] <= t["amount"] < th["cash_reporting_threshold"]
    ]
    window = int(th["structuring_window_days"])
    best: list[dict] = []
    for start_txn in band:
        start = _d(start_txn["date"])
        in_window = [t for t in band if start <= _d(t["date"]) < start + timedelta(days=window)]
        if len(in_window) > len(best):
            best = in_window
    cash_total = round(sum(t["amount"] for t in best), 2)
    branches = sorted({t["channel"] for t in best})
    onward: list[dict] = []
    if best:
        first, last = _d(best[0]["date"]), _d(best[-1]["date"])
        onward = [
            t for t in txns
            if t["type"] in _OUTBOUND_TYPES and first <= _d(t["date"]) <= last + timedelta(days=7)
        ]
    onward_total = round(sum(t["amount"] for t in onward), 2)
    onward_ratio = round(onward_total / cash_total, 2) if cash_total else 0.0
    cross_border = sorted({t["counterparty_country"] for t in onward if t["counterparty_country"] != customer.get("residence_country")})
    best_similarity, best_party = 0.0, None
    for t in onward:
        result = screen_party(data, t["counterparty"], t.get("counterparty_country"))
        if result["candidates"] and result["candidates"][0]["score"] > best_similarity:
            best_similarity, best_party = result["candidates"][0]["score"], (t["counterparty"], result["candidates"][0]["listed_name"])
    deviation = profile_deviation(data, customer)
    return [
        _indicator("structuring_deposits", f"Cash deposits between EUR {th['structuring_band_low']:,.0f} and EUR {th['cash_reporting_threshold']:,.0f} within {window} days", {"count": len(best), "total_eur": cash_total, "dates": [t["date"] for t in best], "txn_ids": [t["txn_id"] for t in best]}, f">= {th['structuring_min_deposits']:g} deposits", len(best) >= th["structuring_min_deposits"], 30),
        _indicator("multiple_branches", "Distinct branches used for the deposits", {"count": len(branches), "branches": branches}, ">= 3 branches", len(branches) >= 3, 10),
        _indicator("profile_deviation", "Credits in last 30 days vs expected monthly credits", f"{deviation}x", f">= {th['profile_deviation_multiple']:g}x", deviation >= th["profile_deviation_multiple"], 15),
        _indicator("rapid_onward_transfer", "Outbound transfers within 7 days after the last deposit, as share of the cash total", {"ratio": onward_ratio, "total_eur": onward_total, "txn_ids": [t["txn_id"] for t in onward], "counterparties": sorted({t["counterparty"] for t in onward})}, ">= 0.8", onward_ratio >= 0.8, 20),
        _indicator("cross_border_onward", "Onward transfers sent abroad", cross_border, "any", bool(cross_border), 5),
        _indicator("counterparty_partial_watchlist_similarity", "Best watchlist name similarity of onward counterparties (below the potential-match threshold)", {"score": best_similarity, "pair": best_party}, f">= 0.6 and < {th['screening_potential_match']}", 0.6 <= best_similarity < th["screening_potential_match"], 5),
    ]


def _mule(data: BankData, alert: dict, customer: dict, th: dict) -> list[dict]:
    txns = data.customer_transactions(customer["customer_id"])
    inbound = [t for t in txns if t["type"] == "instant_in"]
    senders = sorted({t["counterparty"] for t in inbound})
    inbound_total = round(sum(t["amount"] for t in inbound), 2)
    hours = int(th["mule_pass_through_window_hours"])
    outbound: list[dict] = []
    if inbound:
        first, last = _d(inbound[0]["date"]), _d(inbound[-1]["date"])
        outbound = [t for t in txns if t["type"] in _OUTBOUND_TYPES and first <= _d(t["date"]) <= last + timedelta(hours=hours)]
    outbound_total = round(sum(t["amount"] for t in outbound), 2)
    ratio = round(outbound_total / inbound_total, 3) if inbound_total else 0.0
    categories = data.meta.get("counterparty_categories", {})
    casp = sorted({t["counterparty"] for t in outbound if "crypto" in categories.get(t["counterparty"], "").lower()})
    deviation = profile_deviation(data, customer)
    age = None
    if customer.get("date_of_birth"):
        dob = _d(customer["date_of_birth"])
        age = data.as_of.year - dob.year - ((data.as_of.month, data.as_of.day) < (dob.month, dob.day))
    return [
        _indicator("unrelated_senders", "Distinct individuals sending instant transfers", {"count": len(senders), "transfers": len(inbound), "total_eur": inbound_total}, f">= {th['mule_min_unrelated_senders']:g}", len(senders) >= th["mule_min_unrelated_senders"], 25),
        _indicator("pass_through", f"Share of inbound value sent out within {hours} hours", {"ratio": ratio, "outbound_eur": outbound_total, "txn_ids": [t["txn_id"] for t in outbound]}, f">= {th['mule_pass_through_ratio']}", ratio >= th["mule_pass_through_ratio"], 30),
        _indicator("crypto_destination", "Outbound funds sent to a crypto-asset service provider", casp, "any", bool(casp), 10),
        _indicator("profile_deviation", "Credits in last 30 days vs expected monthly credits", f"{deviation}x", f">= {th['profile_deviation_multiple']:g}x", deviation >= th["profile_deviation_multiple"], 15),
        _indicator("vulnerable_profile", "Customer younger than 25 (mule recruitment risk; may also be a victim)", {"age": age}, "< 25", age is not None and age < 25, 5),
    ]


def _sanctions(data: BankData, alert: dict, customer: dict, th: dict) -> tuple[list[dict], dict]:
    party = alert.get("screened_party", {})
    result = screen_party(data, party.get("name", ""), party.get("country"), party.get("registration"), party.get("address"))
    top = result["candidates"][0] if result["candidates"] else {}
    comparison = top.get("identifier_comparison", {})
    listed_on = top.get("listed_on")
    prior = [
        t for t in data.customer_transactions(customer["customer_id"])
        if t["type"] in _OUTBOUND_TYPES and t.get("status") == "Completed"
        and name_similarity(t["counterparty"], party.get("name", "")) >= 0.95
    ]
    recently_listed = bool(listed_on) and (data.as_of - _d(listed_on)).days <= 30
    held = next((t for t in data.customer_transactions(customer["customer_id"]) if t.get("status") == "HELD"), None)
    indicators = [
        _indicator("potential_name_match", "Name similarity to a sanctions list entry", {"score": top.get("score"), "listed_name": top.get("listed_name"), "entry_id": top.get("entry_id")}, f">= {th['screening_potential_match']}", (top.get("score") or 0) >= th["screening_potential_match"], 45),
        _indicator("recently_listed", "List entry added within the last 30 days", listed_on, "<= 30 days", recently_listed, 10),
        _indicator("high_value_cross_border", "Held payment is cross-border and above EUR 100,000", {"amount_eur": held["amount"] if held else None, "country": party.get("country")}, "> EUR 100,000", bool(held and held["amount"] > 100000), 5),
        _indicator("registration_mismatch", "Registration number differs from the list entry (reduces likelihood of a true match)", comparison.get("registration_or_dob"), "mismatch", comparison.get("registration_or_dob") == "mismatch", -5),
        _indicator("address_mismatch", "Registered address differs from the list entry (reduces likelihood of a true match)", comparison.get("address"), "mismatch", comparison.get("address") == "mismatch", -5),
    ]
    extra = {
        "screening": result,
        "disposition_hint": top.get("disposition_hint"),
        "prior_completed_payments_to_beneficiary": {
            "count": len(prior), "total_eur": round(sum(t["amount"] for t in prior), 2),
            "dates": [t["date"] for t in prior],
            "all_before_listing_date": bool(listed_on) and all(_d(t["date"]) < _d(listed_on) for t in prior),
        },
        "held_payment": held,
    }
    return indicators, extra


def _large(data: BankData, alert: dict, customer: dict, th: dict) -> tuple[list[dict], dict]:
    txn_ids = set(alert.get("related_transaction_ids", []))
    txn = next((t for t in data.customer_transactions(customer["customer_id"]) if t["txn_id"] in txn_ids), None)
    amount = txn["amount"] if txn else 0.0
    sof_match: Optional[dict] = None
    for doc in customer.get("source_of_funds_documents", []):
        expected = float(doc.get("expected_amount_eur") or 0)
        if not (txn and expected):
            continue
        amount_ok = abs(expected - amount) <= 0.01 * expected
        cp_ok = name_similarity(doc.get("expected_counterparty", ""), txn["counterparty"]) >= 0.85
        timing_ok = _d(doc["uploaded"]) <= _d(txn["date"])
        if amount_ok and cp_ok and timing_ok:
            sof_match = {"doc_id": doc["doc_id"], "verified_by": doc.get("verified_by"), "verified_on": doc.get("verified_on")}
    deviation = profile_deviation(data, customer)
    indicators = [
        _indicator("large_amount", "Single incoming transaction amount", amount, f">= EUR {th['large_incoming_amount']:,.0f}", amount >= th["large_incoming_amount"], 15),
        _indicator("profile_deviation", "Credits in last 30 days vs expected monthly credits", f"{deviation}x", f">= {th['profile_deviation_multiple']:g}x", deviation >= th["profile_deviation_multiple"], 15),
        _indicator("documented_source_of_funds", "Verified source-of-funds document matches amount, counterparty and timing (reduces risk)", sof_match, "match", sof_match is not None, -30),
    ]
    return indicators, {"transaction": txn}


def _pep(data: BankData, alert: dict, customer: dict, th: dict) -> list[dict]:
    pep = customer.get("pep") or {}
    due = pep.get("edd_refresh_due")
    overdue = (data.as_of - _d(due)).days if due else 0
    txn_ids = set(alert.get("related_transaction_ids", []))
    txns = [t for t in data.customer_transactions(customer["customer_id"]) if t["txn_id"] in txn_ids]
    jurisdictions = data.meta.get("enhanced_monitoring_jurisdictions", {})
    flagged = sorted({t["counterparty_country"] for t in txns if t["counterparty_country"] in jurisdictions})
    sow_gap = [d["doc_id"] for d in customer.get("source_of_funds_documents", []) if "not on file" in d.get("description", "").lower()]
    deviation = profile_deviation(data, customer)
    return [
        _indicator("pep_status", "Customer is a PEP or a relative/close associate (RCA)", pep.get("status"), "PEP or RCA", bool(pep), 25),
        _indicator("edd_overdue", "Days the annual enhanced due diligence refresh is overdue", overdue, "> 0 days", overdue > 0, 25),
        _indicator("enhanced_monitoring_origin", "Funds originate from an enhanced-monitoring jurisdiction", [f"{c}: {jurisdictions[c]}" for c in flagged], "any", bool(flagged), 10),
        _indicator("source_of_wealth_gap", "Source-of-wealth evidence incomplete", sow_gap, "any gap", bool(sow_gap), 5),
        _indicator("profile_deviation", "Credits in last 30 days vs expected monthly credits", f"{deviation}x", f">= {th['profile_deviation_multiple']:g}x", deviation >= th["profile_deviation_multiple"], 15),
    ]


def _tbml(data: BankData, alert: dict, customer: dict, th: dict) -> list[dict]:
    trade = alert.get("trade_details", {})
    reference = data.meta.get("trade_reference_prices", {}).get(trade.get("goods", ""), {})
    ref_price = float(reference.get("unit_price_eur") or 0)
    unit_price = float(trade.get("unit_price_eur") or 0)
    deviation_pct = round((unit_price - ref_price) / ref_price * 100, 1) if ref_price else 0.0
    amount = round(unit_price * float(trade.get("units") or 0), 2)
    return [
        _indicator("unit_price_deviation", "Invoice unit price vs reference price", {"unit_price_eur": unit_price, "reference_eur": ref_price, "deviation_pct": deviation_pct, "reference_source": reference.get("source")}, f"> {th['trade_price_deviation_pct']:g}%", abs(deviation_pct) > th["trade_price_deviation_pct"], 35),
        _indicator("high_value_payment", "Payment value", amount, ">= EUR 100,000", amount >= 100000, 5),
    ]


def compute_risk_indicators(data: BankData, alert: dict[str, Any], customer: dict[str, Any]) -> dict[str, Any]:
    th = {k: float(v) for k, v in data.meta["thresholds"].items()}
    rule = alert["rule_id"]
    extra: dict[str, Any] = {}
    if rule == "TM-STR-03":
        indicators = _structuring(data, alert, customer, th)
    elif rule == "TM-MULE-07":
        indicators = _mule(data, alert, customer, th)
    elif rule == "SCR-SAN-01":
        indicators, extra = _sanctions(data, alert, customer, th)
    elif rule == "TM-LRG-01":
        indicators, extra = _large(data, alert, customer, th)
    elif rule == "KYC-PEP-02":
        indicators = _pep(data, alert, customer, th)
    elif rule == "TBML-PRC-04":
        indicators = _tbml(data, alert, customer, th)
    else:
        indicators = []

    manipulation = detect_injection(alert.get("narrative", ""))
    indicators.append(_indicator(
        "manipulation_attempt", "Untrusted free text tries to instruct the reviewer or AI (POL-10)", manipulation, "any pattern", bool(manipulation), 20,
    ))

    score = max(5, min(100, sum(i["weight"] for i in indicators)))
    rating = "High" if score >= 70 else "Medium" if score >= 40 else "Low"
    return {
        "alert_id": alert["alert_id"],
        "rule_id": rule,
        "indicators": indicators,
        "indicative_score": score,
        "indicative_rating": rating,
        **extra,
        "method": "Deterministic rule-based indicators over synthetic data. Indicative only; not a decision. Humans decide (POL-01).",
    }
