import pytest

from busy_bee import config, db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "db.sqlite")
    db.init_db()
    yield


def test_upsert_item_is_idempotent_by_source_id():
    db.upsert_item(
        project="p1",
        item_type="done",
        text="first version",
        created_at="2026-08-14T10:00:00+00:00",
        resolved_at=None,
        source="agent",
        source_id="abc123",
    )
    db.upsert_item(
        project="p1",
        item_type="done",
        text="edited version",
        created_at="2026-08-14T10:00:00+00:00",
        resolved_at=None,
        source="agent",
        source_id="abc123",
    )
    rows = db.get_recent_done("p1")
    assert len(rows) == 1
    assert rows[0]["text"] == "edited version"


def test_get_recent_done_limits_and_orders():
    for i in range(5):
        db.upsert_item(
            project="p1",
            item_type="done",
            text=f"item {i}",
            created_at=f"2026-08-14T{10 + i:02d}:00:00+00:00",
            resolved_at=None,
            source="agent",
            source_id=f"id{i}",
        )
    rows = db.get_recent_done("p1", limit=3)
    assert [r["text"] for r in rows] == ["item 4", "item 3", "item 2"]


def test_get_next_todo_shows_most_recently_planned():
    for i in range(5):
        db.upsert_item(
            project="p1",
            item_type="todo",
            text=f"todo {i}",
            created_at=f"2026-08-14T{10 + i:02d}:00:00+00:00",
            resolved_at=None,
            source="agent",
            source_id=f"todo-id{i}",
        )
    rows = db.get_next_todo("p1", limit=3)
    assert [r["text"] for r in rows] == ["todo 4", "todo 3", "todo 2"]


def test_get_unresolved_excludes_resolved():
    db.upsert_item("p1", "blocker", "stuck", "2026-08-14T10:00:00+00:00", None, "agent", "b1")
    db.upsert_item(
        "p1", "blocker", "also stuck", "2026-08-14T10:01:00+00:00", "2026-08-14T10:02:00+00:00",
        "agent", "b2",
    )
    rows = db.get_unresolved("p1", "blocker")
    assert len(rows) == 1
    assert rows[0]["text"] == "stuck"


def test_count_all_unresolved_blockers_and_questions():
    db.upsert_item("p1", "blocker", "b", "2026-08-14T10:00:00+00:00", None, "agent", "id1")
    db.upsert_item("p2", "question", "q", "2026-08-14T10:00:00+00:00", None, "agent", "id2")
    db.upsert_item("p2", "done", "d", "2026-08-14T10:00:00+00:00", None, "agent", "id3")
    assert db.count_all_unresolved_blockers_and_questions() == 2


def test_upsert_project_preserves_status_when_none_passed():
    db.upsert_project("p1", "/tmp/p1", status="blocked")
    db.upsert_project("p1", "/tmp/p1")
    project = db.get_project("p1")
    assert project["status"] == "blocked"


def test_upsert_project_sets_and_preserves_last_summary():
    db.upsert_project("p1", "/tmp/p1", last_summary="first summary")
    project = db.get_project("p1")
    assert project["last_summary"] == "first summary"

    db.upsert_project("p1", "/tmp/p1")  # no summary passed -- should keep it
    project = db.get_project("p1")
    assert project["last_summary"] == "first summary"

    db.upsert_project("p1", "/tmp/p1", last_summary="updated summary")
    project = db.get_project("p1")
    assert project["last_summary"] == "updated summary"


def test_items_accept_summary_type():
    db.upsert_item("p1", "summary", "where things stand", "2026-08-14T10:00:00+00:00", None, "agent", "s1")
    # would raise sqlite3.IntegrityError against the old CHECK constraint if migration failed
    rows = db.get_unresolved("p1", "summary")
    assert [r["text"] for r in rows] == ["where things stand"]


