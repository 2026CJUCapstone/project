"""Revision-keyed, public-only contest scoreboard cache helpers.

The cache is deliberately a disposable performance layer.  The database owns
the monotonically increasing revision and all score calculations remain
reproducible from the receipt ledger.  Cached values contain only the public
scoreboard shape; names, contest state, and server time are added by the
caller for every response.
"""
from __future__ import annotations

import math
import re
from typing import Any

from sqlalchemy import func

from app.models import database as m
from app.services.redis_client import cache_get_json, cache_set_json, redis_key


# A scoreboard may be requested often while a contest is live, but correctness
# never depends on Redis.  Revision-specific keys make old values unreachable
# immediately after a committed write; TTL only bounds unused-key retention.
SCOREBOARD_CACHE_TTL_SECONDS = 15
_MAX_ROWS = 10_000
_MAX_PROBLEMS = 200
_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_VERDICT = re.compile(r"[a-z_]{1,64}\Z")
_LABEL = re.compile(r"[A-Z]\Z")
_ISO_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z")
_MUTATING_TRANSACTION_INFO_KEY = "scoreboard_revision_mutating_transaction"


def bump_scoreboard_revision(db, contest_id: str) -> None:
    """Atomically advance one contest revision inside the caller's transaction.

    This function never commits.  Therefore a failed admission, result
    publication, or finalization rolls the revision back with the associated
    scoreboard change.
    """
    updated = db.query(m.Contest).filter(m.Contest.id == contest_id).update(
        {m.Contest.scoreboard_revision: func.coalesce(m.Contest.scoreboard_revision, 0) + 1},
        synchronize_session=False,
    )
    if updated != 1:
        raise LookupError("Contest disappeared while advancing its scoreboard revision")
    # Do not let this session publish an uncommitted projection under a
    # revision that a rollback can reuse.  Store the transaction object, not
    # a boolean: the next transaction on the same long-lived session is safe.
    transaction = db.get_transaction()
    if transaction is None:  # Query.update always starts one; keep fail-closed.
        raise RuntimeError("Scoreboard revision update has no enclosing transaction")
    db.info[_MUTATING_TRANSACTION_INFO_KEY] = transaction


def cache_safe_session(db) -> bool:
    """Whether this session can consume or publish a committed Redis value."""
    if db.new or db.dirty or db.deleted:
        return False
    marker = db.info.get(_MUTATING_TRANSACTION_INFO_KEY)
    return marker is None or marker is not db.get_transaction()


def current_revision(db, contest_id: str) -> int | None:
    """Read the committed/current transaction generation without ORM staleness."""
    value = db.query(m.Contest.scoreboard_revision).filter(m.Contest.id == contest_id).scalar()
    return value if type(value) is int and 0 <= value <= 9_223_372_036_854_775_807 else None


def cache_key(contest_id: str, revision: int) -> str | None:
    if not isinstance(contest_id, str) or _IDENTIFIER.fullmatch(contest_id) is None:
        return None
    if type(revision) is not int or not 0 <= revision <= 9_223_372_036_854_775_807:
        return None
    return redis_key("contest-scoreboard", "public-v1", contest_id, str(revision))


def read_public(contest_id: str, revision: int) -> dict[str, Any] | None:
    key = cache_key(contest_id, revision)
    if key is None:
        return None
    return _validated_projection(cache_get_json(key))


def write_public(contest_id: str, revision: int, projection: dict[str, Any]) -> None:
    key = cache_key(contest_id, revision)
    normalized = _validated_projection(projection)
    if key is None or normalized is None:
        return
    cache_set_json(key, normalized, ttl_seconds=SCOREBOARD_CACHE_TTL_SECONDS)


def _identifier(value: Any) -> str | None:
    return value if isinstance(value, str) and _IDENTIFIER.fullmatch(value) else None


def _integer(value: Any, *, minimum: int = 0) -> int | None:
    return value if type(value) is int and minimum <= value <= 2_147_483_647 else None


