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


def _now_plus(seconds: int) -> str:
    """An ISO timestamp `seconds` from now -- positive for a session
    that started after the items under test were logged (a reused tty),
    negative for one that was already running."""
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


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


def test_auto_resolve_dead_sessions_clears_flag_left_on_a_reused_tty(tmp_path, monkeypatch):
    # The tty is live again -- but with a *different* session on it, one
    # that started after this flag was logged. The session that raised it
    # is gone and can't answer it, same as if the terminal had closed.
    monkeypatch.setattr(project_store.process_utils, "find_claude_ancestor_tty", lambda: "ttys002")
    item = project_store.add_item(tmp_path, "question", "old session's question")

    changed = project_store.auto_resolve_dead_sessions(
        tmp_path,
        live_ttys={"ttys002"},
        session_started_at={"ttys002": _now_plus(seconds=60)},
    )

    assert changed is True
    resolved = next(i for i in project_store.all_items(tmp_path) if i["id"] == item["id"])
    assert resolved["resolved_at"] is not None


def test_auto_resolve_dead_sessions_clears_flag_from_a_cleared_session(tmp_path, monkeypatch):
    # A `/clear` in a still-open terminal: same tty, same `claude`
    # process (so its start time is unchanged and the tty stays live),
    # but a brand new session_id. The question was asked of a
    # conversation that no longer exists -- nobody can answer it and no
    # reply will ever clear it, so it shouldn't sit on the dashboard
    # forever.
    monkeypatch.setattr(project_store.process_utils, "find_claude_ancestor_tty", lambda: "ttys002")
    monkeypatch.setattr(project_store.process_utils, "current_session_id", lambda: "session-old")
    item = project_store.add_item(tmp_path, "question", "which editor?")
    # The SessionStart hook's marker for the session that replaced it.
    monkeypatch.setattr(project_store.process_utils, "current_session_id", lambda: "session-new")
    project_store.mark_session_start(tmp_path)

    changed = project_store.auto_resolve_dead_sessions(
        tmp_path,
        live_ttys={"ttys002"},
        session_started_at={"ttys002": _now_plus(seconds=-60)},
    )

    assert changed is True
    resolved = next(i for i in project_store.all_items(tmp_path) if i["id"] == item["id"])
    assert resolved["resolved_at"] is not None


def test_auto_resolve_dead_sessions_keeps_flag_when_another_tty_moved_on(tmp_path, monkeypatch):
    # A newer session on a *different* tty says nothing about this one --
    # only being replaced in its own terminal ends a session.
    monkeypatch.setattr(project_store.process_utils, "find_claude_ancestor_tty", lambda: "ttys002")
    monkeypatch.setattr(project_store.process_utils, "current_session_id", lambda: "session-a")
    item = project_store.add_item(tmp_path, "blocker", "still waiting")
    monkeypatch.setattr(project_store.process_utils, "find_claude_ancestor_tty", lambda: "ttys003")
    monkeypatch.setattr(project_store.process_utils, "current_session_id", lambda: "session-b")
    project_store.mark_session_start(tmp_path)

    changed = project_store.auto_resolve_dead_sessions(
        tmp_path,
        live_ttys={"ttys002", "ttys003"},
        session_started_at={"ttys002": _now_plus(seconds=-60), "ttys003": _now_plus(seconds=-60)},
    )

    assert changed is False
    still_open = next(i for i in project_store.all_items(tmp_path) if i["id"] == item["id"])
    assert still_open["resolved_at"] is None


def test_auto_resolve_dead_sessions_keeps_flags_from_the_session_still_running(tmp_path, monkeypatch):
    monkeypatch.setattr(project_store.process_utils, "find_claude_ancestor_tty", lambda: "ttys002")
    item = project_store.add_item(tmp_path, "blocker", "this session's blocker")

    changed = project_store.auto_resolve_dead_sessions(
        tmp_path,
        live_ttys={"ttys002"},
        session_started_at={"ttys002": _now_plus(seconds=-60)},
    )

    assert changed is False
    still_open = next(i for i in project_store.all_items(tmp_path) if i["id"] == item["id"])
    assert still_open["resolved_at"] is None


def test_auto_resolve_dead_sessions_keeps_flags_when_start_time_is_unknown(tmp_path, monkeypatch):
    # No start time for this tty (unparseable `ps` output, say) -- fall
    # back to liveness alone rather than resolving something live.
    monkeypatch.setattr(project_store.process_utils, "find_claude_ancestor_tty", lambda: "ttys002")
    project_store.add_item(tmp_path, "blocker", "still open")

    changed = project_store.auto_resolve_dead_sessions(
        tmp_path, live_ttys={"ttys002"}, session_started_at={"ttys099": _now_plus(seconds=60)}
    )

    assert changed is False


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


def test_stale_flags_awaiting_resolve_finds_this_sessions_unanswered_flag(tmp_path):
    item = project_store.add_item(tmp_path, "question", "which env?")
    items = project_store.all_items(tmp_path)
    items[-1]["session_id"] = "session-1"
    items[-1]["created_at"] = "2026-08-14T10:00:00+00:00"
    project_store._save(tmp_path, items)

    # This turn started after the question was logged -- so the user has
    # replied at least once since, and it should have been resolved.
    stale = project_store.stale_flags_awaiting_resolve(
        tmp_path, "session-1", "2026-08-14T12:00:00+00:00"
    )
    assert [i["id"] for i in stale] == [item["id"]]


def test_stale_flags_awaiting_resolve_ignores_one_logged_this_turn(tmp_path):
    project_store.add_item(tmp_path, "question", "just asked")
    items = project_store.all_items(tmp_path)
    items[-1]["session_id"] = "session-1"
    items[-1]["created_at"] = "2026-08-14T13:00:00+00:00"
    project_store._save(tmp_path, items)

    assert (
        project_store.stale_flags_awaiting_resolve(
            tmp_path, "session-1", "2026-08-14T12:00:00+00:00"
        )
        == []
    )


def test_stale_flags_awaiting_resolve_ignores_resolved_and_other_sessions(tmp_path):
    resolved = project_store.add_item(tmp_path, "question", "already answered")
    project_store.resolve_item(tmp_path, "question", resolved["id"])
    project_store.add_item(tmp_path, "blocker", "another terminal's blocker")
    items = project_store.all_items(tmp_path)
    items[0]["session_id"] = "session-1"
    items[0]["created_at"] = "2026-08-14T10:00:00+00:00"
    items[1]["session_id"] = "session-other"
    items[1]["created_at"] = "2026-08-14T10:00:00+00:00"
    project_store._save(tmp_path, items)

    assert (
        project_store.stale_flags_awaiting_resolve(
            tmp_path, "session-1", "2026-08-14T12:00:00+00:00"
        )
        == []
    )


def test_stale_flags_awaiting_resolve_is_empty_on_a_sessions_first_turn(tmp_path):
    project_store.add_item(tmp_path, "question", "asked")
    items = project_store.all_items(tmp_path)
    items[-1]["session_id"] = "session-1"
    project_store._save(tmp_path, items)

    # No previous turn boundary yet -- nothing can be "from an earlier turn".
    assert project_store.stale_flags_awaiting_resolve(tmp_path, "session-1", None) == []
