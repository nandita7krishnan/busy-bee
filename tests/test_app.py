from datetime import datetime, timedelta, timezone

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


def _fake_ps(live="", elapsed=""):
    """Stands in for both `ps` calls process_utils makes -- the plain
    tty/comm listing and the tty/etime/comm one -- picked apart by the
    format argument, since a single lambda would otherwise answer both
    with the same columns."""

    def run(cmd, **kwargs):
        return FakeResult(stdout=elapsed if "etime" in " ".join(cmd) else live)

    return run


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


def test_get_projects_nests_orphaned_flag_under_its_own_project_card(monkeypatch):
    # Regression test: a blocker/question logged from a tty that has
    # since closed must still surface -- but only inside the *same*
    # project's own entry (as a project-level fallback, per get_projects'
    # "never dropped" comment), never detached from every project or
    # bled into a different one. This is what popover.js relies on to
    # keep every flag line inside its owning card -- see renderCard,
    # which nests project.blockers/questions inside that same project's
    # <div class="card">.
    db.upsert_project("proj-a", "/tmp/proj-a")
    db.upsert_project("proj-b", "/tmp/proj-b")
    # proj-a has one still-live session (ttys001) and one orphaned
    # question from a now-closed terminal (ttys099).
    _log("proj-a", "done", "did a thing", "ttys001", "2026-08-15T00:00:00+00:00", source_id="a1")
    _log(
        "proj-a", "question", "still needs an answer", "ttys099", "2026-08-15T00:01:00+00:00",
        source_id="a2",
    )
    _log("proj-b", "done", "unrelated work", "ttys002", "2026-08-15T00:00:00+00:00", source_id="b1")

    # Only ttys001 and ttys002 are live -- ttys099 (the question's
    # terminal) has closed.
    monkeypatch.setattr(
        process_utils.subprocess,
        "run",
        lambda cmd, **k: FakeResult(stdout="ttys001 claude\nttys002 claude\n"),
    )
    monkeypatch.setattr(app.terminal_launcher, "session_title_for_tty", lambda tty: None)

    api = app.Api()
    projects = {p["name"]: p for p in api.get_projects()}

    assert len(projects) == 2
    assert [q["text"] for q in projects["proj-a"]["questions"]] == ["still needs an answer"]
    # Never attached to the wrong project, and never left floating
    # without an owning project entry at all.
    assert projects["proj-b"]["questions"] == []


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


def test_get_projects_hides_project_whose_tty_was_reused_by_a_new_session(monkeypatch):
    # The reported bug: opening `claude` in an untracked directory got
    # macOS's next free tty -- one an old, since-closed session of
    # another project had used. That project's card came back to life
    # showing the dead session's history, instead of the new directory
    # getting a card of its own. Items logged before this tty's current
    # `claude` even started belong to that dead session, so they don't
    # make the tty live for anyone.
    db.upsert_project("proj", "/tmp/proj")
    _log("proj", "done", "old session's work", "ttys009", "2020-01-01T00:00:00+00:00",
         session_id="session-old", source_id="a1")

    monkeypatch.setattr(
        process_utils.subprocess,
        "run",
        _fake_ps(live="ttys009 claude\n", elapsed="ttys009    05:00 claude\n"),
    )

    api = app.Api()
    assert api.get_projects() == []


def test_get_projects_shows_project_once_the_new_session_logs_to_it(monkeypatch):
    # Same reused tty, but this time the session running on it has
    # logged for itself (the SessionStart hook does this immediately) --
    # so the project it's actually working in gets the card.
    db.upsert_project("proj", "/tmp/proj")
    _log("proj", "done", "old session's work", "ttys009", "2020-01-01T00:00:00+00:00",
         session_id="session-old", source_id="a1")
    _log("proj", "done", "this session's work", "ttys009",
         datetime.now(timezone.utc).isoformat(), session_id="session-new", source_id="b1")

    monkeypatch.setattr(
        process_utils.subprocess,
        "run",
        _fake_ps(live="ttys009 claude\n", elapsed="ttys009    05:00 claude\n"),
    )
    monkeypatch.setattr(app.terminal_launcher, "session_title_for_tty", lambda tty: None)

    api = app.Api()
    projects = api.get_projects()

    assert len(projects) == 1
    assert projects[0]["sessions"][0]["done"] == ["this session's work"]


def _live_ps(*ttys):
    """`ps` output for a set of ttys all running a `claude` started five
    minutes ago -- long enough that items logged "now" in a test count
    as this session's."""
    return _fake_ps(
        live="".join(f"{t} claude\n" for t in ttys),
        elapsed="".join(f"{t}    05:00 claude\n" for t in ttys),
    )


def test_session_card_shows_only_its_own_blockers_and_questions(monkeypatch):
    # Two sessions of the same project, running side by side. Each card
    # must show the flags its own agent raised -- pooling them would make
    # both look stuck on the other's problem.
    now = datetime.now(timezone.utc).isoformat()
    db.upsert_project("proj", "/tmp/proj")
    _log("proj", "done", "A shipped", "ttys001", now, session_id="sA", source_id="a1")
    _log("proj", "blocker", "A needs a key", "ttys001", now, session_id="sA", source_id="a2")
    _log("proj", "done", "B shipped", "ttys002", now, session_id="sB", source_id="b1")
    _log("proj", "question", "B asks which env", "ttys002", now, session_id="sB", source_id="b2")

    monkeypatch.setattr(process_utils.subprocess, "run", _live_ps("ttys001", "ttys002"))
    monkeypatch.setattr(app.terminal_launcher, "session_title_for_tty", lambda tty: None)

    project = app.Api().get_projects()[0]
    by_tty = {s["tty"]: s for s in project["sessions"]}

    assert [b["text"] for b in by_tty["ttys001"]["blockers"]] == ["A needs a key"]
    assert by_tty["ttys001"]["questions"] == []
    assert [q["text"] for q in by_tty["ttys002"]["questions"]] == ["B asks which env"]
    assert by_tty["ttys002"]["blockers"] == []
    # Both are accounted for on a session card, so neither is repeated
    # as a project-level fallback.
    assert project["blockers"] == [] and project["questions"] == []


