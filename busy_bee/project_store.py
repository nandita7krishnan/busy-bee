"""Per-project status store: the JSON file dashctl reads and writes.

Lives at <project_root>/.claude-dashboard/status.json. This is the
"local status store" in the architecture diagram -- append-only, full
history retained, one file per project. The aggregator later reads this
file and merges it into the central SQLite store.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from busy_bee import process_utils

ItemType = Literal["done", "todo", "blocker", "question", "summary", "session_start"]
VALID_TYPES: tuple[ItemType, ...] = ("done", "todo", "blocker", "question", "summary", "session_start")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status_file(project_root: Path) -> Path:
    return project_root / ".claude-dashboard" / "status.json"


def _load(project_root: Path) -> list[dict]:
    path = _status_file(project_root)
    if not path.exists():
        return []
    with path.open() as f:
        return json.load(f)


def _save(project_root: Path, items: list[dict]) -> None:
    path = _status_file(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(items, f, indent=2)
    tmp.replace(path)


def add_item(project_root: Path, item_type: ItemType, text: str, source: str = "agent") -> dict:
    if item_type not in VALID_TYPES:
        raise ValueError(f"invalid item type: {item_type!r} (must be one of {VALID_TYPES})")
    items = _load(project_root)
    item = {
        "id": uuid.uuid4().hex[:12],
        "type": item_type,
        "text": text,
        "created_at": _now(),
        "resolved_at": None,
        "source": source,
        "terminal_tty": process_utils.find_claude_ancestor_tty(),
        "session_id": process_utils.current_session_id(),
    }
    items.append(item)
    _save(project_root, items)
    return item


def mark_session_start(project_root: Path) -> dict:
    """Logs a 'session_start' marker as soon as a Claude Code session
    begins, before it's done anything else worth logging. Without this,
    a brand new session in a terminal tty the OS just reused (its
    previous occupant now closed) would have no items of its own yet --
    every lookup keyed by "the most recent session_id logged for this
    tty" would still resolve to the old, unrelated session, so the
    dashboard would show its title and todo list until the new session
    got around to logging something itself. See hooks/session_start_hook.py."""
    return add_item(project_root, "session_start", "session started", source="hook")


def auto_resolve_dead_sessions(
    project_root: Path, live_ttys: set[str], session_started_at: dict[str, str] | None = None
) -> bool:
    """Marks any still-open blocker/question resolved once the session
    that logged it has ended -- it can't act on it or answer it, so
    leaving it flagged forever just piles up stale noise on the
    dashboard (it was otherwise never dropped, by design, so it
    wouldn't be silently lost while the session was still live). Only
    items with a recorded terminal_tty are eligible -- older items from
    before that was tracked have no tty to judge liveness by, and are
    left for manual `dashctl resolve`. Returns True if anything changed,
    so the caller can skip an unnecessary rewrite.

    A session counts as ended either because its terminal closed (its
    tty is gone from live_ttys) or because the tty outlived it: macOS
    hands a closed window's tty number to the next one, so a flag can
    sit on a tty that is live again while the session that raised it is
    long gone. `session_started_at` (tty -> ISO8601, from
    process_utils.claude_session_start_times) catches that second case
    -- anything logged before the `claude` currently on that tty
    started belongs to a dead session. Ttys missing from it are judged
    on liveness alone, as before."""
    items = _load(project_root)
    started_at = session_started_at or {}
    changed = False
    for item in items:
        tty = item.get("terminal_tty")
        if item["type"] not in ("blocker", "question") or item["resolved_at"] is not None or not tty:
            continue
        if tty in live_ttys and not process_utils.logged_before_session_start(
            item["created_at"], started_at.get(tty)
        ):
            continue
        item["resolved_at"] = _now()
        changed = True
    if changed:
        _save(project_root, items)
    return changed


def resolve_item(project_root: Path, item_type: ItemType, item_id: str) -> bool:
    if item_type not in ("blocker", "question", "todo"):
        raise ValueError("only blocker, question, or todo items can be resolved")
    items = _load(project_root)
    for item in items:
        if item["id"] == item_id and item["type"] == item_type:
            if item["resolved_at"] is None:
                item["resolved_at"] = _now()
            _save(project_root, items)
            return True
    return False


def all_items(project_root: Path) -> list[dict]:
    return _load(project_root)


def latest_terminal_tty(items: list[dict]) -> str | None:
    """The tty of the most recent item that has one recorded -- i.e.
    whichever terminal most recently logged status for this project."""
    with_tty = [i for i in items if i.get("terminal_tty")]
    if not with_tty:
        return None
    return max(with_tty, key=lambda i: i["created_at"])["terminal_tty"]


def latest_summary(items: list[dict]) -> str | None:
    """The text of the most recently logged `summary` item, if any."""
    summaries = [i for i in items if i["type"] == "summary"]
    if not summaries:
        return None
    return max(summaries, key=lambda i: i["created_at"])["text"]


def has_logged_this_turn(
    project_root: Path, since_seconds: int = 120, item_type: ItemType | None = None
) -> bool:
    """Used by the Stop hook: did anything (or, if item_type is given,
    that specific type) get logged recently?"""
    items = _load(project_root)
    if item_type is not None:
        items = [i for i in items if i["type"] == item_type]
    if not items:
        return False
    latest = max(items, key=lambda i: i["created_at"])
    latest_dt = datetime.fromisoformat(latest["created_at"])
    delta = datetime.now(timezone.utc) - latest_dt
    return delta.total_seconds() <= since_seconds


def _turn_counts_file(project_root: Path) -> Path:
    return project_root / ".claude-dashboard" / "turn_counts.json"


def bump_turn_count(project_root: Path, session_id: str) -> tuple[int, str | None]:
    """Increments this session's turn count for this project and
    returns (new_count, previous_turn_boundary). previous_turn_boundary
    is the timestamp of the *previous* call for this session_id (None
    on the very first) -- the start-of-this-turn marker that
    summary_logged_since compares against. Used by the Stop hook to
    require a `dashctl summary` every Nth turn, starting with the
    first, instead of leaving it entirely up to the agent's own
    judgment of when a summary is warranted -- that alone tended to
    leave a project's session header showing Claude Code's
    auto-generated tab title for a while instead of a real summary.

    Keyed by session_id rather than terminal tty -- a tty gets reused
    across unrelated `claude` invocations in the same terminal window,
    which would otherwise let a brand new session inherit a previous,
    unrelated session's turn count."""
    path = _turn_counts_file(project_root)
    state: dict[str, dict] = {}
    if path.exists():
        with path.open() as f:
            state = json.load(f)
    entry = state.get(session_id, {"count": 0, "last_bump_at": None})
    previous_bump_at = entry["last_bump_at"]
    new_count = entry["count"] + 1
    state[session_id] = {"count": new_count, "last_bump_at": _now()}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(state, f, indent=2)
    tmp.replace(path)
    return new_count, previous_bump_at


def summary_logged_since(project_root: Path, session_id: str, since: str | None) -> bool:
    """Has this specific session logged a `dashctl summary` more
    recently than `since` (the previous turn's boundary, from
    bump_turn_count)? Deliberately not a fixed recency window like
    has_logged_this_turn -- a summary logged several turns ago is still
    "recent" by wall-clock time in a fast back-and-forth session, which
    would silently let it satisfy a much later checkpoint. Comparing
    against the actual previous-turn boundary doesn't have that gap.
    `since=None` (this session's first-ever turn) means any summary
    counts."""
    items = [
        i for i in _load(project_root) if i["type"] == "summary" and i.get("session_id") == session_id
    ]
    if not items:
        return False
    if since is None:
        return True
    latest = max(items, key=lambda i: i["created_at"])
    return latest["created_at"] > since