def _number(value: Any, *, minimum: float = 0) -> int | float | None:
    if type(value) not in (int, float) or not math.isfinite(value) or value < minimum:
        return None
    return value


def _short_text(value: Any, *, pattern: re.Pattern[str] | None = None, maximum: int = 64) -> str | None:
    if not isinstance(value, str) or not value or len(value) > maximum:
        return None
    if pattern is not None and pattern.fullmatch(value) is None:
        return None
    return value


def _cell(value: Any) -> dict[str, Any] | None:
    expected = {
        "contestProblemId", "label", "points", "wrongAttempts", "acceptedAt",
        "elapsedSeconds", "pending", "verdict",
    }
    if not isinstance(value, dict) or set(value) != expected:
        return None
    contest_problem_id = _identifier(value["contestProblemId"])
    label = _short_text(value["label"], pattern=_LABEL, maximum=1)
    points = _integer(value["points"])
    wrong_attempts = _integer(value["wrongAttempts"])
    accepted_at = value["acceptedAt"]
    elapsed = value["elapsedSeconds"]
    verdict = value["verdict"]
    if contest_problem_id is None or label is None or points is None or wrong_attempts is None:
        return None
    if accepted_at is not None and _short_text(accepted_at, pattern=_ISO_TIMESTAMP, maximum=32) is None:
        return None
    if elapsed is not None and _number(elapsed) is None:
        return None
    if type(value["pending"]) is not bool:
        return None
    if verdict is not None and _short_text(verdict, pattern=_VERDICT) is None:
        return None
    return {
        "contestProblemId": contest_problem_id,
        "label": label,
        "points": points,
        "wrongAttempts": wrong_attempts,
        "acceptedAt": accepted_at,
        "elapsedSeconds": elapsed,
        "pending": value["pending"],
        "verdict": verdict,
    }


def _row(value: Any) -> dict[str, Any] | None:
    expected = {"userId", "totalPoints", "penaltySeconds", "problems", "rank"}
    if not isinstance(value, dict) or set(value) != expected:
        return None
    user_id = _identifier(value["userId"])
    total = _integer(value["totalPoints"])
    penalty = _number(value["penaltySeconds"])
    rank = _integer(value["rank"], minimum=1)
    cells_value = value["problems"]
    if user_id is None or total is None or penalty is None or rank is None:
        return None
    if not isinstance(cells_value, list) or len(cells_value) > _MAX_PROBLEMS:
        return None
    cells = [_cell(cell) for cell in cells_value]
    if any(cell is None for cell in cells):
        return None
    return {
        "userId": user_id,
        "totalPoints": total,
        "penaltySeconds": penalty,
        "problems": cells,
        "rank": rank,
    }


def _problem(value: Any) -> dict[str, Any] | None:
    expected = {"id", "label", "points"}
    if not isinstance(value, dict) or set(value) != expected:
        return None
    identifier = _identifier(value["id"])
    label = _short_text(value["label"], pattern=_LABEL, maximum=1)
    points = _integer(value["points"])
    if identifier is None or label is None or points is None:
        return None
    return {"id": identifier, "label": label, "points": points}


def _validated_projection(value: Any) -> dict[str, Any] | None:
    """Return a fresh, strict public shape or reject a missing/corrupt value."""
    expected = {"rows", "pendingCount", "problems"}
    if not isinstance(value, dict) or set(value) != expected:
        return None
    rows_value, problems_value = value["rows"], value["problems"]
    pending = _integer(value["pendingCount"])
    if pending is None or not isinstance(rows_value, list) or not isinstance(problems_value, list):
        return None
    if len(rows_value) > _MAX_ROWS or len(problems_value) > _MAX_PROBLEMS:
        return None
    rows = [_row(row) for row in rows_value]
    problems = [_problem(problem) for problem in problems_value]
    if any(row is None for row in rows) or any(problem is None for problem in problems):
        return None
    return {"rows": rows, "pendingCount": pending, "problems": problems}
