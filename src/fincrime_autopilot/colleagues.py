"""Agent-to-agent collaboration between hired bid desk instances: ask, don't access.

An instance never reads another team's library (Azure RBAC refuses its token). Instead it can
@mention a colleague instance in the same Teams chat or meeting chat, and the colleague answers
from its own library, in front of the humans. This module holds the deterministic parts:

* who the colleague instances are (``BID_COLLEAGUES``: agent user object ID -> display name,
  written by ``scripts/sync-bid-desk-instances.ps1``),
* recognising a turn sent by a colleague instance (by object ID, never by display name),
* recognising a human request that involves a colleague (so the Teams tool is offered),
* a per-conversation budget for colleague turns (loop breaker, defence in depth).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

_GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)

DEFAULT_MAX_COLLEAGUE_TURNS = 3
DEFAULT_COLLEAGUE_WINDOW_SECONDS = 600


@dataclass(frozen=True)
class Colleague:
    user_id: str
    name: str


def load_colleagues(raw: Optional[str] = None) -> dict[str, str]:
    """``BID_COLLEAGUES`` JSON object: agent user object ID -> display name. Empty disables the feature."""
    raw = os.getenv("BID_COLLEAGUES", "") if raw is None else raw
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        logger.warning("BID_COLLEAGUES is not valid JSON; agent-to-agent collaboration is off")
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {
        key.lower(): str(name).strip()
        for key, name in parsed.items()
        if isinstance(key, str) and _GUID.fullmatch(key.strip()) and str(name).strip()
    }


def _object_id(value: Any) -> str:
    match = _GUID.search(str(value or ""))
    return match.group(0).lower() if match else ""


def colleague_sender(
    sender_values: Iterable[Any],
    colleagues: dict[str, str],
    self_ids: Iterable[Any] = (),
) -> Optional[Colleague]:
    """The colleague instance that sent this activity, matched on its object ID (``aadObjectId`` or ``8:orgid:<id>``)."""
    own = {_object_id(v) for v in self_ids} - {""}
    for value in sender_values:
        oid = _object_id(value)
        if oid and oid in colleagues and oid not in own:
            return Colleague(oid, colleagues[oid])
    return None


def _squash(text: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def directory(colleagues: dict[str, str], self_ids: Iterable[Any] = ()) -> list[Colleague]:
    """Colleague instances other than this one, sorted by name."""
    own = {_object_id(v) for v in self_ids} - {""}
    return sorted((Colleague(k, v) for k, v in colleagues.items() if k not in own), key=lambda c: c.name.lower())


def mentioned_colleagues(text: Optional[str], colleagues: Iterable[Colleague]) -> list[Colleague]:
    """Colleagues named in a human's message ("ask PublicSectorBids ...", "use PublicSectorBids' answer")."""
    haystack = _squash(text)
    return [c for c in colleagues if _squash(c.name) and _squash(c.name) in haystack]


class ColleagueTurnBudget:
    """At most ``max_turns`` colleague-sent turns per conversation within ``window_seconds``.

    The main loop breaker is structural (a colleague turn gets no Teams tool, so it can't @mention
    anyone, and plain replies are not delivered to other instances). This budget caps the damage if
    that ever changes, for example a misconfigured instance that keeps @mentioning this one.
    """

    def __init__(self, max_turns: Optional[int] = None, window_seconds: Optional[float] = None) -> None:
        self.max_turns = max_turns if max_turns is not None else _int_env("COLLEAGUE_MAX_TURNS", DEFAULT_MAX_COLLEAGUE_TURNS)
        self.window_seconds = (
            window_seconds if window_seconds is not None
            else _int_env("COLLEAGUE_WINDOW_SECONDS", DEFAULT_COLLEAGUE_WINDOW_SECONDS)
        )
        self._turns: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, conversation_id: str, now: Optional[float] = None) -> bool:
        now = time.monotonic() if now is None else now
        turns = self._turns[conversation_id or "default"]
        while turns and now - turns[0] >= self.window_seconds:
            turns.popleft()
        if len(turns) >= self.max_turns:
            return False
        turns.append(now)
        return True


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except ValueError:
        return default
