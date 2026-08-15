"""Aggregator: scans configured project paths, reads each project's
local status.json, and merges it into the central SQLite store.

Runs on a simple poll interval -- simplest thing that works reliably,
per the PRD ("whichever is simpler to build"). A project's status is
derived, not stored by the agent: 'blocked' if it has any unresolved
blocker, 'active' if something was logged recently, else 'idle'.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from busy_bee import config, db, project_store

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


def sync_project(name: str, path: str) -> None:
    root = Path(path)
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
        )
    status = derive_status(items)
    terminal_tty = project_store.latest_terminal_tty(items)
    db.upsert_project(name, str(root), status=status, terminal_tty=terminal_tty)


def sync_all() -> int:
    """Runs one aggregation pass over every configured project. Returns
    the number of projects synced."""
    db.init_db()
    projects = config.list_projects()
    for p in projects:
        try:
            sync_project(p["name"], p["path"])
        except FileNotFoundError:
            # project directory moved/deleted -- leave last-known state alone
            continue
    return len(projects)


def run_forever(interval_seconds: int | None = None) -> None:
    cfg = config.load_config()
    interval = interval_seconds or cfg.get("poll_interval_seconds", 5)
    while True:
        sync_all()
        time.sleep(interval)


if __name__ == "__main__":
    run_forever()
