"""Synthetic Contoso Bank data access and name-matching helpers.

Everything in ``data/`` is fictional demo data. In production these lookups
would be calls to the core-banking, transaction-monitoring and screening
systems, authorised against the autopilot instance's own Entra identity.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

DATA_DIR = Path(__file__).resolve().parent / "data"

_LEGAL_FORMS = {
    "llc", "l l c", "ltd", "limited", "gmbh", "bv", "b v", "ou", "oy", "ab", "sa", "s a",
    "fze", "fzco", "plc", "ag", "co", "inc", "corp", "corporation", "company", "nv",
}


@dataclass(frozen=True)
class BankData:
    meta: dict[str, Any]
    customers: dict[str, dict[str, Any]]
    alerts: dict[str, dict[str, Any]]
    transactions: list[dict[str, Any]]
    watchlists: dict[str, Any]
    policies: list[dict[str, Any]]
    as_of: date = field(default=date(2026, 10, 26))

    def customer_transactions(self, customer_id: str) -> list[dict[str, Any]]:
        return sorted(
            (t for t in self.transactions if t["customer_id"] == customer_id),
            key=lambda t: (t["date"], t["txn_id"]),
        )


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=4)
def load_bank_data(data_dir: Optional[str] = None) -> BankData:
    base = Path(data_dir) if data_dir else DATA_DIR
    meta = _read_json(base / "meta.json")
    customers = {c["customer_id"]: c for c in _read_json(base / "customers.json")}
    alerts = {a["alert_id"]: a for a in _read_json(base / "alerts.json")}
    transactions = _read_json(base / "transactions.json")
    watchlists = _read_json(base / "watchlists.json")
    policies = _read_json(base / "policies.json")
    return BankData(
        meta=meta,
        customers=customers,
        alerts=alerts,
        transactions=transactions,
        watchlists=watchlists,
        policies=policies,
        as_of=date.fromisoformat(meta.get("as_of", "2026-10-26")),
    )


def normalize_name(name: str) -> str:
    """Lower-case, strip accents and punctuation, and drop legal-form tokens."""
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    for form in sorted(_LEGAL_FORMS, key=len, reverse=True):
        text = re.sub(rf"(?:^| ){re.escape(form)}(?= |$)", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _token_average(left: list[str], right: list[str]) -> float:
    if not left or not right:
        return 0.0
    total = 0.0
    for token in left:
        total += max(SequenceMatcher(None, token, other).ratio() for other in right)
    return total / len(left)


def name_similarity(first: str, second: str) -> float:
    """Return a 0..1 similarity combining full-string and token-level matching."""
    a, b = normalize_name(first), normalize_name(second)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    full = SequenceMatcher(None, a, b).ratio()
    tokens_a, tokens_b = a.split(), b.split()
    token = (_token_average(tokens_a, tokens_b) + _token_average(tokens_b, tokens_a)) / 2
    return round(max(full, token), 2)


def normalize_identifier(value: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())
