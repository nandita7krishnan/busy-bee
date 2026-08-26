from datetime import datetime, timedelta, timezone

import pytest

from busy_bee import app, config, db, placeholder_store, process_utils


class FakeResult:
    def __init__(self, stdout=""):
        self.stdout = stdout


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "cfg" / "db.sqlite")
    monkeypatch.setattr(config, "HOME_DIR", tmp_path / "cfg")
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "cfg" / "config.json")
    db.init_db()
    yield


class FakeWindow:
    """Stands in for the popover's webview.Window -- just enough surface
    for dialogs.choose_folder (create_file_dialog) and
    Api.refresh_popover_content (evaluate_js) to have something to call."""

    def __init__(self, folder_result=None):
        self.folder_result = folder_result  # a list (as pywebview returns) or None
        self.evaluate_js_calls = []

    def create_file_dialog(self, *args, **kwargs):
        return self.folder_result

    def evaluate_js(self, script):
        self.evaluate_js_calls.append(script)


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


def test_get_projects_orders_most_recently_active_terminal_first(monkeypatch):
    # Not alphabetical -- "aaa-oldest" would sort first by name, but the
    # dashboard is a view of what you're working on now, so the project
    # whose terminal logged most recently goes on top.
    # Both within the live sessions' lifetime (started five minutes ago,
    # per _live_ps) so neither is discarded as predating its tty's
    # current session -- only their order relative to each other matters.
    now = datetime.now(timezone.utc)
    older = (now - timedelta(seconds=60)).isoformat()
    newer = (now - timedelta(seconds=10)).isoformat()
    db.upsert_project("aaa-oldest", "/tmp/aaa")
    db.upsert_project("zzz-newest", "/tmp/zzz")
    _log("aaa-oldest", "done", "long ago", "ttys001", older, source_id="a1")
    _log("zzz-newest", "done", "just now", "ttys002", newer, source_id="b1")

    monkeypatch.setattr(process_utils.subprocess, "run", _live_ps("ttys001", "ttys002"))
    monkeypatch.setattr(app.terminal_launcher, "session_title_for_tty", lambda tty: None)

    projects = app.Api().get_projects()

    assert [p["name"] for p in projects] == ["zzz-newest", "aaa-oldest"]


def test_get_projects_does_not_leak_the_internal_sort_key(monkeypatch):
    db.upsert_project("proj", "/tmp/proj")
    _log("proj", "done", "did a thing", "ttys009", "2026-08-15T00:00:00+00:00")
    monkeypatch.setattr(
        process_utils.subprocess, "run", lambda cmd, **k: FakeResult(stdout="ttys009 claude\n")
    )
    monkeypatch.setattr(app.terminal_launcher, "session_title_for_tty", lambda tty: None)

    assert "_last_active" not in app.Api().get_projects()[0]


# --- placeholder projects ---------------------------------------------


def _no_live_claude(monkeypatch):
    monkeypatch.setattr(process_utils.subprocess, "run", lambda cmd, **k: FakeResult(stdout=""))


def test_get_projects_output_is_unchanged_when_there_are_no_placeholders(monkeypatch):
    # Regression guard: with zero placeholders, get_projects()'s output
    # must be byte-identical to before this feature existed.
    db.upsert_project("live-proj", "/tmp/live-proj")
    _log("live-proj", "done", "shipped it", "ttys009", "2026-08-15T00:00:00+00:00")
    monkeypatch.setattr(
        process_utils.subprocess, "run", lambda cmd, **k: FakeResult(stdout="ttys009 claude\n")
    )
    monkeypatch.setattr(app.terminal_launcher, "session_title_for_tty", lambda tty: None)

    projects = app.Api().get_projects()
    assert len(projects) == 1
    assert projects[0]["placeholder"] is False
    assert projects[0]["done"] == []
    assert projects[0]["todo"] == []


