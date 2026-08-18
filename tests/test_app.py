import pytest

from busy_bee import app, config, db, process_utils


class FakeResult:
    def __init__(self, stdout=""):
        self.stdout = stdout


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "cfg" / "db.sqlite")
    db.init_db()
    yield


def _log(project, item_type, text, tty, created_at, session_id=None, source_id=None):
    db.upsert_item(
        project=project,
        item_type=item_type,
        text=text,
        created_at=created_at,
        resolved_at=None,
        source="agent",
        source_id=source_id,
        terminal_tty=tty,
        session_id=session_id,
    )


def test_get_projects_skips_project_with_no_live_session(monkeypatch):
    db.upsert_project("stray-proj", "/tmp/stray-proj")
    _log("stray-proj", "done", "did a thing", "ttys009", "2026-08-15T00:00:00+00:00")

    # No `claude` process reported as running anywhere.
    monkeypatch.setattr(process_utils.subprocess, "run", lambda cmd, **k: FakeResult(stdout=""))

    api = app.Api()
    assert api.get_projects() == []


def test_get_projects_includes_project_with_live_session(monkeypatch):
    db.upsert_project("live-proj", "/tmp/live-proj")
    _log("live-proj", "done", "shipped it", "ttys009", "2026-08-15T00:00:00+00:00")

    monkeypatch.setattr(
        process_utils.subprocess, "run", lambda cmd, **k: FakeResult(stdout="ttys009 claude\n")
    )
    monkeypatch.setattr(app.terminal_launcher, "session_title_for_tty", lambda tty: None)

    api = app.Api()
    projects = api.get_projects()

    assert len(projects) == 1
    assert projects[0]["name"] == "live-proj"
    assert len(projects[0]["sessions"]) == 1
    assert projects[0]["sessions"][0]["tty"] == "ttys009"
    assert projects[0]["sessions"][0]["done"] == ["shipped it"]


def test_get_projects_does_not_leak_old_sessions_history_into_reused_tty(monkeypatch):
    # Regression test: an old, unrelated `claude` session logged done/todo
    # items from ttys009, then quit. A brand new session (different
    # session_id) started later in that same terminal window -- its
    # session card must only show its own history, not the old session's.
    db.upsert_project("proj", "/tmp/proj")
    _log(
        "proj", "done", "old session's work", "ttys009", "2026-08-15T00:00:00+00:00",
        session_id="session-old", source_id="a1",
    )
    _log(
        "proj", "todo", "old session's todo", "ttys009", "2026-08-15T00:01:00+00:00",
        session_id="session-old", source_id="a2",
    )
    _log(
        "proj", "done", "new session's work", "ttys009", "2026-08-15T01:00:00+00:00",
        session_id="session-new", source_id="b1",
    )

    monkeypatch.setattr(
        process_utils.subprocess, "run", lambda cmd, **k: FakeResult(stdout="ttys009 claude\n")
    )
    monkeypatch.setattr(app.terminal_launcher, "session_title_for_tty", lambda tty: None)

    api = app.Api()
    projects = api.get_projects()

    assert len(projects) == 1
    session = projects[0]["sessions"][0]
    assert session["done"] == ["new session's work"]
    assert session["todo"] == []


def test_get_projects_drops_project_once_its_only_session_closes(monkeypatch):
    db.upsert_project("closing-proj", "/tmp/closing-proj")
    _log("closing-proj", "done", "wrapped up", "ttys009", "2026-08-15T00:00:00+00:00")
    monkeypatch.setattr(app.terminal_launcher, "session_title_for_tty", lambda tty: None)

    api = app.Api()

    monkeypatch.setattr(
        process_utils.subprocess, "run", lambda cmd, **k: FakeResult(stdout="ttys009 claude\n")
    )
    assert len(api.get_projects()) == 1

    # Terminal closes -- the underlying claude process is gone.
    monkeypatch.setattr(process_utils.subprocess, "run", lambda cmd, **k: FakeResult(stdout=""))
    assert api.get_projects() == []

    # The history isn't lost -- it's still in the db, just not shown.
    assert db.get_project("closing-proj") is not None
