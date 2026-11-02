"""Sanctions and PEP screening over the synthetic SYN-CONSOLIDATED lists."""

from __future__ import annotations

from typing import Any, Optional

from .fsi_data import BankData, name_similarity, normalize_identifier, normalize_name

MIN_REPORTED_SCORE = 0.5


def _compare_identifier(provided: Optional[str], listed: Optional[str]) -> str:
    if not provided:
        return "not_provided"
    if not listed:
        return "not_on_list"
    return "match" if normalize_identifier(provided) == normalize_identifier(listed) else "mismatch"


def _compare_address(provided: Optional[str], listed: Optional[str]) -> str:
    if not provided:
        return "not_provided"
    if not listed:
        return "not_on_list"
    return "match" if name_similarity(provided, listed) >= 0.8 else "mismatch"


def _compare_country(provided: Optional[str], listed: Optional[str]) -> str:
    if not provided:
        return "not_provided"
    if not listed:
        return "not_on_list"
    return "match" if provided.strip().upper() == listed.strip().upper() else "mismatch"


def _disposition_hint(score: float, threshold: float, identifiers: dict[str, str]) -> str:
    if score < threshold:
        return "below_threshold_document_and_continue"
    strong = [identifiers.get("registration_or_dob"), identifiers.get("address")]
    if "match" in strong:
        return "probable_true_match_freeze_and_escalate_to_sanctions_officer"
    if strong.count("mismatch") == 2:
        return "likely_false_positive_pending_L2_signoff"
    return "insufficient_identifiers_L2_review_required"


def screen_party(
    data: BankData,
    name: str,
    country: Optional[str] = None,
    identifier: Optional[str] = None,
    address: Optional[str] = None,
) -> dict[str, Any]:
    threshold = float(data.meta["thresholds"]["screening_potential_match"])
    candidates: list[dict[str, Any]] = []

    for entry in data.watchlists.get("sanctions", []):
        names = [entry["name"], *entry.get("aliases", [])]
        best_name, best_score = max(
            ((n, name_similarity(name, n)) for n in names), key=lambda item: item[1]
        )
        if best_score < MIN_REPORTED_SCORE:
            continue
        listed_identifier = entry.get("registration") or entry.get("date_of_birth")
        identifiers = {
            "registration_or_dob": _compare_identifier(identifier, listed_identifier),
            "address": _compare_address(address, entry.get("address")),
            "country": _compare_country(country, entry.get("country")),
        }
        candidates.append({
            "list": "sanctions",
            "entry_id": entry["entry_id"],
            "listed_name": entry["name"],
            "matched_on": best_name,
            "score": best_score,
            "verdict": "potential_match" if best_score >= threshold else "below_threshold",
            "listed_identifiers": {
                "registration_or_dob": listed_identifier,
                "address": entry.get("address"),
                "country": entry.get("country"),
            },
            "identifier_comparison": identifiers,
            "program": entry.get("program"),
            "listed_on": entry.get("listed_on"),
            "disposition_hint": _disposition_hint(best_score, threshold, identifiers),
        })

    for entry in data.watchlists.get("pep", []):
        pep_score = name_similarity(name, entry["name"])
        if pep_score >= MIN_REPORTED_SCORE:
            candidates.append({
                "list": "pep",
                "entry_id": entry["entry_id"],
                "listed_name": entry["name"],
                "score": pep_score,
                "verdict": "potential_match" if pep_score >= threshold else "below_threshold",
                "role": entry.get("role"),
                "category": entry.get("category"),
            })
        for rca in entry.get("relatives_and_close_associates", []):
            rca_score = name_similarity(name, rca["name"])
            if rca_score >= threshold:
                candidates.append({
                    "list": "pep_rca",
                    "entry_id": entry["entry_id"],
                    "listed_name": rca["name"],
                    "score": rca_score,
                    "verdict": "potential_match",
                    "relationship": f"{rca['relationship']} of {entry['name']} ({entry.get('role')})",
                })

    candidates.sort(key=lambda c: c["score"], reverse=True)
    top = candidates[:3]
    overall = "potential_match" if any(c["verdict"] == "potential_match" for c in top) else (
        "below_threshold" if top else "no_match"
    )
    return {
        "screened_name": name,
        "normalized_name": normalize_name(name),
        "list_version": data.watchlists.get("list_version"),
        "threshold": threshold,
        "overall_result": overall,
        "candidates": top,
        "note": "Synthetic lists. A potential match is not a confirmed match; follow POL-03 and require L2 sign-off.",
    }