def test_get_projects_does_not_treat_legacy_agent_items_as_dashboard_tasks(monkeypatch):
    # Regression test: a real agent-logged 'done' item with no
    # terminal_tty or session_id recorded (predates that tracking being
    # reliable, or logged from a non-terminal context) must not be
    # mistaken for a migrated placeholder task -- confirmed live against
    # this repo's own history, which has exactly this shape from before
    # session tracking existed. The distinguishing signal is source
    # ('human' vs 'agent'), not a null tty/session_id.
    db.upsert_project("proj", "/tmp/proj")
    db.upsert_item(
        project="proj", item_type="done", text="legacy agent work",
        created_at="2026-08-15T05:44:42+00:00", resolved_at=None,
        source="agent", source_id="legacy1", terminal_tty=None, session_id=None,
    )
    monkeypatch.setattr(
        process_utils.subprocess, "run", lambda cmd, **k: FakeResult(stdout="ttys009 claude\n")
    )
    db.upsert_item(
        project="proj", item_type="done", text="live work",
        created_at="2026-08-15T06:00:00+00:00", resolved_at=None,
        source="agent", source_id="live1", terminal_tty="ttys009", session_id="s1",
    )
    monkeypatch.setattr(app.terminal_launcher, "session_title_for_tty", lambda tty: None)

    project = app.Api().get_projects()[0]

    assert project["done"] == []
    assert project["todo"] == []


def test_get_projects_returns_placeholder_card_with_no_live_session(monkeypatch):
    _no_live_claude(monkeypatch)
    placeholder_store.create("someday-project")

    projects = app.Api().get_projects()

    assert len(projects) == 1
    assert projects[0]["name"] == "someday-project"
    assert projects[0]["placeholder"] is True
    assert projects[0]["path"] is None
    assert projects[0]["sessions"] == []


def test_placeholder_card_lists_manual_tasks_as_objects_with_ids(monkeypatch):
    _no_live_claude(monkeypatch)
    placeholder_store.create("proj")
    task = placeholder_store.add_task("proj", "sketch the schema")

    project = app.Api().get_projects()[0]

    assert project["todo"] == [{"id": task["id"], "text": "sketch the schema"}]
    assert project["done"] == []


def test_checking_a_manual_task_moves_it_from_the_todo_to_the_done_column(monkeypatch):
    _no_live_claude(monkeypatch)
    placeholder_store.create("proj")
    task = placeholder_store.add_task("proj", "write tests")

    api = app.Api()
    result = api.set_placeholder_task_done("proj", task["id"], True)
    assert result["ok"] is True

    project = api.get_projects()[0]
    assert project["todo"] == []
    assert project["done"] == [{"id": task["id"], "text": "write tests"}]


def test_unchecking_a_manual_task_moves_it_back_to_the_todo_column(monkeypatch):
    _no_live_claude(monkeypatch)
    placeholder_store.create("proj")
    task = placeholder_store.add_task("proj", "write tests")

    api = app.Api()
    api.set_placeholder_task_done("proj", task["id"], True)
    api.set_placeholder_task_done("proj", task["id"], False)

    project = api.get_projects()[0]
    assert project["todo"] == [{"id": task["id"], "text": "write tests"}]
    assert project["done"] == []


def test_deleting_a_manual_task_drops_it_from_the_card(monkeypatch):
    _no_live_claude(monkeypatch)
    placeholder_store.create("proj")
    keep = placeholder_store.add_task("proj", "keep me")
    drop = placeholder_store.add_task("proj", "drop me")

    api = app.Api()
    assert api.delete_placeholder_task("proj", drop["id"])["ok"] is True

    project = api.get_projects()[0]
    assert project["todo"] == [{"id": keep["id"], "text": "keep me"}]


def test_delete_placeholder_task_reports_failure_for_unknown_task(monkeypatch):
    placeholder_store.create("proj")
    assert app.Api().delete_placeholder_task("proj", "nope")["ok"] is False


def test_add_placeholder_project_rejects_duplicate_name(monkeypatch):
    api = app.Api()
    assert api.add_placeholder_project("dup")["ok"] is True
    result = api.add_placeholder_project("dup")
    assert result["ok"] is False
    assert "error" in result


