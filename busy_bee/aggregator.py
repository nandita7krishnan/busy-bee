"""Aggregator: scans configured project paths, reads each project's
local status.json, and merges it into the central SQLite store.

Runs on a simple poll interval -- simplest thing that works reliably,
per the PRD ("whichever is simpler to build"). A project's status is
derived, not stored by the agent: 'blocked' if it has any unresolved
blocker, 'active' if something was logged recently, else 'idle'.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from busy_bee import config, db, process_utils, project_store, terminal_launcher

ACTIVE_WINDOW = timedelta(minutes=30)


def derive_status(items: list[dict]) -> str:
    if any(i["type"] == "blocker" and i["resolved_at"] is None for i in items):
        return "blocked"
    if items:
        latest = max(items, key=lambda i: i["created_at"])
        latest_dt = datetime.fromisoformat(latest["created_at"])
        if datetime.now(timezone.utc) - latest_dt <= ACTIVE_WINDOW:
            return "active"
    return "idle"


def sync_project(name: str, path: str, live_ttys: frozenset[str] = frozenset()) -> None:
    root = Path(path)
    # Clears blockers/questions whose terminal has since closed *before*
    # reading items for this pass -- otherwise db.upsert_item would just
    # overwrite any resolution back to unresolved from the still-open
    # local file on the very next poll.
    project_store.auto_resolve_dead_sessions(root, live_ttys)
    items = project_store.all_items(root)
    for item in items:
        db.upsert_item(
            project=name,
            item_type=item["type"],
            text=item["text"],
            created_at=item["created_at"],
            resolved_at=item["resolved_at"],
            source=item["source"],
            source_id=item["id"],
            terminal_tty=item.get("terminal_tty"),
            session_id=item.get("session_id"),
        )
    status = derive_status(items)
    terminal_tty = project_store.latest_terminal_tty(items)
    last_summary = project_store.latest_summary(items)
    db.upsert_project(
        name, str(root), status=status, terminal_tty=terminal_tty, last_summary=last_summary
    )


def sync_session_state(name: str, live_ttys: frozenset[str], current_project_by_tty: dict[str, str]) -> None:
    """Refreshes tab coloring for this project's genuinely live sessions.

    A tty only counts as live *here* if this project is the one it most
    recently logged to -- otherwise a conversation that `cd`'d away to a
    different tracked project (same tty, still-live `claude` process)
    would leave this project showing an open session forever, since the
    tty itself never dies. current_project_by_tty must be computed after
    every project's items for this pass have already been upserted, or
    it'll judge ownership on stale data."""
    live_for_project = [
        t
        for t in db.get_project_ttys(name)
        if t in live_ttys and current_project_by_tty.get(t) == name
    ]
    terminal_launcher.sync_session_colors(name, live_for_project)


def sync_all() -> int:
    """Runs one aggregation pass over every configured project. Returns
    the number of projects synced."""
    db.init_db()
    projects = config.list_projects()
    live_ttys = process_utils.live_claude_ttys()
    terminal_launcher.prune_colored_ttys(live_ttys)

    synced = []
    for p in projects:
        try:
            sync_project(p["name"], p["path"], live_ttys)
        except FileNotFoundError:
            # project directory moved/deleted -- leave last-known state alone
            continue
        synced.append(p)

    # Computed once, after every project's items are upserted, so
    # ownership reflects this whole pass rather than whichever project
    # happened to be processed first.
    current_project_by_tty = db.current_project_by_tty()
    for p in synced:
        sync_session_state(p["name"], live_ttys, current_project_by_tty)

    return len(projects)


def run_forever(interval_seconds: int | None = None) -> None:
    cfg = config.load_config()
    interval = interval_seconds or cfg.get("poll_interval_seconds", 5)
    while True:
        try:
            sync_all()
        except Exception as exc:
            # This loop is the only thing keeping the dashboard's central
            # db in sync -- an uncaught exception here doesn't just skip
            # one pass, it silently kills the background thread forever,
            # freezing every project's data at whatever it was at the
            # moment of the crash (seen in practice: an unhandled schema
            # mismatch from a stale process took the whole dashboard down
            # mid-session). One bad pass logging and retrying next
            # interval beats that.
            print(f"sync_all() failed, will retry next interval: {exc!r}", file=sys.stderr)
        time.sleep(interval)


if __name__ == "__main__":
    run_forever()
