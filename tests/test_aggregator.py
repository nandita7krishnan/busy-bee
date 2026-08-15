from datetime import datetime, timedelta, timezone

import pytest

from busy_bee import aggregator, config, db, project_store


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "db.sqlite")
    monkeypatch.setattr(project_store.process_utils, "find_claude_ancestor_tty", lambda: None)
    db.init_db()
    yield


def test_derive_status_blocked_wins():
    items = [
        {"type": "blocker", "resolved_at": None, "created_at": "2026-08-14T10:00:00+00:00"},
        {"type": "done", "resolved_at": None, "created_at": "2026-08-14T10:00:00+00:00"},
    ]
    assert aggregator.derive_status(items) == "blocked"


def test_derive_status_active_when_recent():
    now = datetime.now(timezone.utc).isoformat()
    items = [{"type": "done", "resolved_at": None, "created_at": now}]
    assert aggregator.derive_status(items) == "active"


def test_derive_status_idle_when_stale():
    stale = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    items = [{"type": "done", "resolved_at": None, "created_at": stale}]
    assert aggregator.derive_status(items) == "idle"


def test_derive_status_idle_when_empty():
    assert aggregator.derive_status([]) == "idle"


def test_derive_status_ignores_resolved_blocker():
    now = datetime.now(timezone.utc).isoformat()
    items = [
        {"type": "blocker", "resolved_at": now, "created_at": now},
        {"type": "done", "resolved_at": None, "created_at": now},
    ]
    assert aggregator.derive_status(items) == "active"


def test_sync_project_merges_items_and_status(tmp_path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    project_store.add_item(project_dir, "done", "shipped feature")
    project_store.add_item(project_dir, "blocker", "need API key")

    aggregator.sync_project("proj", str(project_dir))

    project = db.get_project("proj")
    assert project["status"] == "blocked"
    done_rows = db.get_recent_done("proj")
    assert [r["text"] for r in done_rows] == ["shipped feature"]
    blockers = db.get_unresolved("proj", "blocker")
    assert [b["text"] for b in blockers] == ["need API key"]


def test_sync_project_propagates_terminal_tty(tmp_path, monkeypatch):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    monkeypatch.setattr(project_store.process_utils, "find_claude_ancestor_tty", lambda: "ttys002")
    project_store.add_item(project_dir, "done", "did a thing")

    aggregator.sync_project("proj", str(project_dir))

    project = db.get_project("proj")
    assert project["terminal_tty"] == "ttys002"


def test_sync_all_uses_config(tmp_path, monkeypatch):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    project_store.add_item(project_dir, "todo", "write tests")

    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "HOME_DIR", tmp_path)
    config.add_project("proj", str(project_dir))

    synced = aggregator.sync_all()
    assert synced == 1
    todos = db.get_next_todo("proj")
    assert [t["text"] for t in todos] == ["write tests"]