def test_session_card_excludes_flags_raised_by_an_earlier_session_on_that_tty(monkeypatch):
    # Same reused-tty problem as the done/todo scoping above, for flags:
    # an unresolved blocker from the session that previously held this
    # tty isn't the current agent's, so it drops to the project-level
    # fallback rather than showing up as this session's own.
    now = datetime.now(timezone.utc).isoformat()
    db.upsert_project("proj", "/tmp/proj")
    _log("proj", "blocker", "old session's blocker", "ttys009", "2020-01-01T00:00:00+00:00",
         session_id="session-old", source_id="a1")
    _log("proj", "done", "new session's work", "ttys009", now,
         session_id="session-new", source_id="b1")

    monkeypatch.setattr(process_utils.subprocess, "run", _live_ps("ttys009"))
    monkeypatch.setattr(app.terminal_launcher, "session_title_for_tty", lambda tty: None)

    project = app.Api().get_projects()[0]

    assert project["sessions"][0]["blockers"] == []
    # Still surfaced somewhere -- flags are never silently dropped.
    assert [b["text"] for b in project["blockers"]] == ["old session's blocker"]


def test_session_card_keeps_flags_that_predate_session_id_tracking(monkeypatch):
    # Items logged before session ids were recorded have none; matching
    # on tty alone is all that's available, and is better than hiding a
    # live session's own blocker from its card.
    now = datetime.now(timezone.utc).isoformat()
    db.upsert_project("proj", "/tmp/proj")
    _log("proj", "blocker", "legacy blocker", "ttys009", now, session_id=None, source_id="a1")
    _log("proj", "done", "current work", "ttys009", now, session_id=None, source_id="b1")

    monkeypatch.setattr(process_utils.subprocess, "run", _live_ps("ttys009"))
    monkeypatch.setattr(app.terminal_launcher, "session_title_for_tty", lambda tty: None)

    project = app.Api().get_projects()[0]

    assert [b["text"] for b in project["sessions"][0]["blockers"]] == ["legacy blocker"]
    assert project["blockers"] == []


def test_session_card_hides_resolved_todos_and_flags(monkeypatch):
    now = datetime.now(timezone.utc).isoformat()
    db.upsert_project("proj", "/tmp/proj")
    _log("proj", "todo", "still to do", "ttys009", now, session_id="s1", source_id="t1")
    db.upsert_item(
        project="proj", item_type="todo", text="already handled", created_at=now,
        resolved_at=now, source="agent", source_id="t2", terminal_tty="ttys009", session_id="s1",
    )
    db.upsert_item(
        project="proj", item_type="blocker", text="answered blocker", created_at=now,
        resolved_at=now, source="agent", source_id="b1", terminal_tty="ttys009", session_id="s1",
    )

    monkeypatch.setattr(process_utils.subprocess, "run", _live_ps("ttys009"))
    monkeypatch.setattr(app.terminal_launcher, "session_title_for_tty", lambda tty: None)

    session = app.Api().get_projects()[0]["sessions"][0]

    assert session["todo"] == ["still to do"]
    assert session["blockers"] == []


def test_session_card_shows_the_three_most_recent_done_and_todo(monkeypatch):
    db.upsert_project("proj", "/tmp/proj")
    # Timestamps within this session's lifetime (it started five minutes
    # ago, per _live_ps), oldest first.
    now = datetime.now(timezone.utc)
    for i in range(5):
        stamp = (now - timedelta(seconds=60 - i)).isoformat()
        _log("proj", "done", f"done {i}", "ttys009", stamp, session_id="s1", source_id=f"d{i}")
        _log("proj", "todo", f"todo {i}", "ttys009", stamp, session_id="s1", source_id=f"t{i}")

    monkeypatch.setattr(process_utils.subprocess, "run", _live_ps("ttys009"))
    monkeypatch.setattr(app.terminal_launcher, "session_title_for_tty", lambda tty: None)

    session = app.Api().get_projects()[0]["sessions"][0]

    # Newest first, capped at three -- what's most immediately relevant,
    # not the oldest backlog.
    assert session["done"] == ["done 4", "done 3", "done 2"]
    assert session["todo"] == ["todo 4", "todo 3", "todo 2"]


def test_session_card_ignores_another_projects_items_on_the_same_tty(monkeypatch):
    # One long-running conversation that `cd`'d from proj-a into proj-b:
    # the tty now belongs to proj-b, and proj-a mustn't show either the
    # session or its own earlier items as live.
    earlier = datetime.now(timezone.utc).isoformat()
    later = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
    db.upsert_project("proj-a", "/tmp/proj-a")
    db.upsert_project("proj-b", "/tmp/proj-b")
    _log("proj-a", "done", "work in a", "ttys009", earlier, session_id="s1", source_id="a1")
    _log("proj-b", "done", "work in b", "ttys009", later, session_id="s1", source_id="b1")

    monkeypatch.setattr(process_utils.subprocess, "run", _live_ps("ttys009"))
    monkeypatch.setattr(app.terminal_launcher, "session_title_for_tty", lambda tty: None)

    projects = app.Api().get_projects()

    assert [p["name"] for p in projects] == ["proj-b"]
    assert projects[0]["sessions"][0]["done"] == ["work in b"]