def test_remove_placeholder_project_deletes_it(monkeypatch):
    api = app.Api()
    api.add_placeholder_project("proj")
    assert api.remove_placeholder_project("proj")["ok"] is True
    assert placeholder_store.get("proj") is None


def test_remove_placeholder_project_with_tasks_asks_first(monkeypatch):
    asked = {}

    def fake_confirm(message, informative, ok_title, cancel_title):
        asked["message"] = message
        return True

    monkeypatch.setattr(app.dialogs, "confirm", fake_confirm)
    api = app.Api()
    api.add_placeholder_project("proj")
    placeholder_store.add_task("proj", "something worth losing")

    assert api.remove_placeholder_project("proj")["ok"] is True
    assert "proj" in asked["message"]
    assert placeholder_store.get("proj") is None


def test_remove_placeholder_project_keeps_the_card_when_the_confirm_is_declined(monkeypatch):
    monkeypatch.setattr(app.dialogs, "confirm", lambda *a, **k: False)
    api = app.Api()
    api.add_placeholder_project("proj")
    placeholder_store.add_task("proj", "something worth losing")

    result = api.remove_placeholder_project("proj")

    assert result["ok"] is False
    assert result["cancelled"] is True
    assert placeholder_store.get("proj") is not None


def test_remove_placeholder_project_with_no_tasks_skips_the_confirm(monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("an empty card should not prompt")

    monkeypatch.setattr(app.dialogs, "confirm", explode)
    api = app.Api()
    api.add_placeholder_project("proj")

    assert api.remove_placeholder_project("proj")["ok"] is True


def test_remove_placeholder_project_reports_an_unknown_card(monkeypatch):
    assert app.Api().remove_placeholder_project("nope")["ok"] is False


def test_activate_placeholder_creates_the_folder_and_registers_the_project(tmp_path, monkeypatch):
    monkeypatch.setattr(app.dialogs, "confirm", lambda *a, **k: False)
    api = app.Api()
    api.popover_window = FakeWindow(folder_result=[str(tmp_path)])
    api.add_placeholder_project("proj")

    result = api.activate_placeholder_project("proj")

    assert result["ok"] is True
    target = tmp_path / "proj"
    assert target.is_dir()
    assert (target / ".claude-dashboard" / "status.json").exists()
    assert config.list_projects() == [{"name": "proj", "path": str(target)}]
    assert db.get_project("proj") is not None


def test_activate_placeholder_migrates_tasks_into_status_json_when_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(app.dialogs, "confirm", lambda *a, **k: True)
    api = app.Api()
    api.popover_window = FakeWindow(folder_result=[str(tmp_path)])
    api.add_placeholder_project("proj")
    placeholder_store.add_task("proj", "sketch the schema")

    result = api.activate_placeholder_project("proj")

    assert result["ok"] is True
    assert result["handed_off"] is True
    assert result["migrated"] == 1

    from busy_bee import project_store

    items = project_store.all_items(tmp_path / "proj")
    todo_items = [i for i in items if i["type"] == "todo"]
    assert len(todo_items) == 1
    assert todo_items[0]["text"] == "sketch the schema"
    assert todo_items[0]["source"] == "human"
    assert todo_items[0]["terminal_tty"] is None
    assert todo_items[0]["session_id"] is None

    # The placeholder record's job is done -- migrated, not retained.
    assert placeholder_store.get("proj") is None


def test_accepted_handoff_opens_the_terminal_with_a_prompt_naming_the_tasks(tmp_path, monkeypatch):
    # The SessionStart hook's additionalContext injects the task list
    # but can't make Claude speak first -- Claude Code takes no turn
    # until a message arrives. Passing an opening prompt is what
    # actually makes the handoff visible to the user.
    monkeypatch.setattr(app.dialogs, "confirm", lambda *a, **k: True)
    calls = []
    monkeypatch.setattr(
        app.terminal_launcher,
        "resume_project",
        lambda *a, **k: calls.append((a, k)),
    )
    api = app.Api()
    api.popover_window = FakeWindow(folder_result=[str(tmp_path)])
    api.add_placeholder_project("proj")
    placeholder_store.add_task("proj", "sketch the schema")

    api.activate_placeholder_project("proj")

    assert len(calls) == 1
    prompt = calls[0][1]["prompt"]
    assert "sketch the schema" in prompt
    assert "dashctl resolve todo" in prompt


def test_declined_handoff_does_not_open_a_terminal(tmp_path, monkeypatch):
    monkeypatch.setattr(app.dialogs, "confirm", lambda *a, **k: False)
    calls = []
    monkeypatch.setattr(
        app.terminal_launcher, "resume_project", lambda *a, **k: calls.append((a, k))
    )
    api = app.Api()
    api.popover_window = FakeWindow(folder_result=[str(tmp_path)])
    api.add_placeholder_project("proj")
    placeholder_store.add_task("proj", "sketch the schema")

    api.activate_placeholder_project("proj")

    assert calls == []


def test_activate_placeholder_keeps_tasks_dashboard_only_when_declined(tmp_path, monkeypatch):
    monkeypatch.setattr(app.dialogs, "confirm", lambda *a, **k: False)
    api = app.Api()
    api.popover_window = FakeWindow(folder_result=[str(tmp_path)])
    api.add_placeholder_project("proj")
    placeholder_store.add_task("proj", "sketch the schema")

    result = api.activate_placeholder_project("proj")

    assert result["ok"] is True
    assert result["handed_off"] is False

    from busy_bee import project_store

    assert project_store.all_items(tmp_path / "proj") == []

    record = placeholder_store.get("proj")
    assert record is not None
    assert record["activated_path"] == str(tmp_path / "proj")

    # And it still surfaces on the now-real project's card.
    _no_live_claude(monkeypatch)
    project = api.get_projects()[0]
    assert project["placeholder"] is False
    assert [t["text"] for t in project["todo"]] == ["sketch the schema"]


def test_activate_placeholder_does_nothing_when_the_folder_picker_is_cancelled(tmp_path, monkeypatch):
    api = app.Api()
    api.popover_window = FakeWindow(folder_result=None)  # user cancelled
    api.add_placeholder_project("proj")

    result = api.activate_placeholder_project("proj")

    assert result == {"ok": False, "cancelled": True}
    assert not (tmp_path / "proj").exists()
    assert placeholder_store.get("proj")["activated_path"] is None
    assert config.list_projects() == []


def test_activate_placeholder_refuses_when_the_target_folder_already_exists_and_is_not_empty(
    tmp_path, monkeypatch
):
    target = tmp_path / "proj"
    target.mkdir()
    (target / "some_file.txt").write_text("already here")

    api = app.Api()
    api.popover_window = FakeWindow(folder_result=[str(tmp_path)])
    api.add_placeholder_project("proj")

    result = api.activate_placeholder_project("proj")

    assert result["ok"] is False
    assert "error" in result
    assert config.list_projects() == []


def test_activate_placeholder_refuses_a_name_already_tracked_as_a_project(tmp_path, monkeypatch):
    api = app.Api()
    api.popover_window = FakeWindow(folder_result=[str(tmp_path)])
    api.add_placeholder_project("proj")

    # Simulates config.auto_register claiming the name from another
    # terminal in between the card being created and Create Folder
    # being clicked.
    config.add_project("proj", str(tmp_path / "elsewhere"))

    result = api.activate_placeholder_project("proj")

    assert result["ok"] is False
    assert not (tmp_path / "proj").exists()


def test_activate_placeholder_carve_out_keeps_the_card_visible_before_its_first_session(
    tmp_path, monkeypatch
):
    # The visibility fix this whole feature depends on: without it, the
    # card the user just created a folder for would immediately vanish
    # (app.py's ordinary "no live session -> skip" rule), which is the
    # worst possible moment for that to happen.
    monkeypatch.setattr(app.dialogs, "confirm", lambda *a, **k: False)
    _no_live_claude(monkeypatch)
    api = app.Api()
    api.popover_window = FakeWindow(folder_result=[str(tmp_path)])
    api.add_placeholder_project("proj")

    api.activate_placeholder_project("proj")

    projects = api.get_projects()
    assert len(projects) == 1
    assert projects[0]["name"] == "proj"
    assert projects[0]["placeholder"] is False
    assert projects[0]["sessions"] == []



def test_open_new_session_launches_a_fresh_session_in_the_project(tmp_path, monkeypatch):
    root = tmp_path / "a-timeline"
    root.mkdir()
    config.add_project("a-timeline", str(root))
    db.upsert_project("a-timeline", str(root))
    calls = []
    monkeypatch.setattr(
        app.terminal_launcher,
        "start_new_session",
        lambda path, terminal_app, prompt=None: calls.append((path, terminal_app, prompt)),
    )

    assert app.Api().open_new_session("a-timeline") == {"ok": True}
    assert calls == [(str(root), "Terminal", None)]


def test_open_new_session_passes_the_prompt_through(tmp_path, monkeypatch):
    root = tmp_path / "a-timeline"
    root.mkdir()
    db.upsert_project("a-timeline", str(root))
    calls = []
    monkeypatch.setattr(
        app.terminal_launcher,
        "start_new_session",
        lambda path, terminal_app, prompt=None: calls.append(prompt),
    )

    app.Api().open_new_session("a-timeline", "  fix the redirect loop  ")
    assert calls == ["fix the redirect loop"]


def test_open_new_session_treats_a_blank_prompt_as_none(tmp_path, monkeypatch):
    # An empty box means "just give me a terminal" -- passing "" through
    # would run `claude ''` and hand the session an empty first message.
    root = tmp_path / "a-timeline"
    root.mkdir()
    db.upsert_project("a-timeline", str(root))
    calls = []
    monkeypatch.setattr(
        app.terminal_launcher,
        "start_new_session",
        lambda path, terminal_app, prompt=None: calls.append(prompt),
    )

    app.Api().open_new_session("a-timeline", "   ")
    assert calls == [None]


def test_open_new_session_refuses_a_project_whose_folder_is_gone(tmp_path, monkeypatch):
    db.upsert_project("a-timeline", str(tmp_path / "deleted"))
    monkeypatch.setattr(
        app.terminal_launcher,
        "start_new_session",
        lambda *a, **k: pytest.fail("should not have opened a terminal"),
    )

    result = app.Api().open_new_session("a-timeline")
    assert result["ok"] is False
    assert "no longer exists" in result["error"]


def test_open_new_session_reports_an_unknown_project(monkeypatch):
    result = app.Api().open_new_session("never-registered")
    assert result["ok"] is False


def test_open_new_session_reports_a_failed_launch(tmp_path, monkeypatch):
    # osascript failing shouldn't take the popover down with it -- the
    # tile shows the message instead.
    root = tmp_path / "a-timeline"
    root.mkdir()
    db.upsert_project("a-timeline", str(root))

    def boom(*args, **kwargs):
        raise RuntimeError("Terminal is not running")

    monkeypatch.setattr(app.terminal_launcher, "start_new_session", boom)

    result = app.Api().open_new_session("a-timeline")
    assert result["ok"] is False
    assert "Terminal is not running" in result["error"]


def test_open_new_session_honours_the_configured_terminal_app(tmp_path, monkeypatch):
    root = tmp_path / "a-timeline"
    root.mkdir()
    db.upsert_project("a-timeline", str(root))
    config.save_config({**config.load_config(), "terminal_app": "iTerm"})
    calls = []
    monkeypatch.setattr(
        app.terminal_launcher,
        "start_new_session",
        lambda path, terminal_app, prompt=None: calls.append(terminal_app),
    )

    app.Api().open_new_session("a-timeline")
    assert calls == ["iTerm"]
