from datetime import datetime, timedelta, timezone

import pytest

from busy_bee import project_store


@pytest.fixture(autouse=True)
def no_real_tty_lookup(monkeypatch):
    # add_item shells out to `ps` via process_utils to find the calling
    # terminal's tty, and reads CLAUDE_CODE_SESSION_ID from the
    # environment; stub both so tests are deterministic and fast
    # regardless of what's actually running this test process.
    monkeypatch.setattr(project_store.process_utils, "find_claude_ancestor_tty", lambda: None)
    monkeypatch.setattr(project_store.process_utils, "current_session_id", lambda: None)
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


def test_auto_resolve_dead_sessions_clears_blocker_from_closed_tty(tmp_path, monkeypatch):
    monkeypatch.setattr(project_store.process_utils, "find_claude_ancestor_tty", lambda: "ttys002")
    item = project_store.add_item(tmp_path, "blocker", "need API key")

    changed = project_store.auto_resolve_dead_sessions(tmp_path, live_ttys=set())

    assert changed is True
    resolved = next(i for i in project_store.all_items(tmp_path) if i["id"] == item["id"])
    assert resolved["resolved_at"] is not None


def test_auto_resolve_dead_sessions_leaves_live_tty_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(project_store.process_utils, "find_claude_ancestor_tty", lambda: "ttys002")
    item = project_store.add_item(tmp_path, "question", "which API key?")

    changed = project_store.auto_resolve_dead_sessions(tmp_path, live_ttys={"ttys002"})

    assert changed is False
    still_open = next(i for i in project_store.all_items(tmp_path) if i["id"] == item["id"])
    assert still_open["resolved_at"] is None


def test_auto_resolve_dead_sessions_ignores_items_without_tty(tmp_path):
    item = project_store.add_item(tmp_path, "blocker", "no tty recorded")

    changed = project_store.auto_resolve_dead_sessions(tmp_path, live_ttys=set())

    assert changed is False
    still_open = next(i for i in project_store.all_items(tmp_path) if i["id"] == item["id"])
    assert still_open["resolved_at"] is None


def test_auto_resolve_dead_sessions_ignores_done_and_todo(tmp_path, monkeypatch):
    monkeypatch.setattr(project_store.process_utils, "find_claude_ancestor_tty", lambda: "ttys002")
    project_store.add_item(tmp_path, "done", "shipped it")
    project_store.add_item(tmp_path, "todo", "write tests")

    changed = project_store.auto_resolve_dead_sessions(tmp_path, live_ttys=set())

    assert changed is False
    assert all(i["resolved_at"] is None for i in project_store.all_items(tmp_path))


def test_resolve_item_marks_resolved(tmp_path):
    item = project_store.add_item(tmp_path, "blocker", "waiting on API key")
    assert project_store.resolve_item(tmp_path, "blocker", item["id"]) is True

    items = project_store.all_items(tmp_path)
    resolved = next(i for i in items if i["id"] == item["id"])
    assert resolved["resolved_at"] is not None


def test_resolve_unknown_item_returns_false(tmp_path):
    assert project_store.resolve_item(tmp_path, "blocker", "does-not-exist") is False


def test_resolve_rejects_done_or_summary(tmp_path):
    item = project_store.add_item(tmp_path, "done", "x")
    try:
        project_store.resolve_item(tmp_path, "done", item["id"])
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_resolve_accepts_todo(tmp_path):
    item = project_store.add_item(tmp_path, "todo", "write tests")
    assert project_store.resolve_item(tmp_path, "todo", item["id"]) is True

    items = project_store.all_items(tmp_path)
    resolved = next(i for i in items if i["id"] == item["id"])
    assert resolved["resolved_at"] is not None


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


def test_add_item_records_session_id(tmp_path, monkeypatch):
    monkeypatch.setattr(project_store.process_utils, "current_session_id", lambda: "session-abc")
    item = project_store.add_item(tmp_path, "done", "x")
    assert item["session_id"] == "session-abc"


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


def test_has_logged_this_turn_filters_by_item_type(tmp_path):
    project_store.add_item(tmp_path, "done", "shipped it")
    assert project_store.has_logged_this_turn(tmp_path, item_type="summary") is False
    project_store.add_item(tmp_path, "summary", "where things stand")
    assert project_store.has_logged_this_turn(tmp_path, item_type="summary") is True


def test_bump_turn_count_increments_per_session(tmp_path):
    count, previous = project_store.bump_turn_count(tmp_path, "session-1")
    assert (count, previous) == (1, None)
    count, previous = project_store.bump_turn_count(tmp_path, "session-1")
    assert count == 2
    assert previous is not None  # timestamp of the first bump
    count, _ = project_store.bump_turn_count(tmp_path, "session-1")
    assert count == 3


def test_bump_turn_count_tracks_sessions_independently(tmp_path):
    # Same tty, two unrelated sessions (e.g. one quit and a new `claude`
    # started in the same terminal window) -- their turn counts must
    # not bleed into each other.
    count, previous = project_store.bump_turn_count(tmp_path, "session-1")
    assert (count, previous) == (1, None)
    count, previous = project_store.bump_turn_count(tmp_path, "session-2")
    assert (count, previous) == (1, None)  # independent of session-1's count
    count, _ = project_store.bump_turn_count(tmp_path, "session-1")
    assert count == 2


def test_summary_logged_since_none_means_any_summary_counts(tmp_path):
    assert project_store.summary_logged_since(tmp_path, "session-1", None) is False
    project_store.add_item(tmp_path, "summary", "where things stand")
    # add_item doesn't set session_id here (no live claude session in tests),
    # so tag it directly to simulate a real dashctl call from session-1.
    items = project_store.all_items(tmp_path)
    items[-1]["session_id"] = "session-1"
    project_store._save(tmp_path, items)
    assert project_store.summary_logged_since(tmp_path, "session-1", None) is True


def test_summary_logged_since_requires_newer_than_boundary(tmp_path):
    project_store.add_item(tmp_path, "summary", "old summary")
    items = project_store.all_items(tmp_path)
    items[-1]["session_id"] = "session-1"
    boundary = "2026-08-14T12:00:00+00:00"
    items[-1]["created_at"] = "2026-08-14T10:00:00+00:00"  # before the boundary
    project_store._save(tmp_path, items)

    assert project_store.summary_logged_since(tmp_path, "session-1", boundary) is False


def test_summary_logged_since_ignores_other_sessions(tmp_path):
    # Includes the case that matters most: a previous, unrelated session
    # that happened to share this terminal's tty must not satisfy the
    # new session's summary requirement.
    project_store.add_item(tmp_path, "summary", "someone else's summary")
    items = project_store.all_items(tmp_path)
    items[-1]["session_id"] = "session-old"
    project_store._save(tmp_path, items)


def test_mark_session_start_logs_a_session_start_item(tmp_path, monkeypatch):
    monkeypatch.setattr(project_store.process_utils, "find_claude_ancestor_tty", lambda: "ttys002")
    monkeypatch.setattr(project_store.process_utils, "current_session_id", lambda: "session-new")

    item = project_store.mark_session_start(tmp_path)

    assert item["type"] == "session_start"
    assert item["terminal_tty"] == "ttys002"
    assert item["session_id"] == "session-new"

    items = project_store.all_items(tmp_path)
    assert len(items) == 1
    assert items[0]["type"] == "session_start"

    assert project_store.summary_logged_since(tmp_path, "session-1", None) is False
