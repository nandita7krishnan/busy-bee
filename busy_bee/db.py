"""Central SQLite store -- single source of truth for the dashboard UI.

Schema matches the PRD, plus a `source_id` column on items so the
aggregator can merge idempotently (upsert by project+source_id instead
of re-inserting the same item every poll), and `last_seen_at` on
projects so the UI/aggregator can judge staleness.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from busy_bee import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY,
  project TEXT NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('done','todo','blocker','question')),
  text TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL,
  resolved_at TIMESTAMP,
  source TEXT NOT NULL DEFAULT 'agent',
  source_id TEXT,
  UNIQUE(project, source_id)
);

CREATE TABLE IF NOT EXISTS projects (
  name TEXT PRIMARY KEY,
  path TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'idle',
  last_seen_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_items_project_type ON items(project, type);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def upsert_project(name: str, path: str, status: str | None = None) -> None:
    with connect() as conn:
        row = conn.execute("SELECT status FROM projects WHERE name = ?", (name,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO projects (name, path, status, last_seen_at) VALUES (?, ?, ?, ?)",
                (name, path, status or "idle", datetime.now(timezone.utc).isoformat()),
            )
        else:
            conn.execute(
                "UPDATE projects SET path = ?, status = COALESCE(?, status), last_seen_at = ? "
                "WHERE name = ?",
                (path, status, datetime.now(timezone.utc).isoformat(), name),
            )


def set_project_status(name: str, status: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE projects SET status = ? WHERE name = ?", (status, name))


def upsert_item(
    project: str,
    item_type: str,
    text: str,
    created_at: str,
    resolved_at: str | None,
    source: str,
    source_id: str | None,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO items (project, type, text, created_at, resolved_at, source, source_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project, source_id) DO UPDATE SET
                text = excluded.text,
                resolved_at = excluded.resolved_at
            """,
            (project, item_type, text, created_at, resolved_at, source, source_id),
        )


def add_manual_item(project: str, item_type: str, text: str) -> int:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO items (project, type, text, created_at, resolved_at, source, source_id)
            VALUES (?, ?, ?, ?, NULL, 'manual', NULL)
            """,
            (project, item_type, text, datetime.now(timezone.utc).isoformat()),
        )
        return cur.lastrowid


def resolve_item_by_id(item_id: int) -> bool:
    with connect() as conn:
        cur = conn.execute(
            "UPDATE items SET resolved_at = ? WHERE id = ? AND resolved_at IS NULL",
            (datetime.now(timezone.utc).isoformat(), item_id),
        )
        return cur.rowcount > 0


def get_projects() -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute("SELECT * FROM projects ORDER BY name").fetchall()


def get_project(name: str) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()


def get_recent_done(project: str, limit: int = 3) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM items WHERE project = ? AND type = 'done' "
            "ORDER BY created_at DESC LIMIT ?",
            (project, limit),
        ).fetchall()


def get_next_todo(project: str, limit: int = 3) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM items WHERE project = ? AND type = 'todo' AND resolved_at IS NULL "
            "ORDER BY created_at ASC LIMIT ?",
            (project, limit),
        ).fetchall()


def get_unresolved(project: str, item_type: str) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM items WHERE project = ? AND type = ? AND resolved_at IS NULL "
            "ORDER BY created_at ASC",
            (project, item_type),
        ).fetchall()


def count_all_unresolved_blockers_and_questions() -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM items "
            "WHERE type IN ('blocker', 'question') AND resolved_at IS NULL"
        ).fetchone()
        return row["c"]
