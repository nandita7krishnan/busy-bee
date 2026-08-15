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


def test_resolve_item_by_id():
    item_id = db.add_manual_item("p1", "blocker", "manual blocker")
    assert db.resolve_item_by_id(item_id) is True
    rows = db.get_unresolved("p1", "blocker")
    assert rows == []
    # resolving again is a no-op, not an error
    assert db.resolve_item_by_id(item_id) is False


def test_count_all_unresolved_blockers_and_questions():
    db.add_manual_item("p1", "blocker", "b")
    db.add_manual_item("p2", "question", "q")
    db.add_manual_item("p2", "done", "d")
    assert db.count_all_unresolved_blockers_and_questions() == 2


def test_upsert_project_preserves_status_when_none_passed():
    db.upsert_project("p1", "/tmp/p1", status="blocked")
    db.upsert_project("p1", "/tmp/p1")
    project = db.get_project("p1")
    assert project["status"] == "blocked"
