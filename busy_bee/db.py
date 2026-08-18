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
  type TEXT NOT NULL CHECK (type IN ('done','todo','blocker','question','summary')),
  text TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL,
  resolved_at TIMESTAMP,
  source TEXT NOT NULL DEFAULT 'agent',
  source_id TEXT,
  terminal_tty TEXT,
  UNIQUE(project, source_id)
);

CREATE TABLE IF NOT EXISTS projects (
  name TEXT PRIMARY KEY,
  path TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'idle',
  last_seen_at TIMESTAMP,
  terminal_tty TEXT,
  last_summary TEXT
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


def _migrate(conn: sqlite3.Connection) -> None:
    """Adds columns to tables that already existed before this column
    was introduced -- CREATE TABLE IF NOT EXISTS is a no-op against a
    table that's already there."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(projects)")}
    if "terminal_tty" not in columns:
        conn.execute("ALTER TABLE projects ADD COLUMN terminal_tty TEXT")
    if "last_summary" not in columns:
        conn.execute("ALTER TABLE projects ADD COLUMN last_summary TEXT")

    # SQLite can't ALTER a CHECK constraint in place -- rebuild items
    # if the table predates 'summary' being a valid type, preserving
    # every row.
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='items'").fetchone()
    if row is not None and "'summary'" not in row["sql"]:
        conn.execute("ALTER TABLE items RENAME TO items_old")
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO items (id, project, type, text, created_at, resolved_at, source, source_id) "
            "SELECT id, project, type, text, created_at, resolved_at, source, source_id FROM items_old"
        )
        conn.execute("DROP TABLE items_old")

    item_columns = {row["name"] for row in conn.execute("PRAGMA table_info(items)")}
    if "terminal_tty" not in item_columns:
        conn.execute("ALTER TABLE items ADD COLUMN terminal_tty TEXT")


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def upsert_project(
    name: str,
    path: str,
    status: str | None = None,
    terminal_tty: str | None = None,
    last_summary: str | None = None,
) -> None:
    with connect() as conn:
        row = conn.execute("SELECT status FROM projects WHERE name = ?", (name,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO projects (name, path, status, last_seen_at, terminal_tty, last_summary) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    name,
                    path,
                    status or "idle",
                    datetime.now(timezone.utc).isoformat(),
                    terminal_tty,
                    last_summary,
                ),
            )
        else:
            conn.execute(
                "UPDATE projects SET path = ?, status = COALESCE(?, status), last_seen_at = ?, "
                "terminal_tty = COALESCE(?, terminal_tty), last_summary = COALESCE(?, last_summary) "
                "WHERE name = ?",
                (
                    path,
                    status,
                    datetime.now(timezone.utc).isoformat(),
                    terminal_tty,
                    last_summary,
                    name,
                ),
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
    terminal_tty: str | None = None,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO items (project, type, text, created_at, resolved_at, source, source_id, terminal_tty)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project, source_id) DO UPDATE SET
                text = excluded.text,
                resolved_at = excluded.resolved_at,
                terminal_tty = excluded.terminal_tty
            """,
            (project, item_type, text, created_at, resolved_at, source, source_id, terminal_tty),
        )


def get_projects() -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute("SELECT * FROM projects ORDER BY name").fetchall()


def get_project(name: str) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()


def get_recent_done(project: str, limit: int = 3, terminal_tty: str | None = None) -> list[sqlite3.Row]:
    with connect() as conn:
        if terminal_tty is not None:
            return conn.execute(
                "SELECT * FROM items WHERE project = ? AND type = 'done' AND terminal_tty = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (project, terminal_tty, limit),
            ).fetchall()
        return conn.execute(
            "SELECT * FROM items WHERE project = ? AND type = 'done' "
            "ORDER BY created_at DESC LIMIT ?",
            (project, limit),
        ).fetchall()


def get_next_todo(project: str, limit: int = 3, terminal_tty: str | None = None) -> list[sqlite3.Row]:
    """The most recently logged unresolved todos -- i.e. whatever was
    most immediately planned, not the oldest backlog items."""
    with connect() as conn:
        if terminal_tty is not None:
            return conn.execute(
                "SELECT * FROM items WHERE project = ? AND type = 'todo' AND resolved_at IS NULL "
                "AND terminal_tty = ? ORDER BY created_at DESC LIMIT ?",
                (project, terminal_tty, limit),
            ).fetchall()
        return conn.execute(
            "SELECT * FROM items WHERE project = ? AND type = 'todo' AND resolved_at IS NULL "
            "ORDER BY created_at DESC LIMIT ?",
            (project, limit),
        ).fetchall()


def get_project_ttys(project: str) -> list[str]:
    """Every tty that has ever logged an item for this project, most
    recently active first -- callers intersect this with currently-live
    ttys to find sessions that are still actually open."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT terminal_tty FROM items WHERE project = ? AND terminal_tty IS NOT NULL "
            "GROUP BY terminal_tty ORDER BY MAX(created_at) DESC",
            (project,),
        ).fetchall()
        return [r["terminal_tty"] for r in rows]


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
