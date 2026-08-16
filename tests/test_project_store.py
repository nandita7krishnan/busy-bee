from datetime import datetime, timedelta, timezone

import pytest

from busy_bee import project_store


@pytest.fixture(autouse=True)
def no_real_tty_lookup(monkeypatch):
    # add_item shells out to `ps` via process_utils to find the calling
    # terminal's tty; stub it so tests are deterministic and fast
    # regardless of what's actually running this test process.
    monkeypatch.setattr(project_store.process_utils, "find_claude_ancestor_tty", lambda: None)
    yield


def test_add_item_creates_status_file(tmp_path):
    item = project_store.add_item(tmp_path, "done", "shipped the thing")
    assert item["type"] == "done"
    assert item["text"] == "shipped the thing"
    assert item["resolved_at"] is None

    items = project_store.all_items(tmp_path)
    assert len(items) == 1
    assert items[0]["id"] == item["id"]


def test_add_item_rejects_invalid_type(tmp_path):
    try:
        project_store.add_item(tmp_path, "nope", "text")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_resolve_item_marks_resolved(tmp_path):
    item = project_store.add_item(tmp_path, "blocker", "waiting on API key")
    assert project_store.resolve_item(tmp_path, "blocker", item["id"]) is True

    items = project_store.all_items(tmp_path)
    resolved = next(i for i in items if i["id"] == item["id"])
    assert resolved["resolved_at"] is not None


def test_resolve_unknown_item_returns_false(tmp_path):
    assert project_store.resolve_item(tmp_path, "blocker", "does-not-exist") is False


def test_resolve_rejects_done_or_todo(tmp_path):
    item = project_store.add_item(tmp_path, "done", "x")
    try:
        project_store.resolve_item(tmp_path, "done", item["id"])
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_has_logged_this_turn(tmp_path):
    assert project_store.has_logged_this_turn(tmp_path) is False
    project_store.add_item(tmp_path, "done", "just now")
    assert project_store.has_logged_this_turn(tmp_path, since_seconds=120) is True


def test_has_logged_this_turn_respects_window(tmp_path, monkeypatch):
    item = project_store.add_item(tmp_path, "done", "a while ago")
    items = project_store.all_items(tmp_path)
    stale_time = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    items[0]["created_at"] = stale_time
    project_store._save(tmp_path, items)

    assert project_store.has_logged_this_turn(tmp_path, since_seconds=120) is False


def test_add_item_records_terminal_tty(tmp_path, monkeypatch):
    monkeypatch.setattr(project_store.process_utils, "find_claude_ancestor_tty", lambda: "ttys002")
    item = project_store.add_item(tmp_path, "done", "x")
    assert item["terminal_tty"] == "ttys002"


def test_latest_terminal_tty_picks_most_recent():
    items = [
        {"created_at": "2026-08-14T10:00:00+00:00", "terminal_tty": "ttys000"},
        {"created_at": "2026-08-14T11:00:00+00:00", "terminal_tty": "ttys002"},
        {"created_at": "2026-08-14T09:00:00+00:00", "terminal_tty": None},
    ]
    assert project_store.latest_terminal_tty(items) == "ttys002"


def test_latest_terminal_tty_returns_none_when_none_recorded():
    items = [{"created_at": "2026-08-14T10:00:00+00:00", "terminal_tty": None}]
    assert project_store.latest_terminal_tty(items) is None


def test_add_item_accepts_summary_type(tmp_path):
    item = project_store.add_item(tmp_path, "summary", "shipped the login flow")
    assert item["type"] == "summary"


def test_latest_summary_picks_most_recent():
    items = [
        {"type": "summary", "created_at": "2026-08-14T10:00:00+00:00", "text": "old summary"},
        {"type": "done", "created_at": "2026-08-14T11:00:00+00:00", "text": "not a summary"},
        {"type": "summary", "created_at": "2026-08-14T12:00:00+00:00", "text": "new summary"},
    ]
    assert project_store.latest_summary(items) == "new summary"


def test_latest_summary_returns_none_when_absent():
    items = [{"type": "done", "created_at": "2026-08-14T10:00:00+00:00", "text": "x"}]
    assert project_store.latest_summary(items) is None