def test_migrate_rebuilds_items_table_preserving_rows_and_allowing_summary(tmp_path, monkeypatch):
    import sqlite3

    old_db_path = tmp_path / "old.sqlite"
    monkeypatch.setattr(config, "DB_PATH", old_db_path)

    # Simulate a pre-'summary' database (old CHECK constraint, no
    # last_summary column) to prove the migration handles real
    # upgrades, not just fresh installs.
    conn = sqlite3.connect(old_db_path)
    conn.executescript(
        """
        CREATE TABLE items (
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
        CREATE TABLE projects (
          name TEXT PRIMARY KEY,
          path TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'idle',
          last_seen_at TIMESTAMP,
          terminal_tty TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO items (project, type, text, created_at, source, source_id) "
        "VALUES ('p1', 'done', 'pre-migration item', '2026-08-14T10:00:00+00:00', 'agent', 'old1')"
    )
    conn.commit()
    conn.close()

    db.init_db()

    rows = db.get_recent_done("p1")
    assert [r["text"] for r in rows] == ["pre-migration item"]

    db.upsert_item("p1", "summary", "now works", "2026-08-14T11:00:00+00:00", None, "agent", "new1")
    assert [r["text"] for r in db.get_unresolved("p1", "summary")] == ["now works"]


def test_migrate_adds_terminal_tty_to_preexisting_items_table(tmp_path, monkeypatch):
    import sqlite3

    old_db_path = tmp_path / "old.sqlite"
    monkeypatch.setattr(config, "DB_PATH", old_db_path)

    # A DB from after 'summary' was added but before terminal_tty
    # existed on items -- the CHECK-constraint rebuild path above won't
    # fire, so this exercises the separate ALTER TABLE ADD COLUMN path.
    conn = sqlite3.connect(old_db_path)
    conn.executescript(
        """
        CREATE TABLE items (
          id INTEGER PRIMARY KEY,
          project TEXT NOT NULL,
          type TEXT NOT NULL CHECK (type IN ('done','todo','blocker','question','summary')),
          text TEXT NOT NULL,
          created_at TIMESTAMP NOT NULL,
          resolved_at TIMESTAMP,
          source TEXT NOT NULL DEFAULT 'agent',
          source_id TEXT,
          UNIQUE(project, source_id)
        );
        CREATE TABLE projects (
          name TEXT PRIMARY KEY,
          path TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'idle',
          last_seen_at TIMESTAMP,
          terminal_tty TEXT,
          last_summary TEXT
        );
        """
    )
    conn.commit()
    conn.close()

    db.init_db()

    db.upsert_item(
        "p1", "done", "with tty", "2026-08-14T11:00:00+00:00", None, "agent", "t1",
        terminal_tty="ttys002",
    )
    assert db.get_project_ttys("p1") == ["ttys002"]


def test_upsert_item_persists_terminal_tty():
    db.upsert_item(
        project="p1",
        item_type="done",
        text="did a thing",
        created_at="2026-08-14T10:00:00+00:00",
        resolved_at=None,
        source="agent",
        source_id="a1",
        terminal_tty="ttys002",
    )
    rows = db.get_recent_done("p1")
    assert rows[0]["terminal_tty"] == "ttys002"


def test_get_recent_done_and_next_todo_filter_by_terminal_tty():
    db.upsert_item("p1", "done", "session A done", "2026-08-14T10:00:00+00:00", None, "agent", "a1", terminal_tty="ttys001")
    db.upsert_item("p1", "done", "session B done", "2026-08-14T10:01:00+00:00", None, "agent", "b1", terminal_tty="ttys002")
    db.upsert_item("p1", "todo", "session A todo", "2026-08-14T10:02:00+00:00", None, "agent", "a2", terminal_tty="ttys001")
    db.upsert_item("p1", "todo", "session B todo", "2026-08-14T10:03:00+00:00", None, "agent", "b2", terminal_tty="ttys002")

    assert [r["text"] for r in db.get_recent_done("p1", terminal_tty="ttys001")] == ["session A done"]
    assert [r["text"] for r in db.get_next_todo("p1", terminal_tty="ttys002")] == ["session B todo"]


def test_get_project_ttys_orders_by_most_recent_activity():
    db.upsert_item("p1", "done", "old", "2026-08-14T10:00:00+00:00", None, "agent", "a1", terminal_tty="ttys001")
    db.upsert_item("p1", "done", "new", "2026-08-14T10:05:00+00:00", None, "agent", "b1", terminal_tty="ttys002")
    db.upsert_item("p1", "done", "older still", "2026-08-14T09:00:00+00:00", None, "agent", "a2", terminal_tty="ttys001")

    assert db.get_project_ttys("p1") == ["ttys002", "ttys001"]


def test_get_project_ttys_ignores_items_without_a_tty():
    db.upsert_item("p1", "done", "no tty", "2026-08-14T10:00:00+00:00", None, "agent", "a1")
    assert db.get_project_ttys("p1") == []


def test_get_latest_summary_for_tty_returns_most_recent():
    db.upsert_item("p1", "summary", "first pass done", "2026-08-14T10:00:00+00:00", None, "agent", "s1", terminal_tty="ttys001")
    db.upsert_item("p1", "summary", "wrapping up now", "2026-08-14T10:05:00+00:00", None, "agent", "s2", terminal_tty="ttys001")
    db.upsert_item("p1", "summary", "unrelated session", "2026-08-14T10:06:00+00:00", None, "agent", "s3", terminal_tty="ttys002")

    assert db.get_latest_summary_for_tty("p1", "ttys001") == "wrapping up now"


def test_get_latest_summary_for_tty_none_when_unlogged():
    assert db.get_latest_summary_for_tty("p1", "ttys001") is None
