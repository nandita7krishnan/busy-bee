import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

from busy_bee import config, project_store

HOOK_PATH = Path(__file__).resolve().parent.parent / "hooks" / "session_start_hook.py"
_spec = importlib.util.spec_from_file_location("session_start_hook", HOOK_PATH)
session_start_hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(session_start_hook)


@pytest.fixture(autouse=True)
def fixed_session(monkeypatch, tmp_path):
    # The hook registers projects now, so the config it writes to has to
    # be a throwaway -- otherwise a test run adds its own tmp_path
    # directories to the real ~/.claude-dashboard/config.json.
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "cfg" / "config.json")
    monkeypatch.setattr(config, "HOME_DIR", tmp_path / "cfg")
    monkeypatch.setattr(project_store.process_utils, "find_claude_ancestor_tty", lambda: "ttys002")
    monkeypatch.setattr(project_store.process_utils, "current_session_id", lambda: "session-new")
    yield


def _run(monkeypatch, cwd, extra_payload=None):
    payload = {"cwd": str(cwd), **(extra_payload or {})}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    return session_start_hook.main()


def test_untracked_directory_is_registered_and_logged(monkeypatch, tmp_path):
    # A session opening somewhere busy-bee doesn't know about yet gets
    # that directory tracked right away. Skipping it (the old behaviour)
    # left the session invisible, so its reused tty stayed attributed to
    # whichever unrelated project last logged from that tty number.
    project_dir = tmp_path / "a-timeline"
    project_dir.mkdir()

    assert _run(monkeypatch, project_dir) == 0

    assert [p["name"] for p in config.list_projects()] == ["a-timeline"]
    assert [i["type"] for i in project_store.all_items(project_dir)] == ["session_start"]


def test_home_directory_is_not_registered(monkeypatch, tmp_path):
    # $HOME isn't a project -- `claude` run straight from it shouldn't
    # register "yourusername" as one, same rule dashctl's log commands use.
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    assert _run(monkeypatch, home) == 0

    assert config.list_projects() == []
    assert project_store.all_items(home) == []


def test_tracked_project_logs_a_session_start_marker(monkeypatch, tmp_path):
    config.add_project(tmp_path.name, str(tmp_path))
    project_store.add_item(tmp_path, "done", "earlier, unrelated session's work")

    _run(monkeypatch, tmp_path)

    items = project_store.all_items(tmp_path)
    assert items[-1]["type"] == "session_start"
    assert items[-1]["session_id"] == "session-new"


def test_prints_additional_context_for_pending_handed_off_tasks(monkeypatch, tmp_path, capsys):
    config.add_project(tmp_path.name, str(tmp_path))
    project_store.add_item(tmp_path, "todo", "sketch the schema", source="human")

    assert _run(monkeypatch, tmp_path) == 0

    out = json.loads(capsys.readouterr().out)
    context = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "sketch the schema" in context


def test_prints_nothing_when_there_are_no_pending_handed_off_tasks(monkeypatch, tmp_path, capsys):
    config.add_project(tmp_path.name, str(tmp_path))
    project_store.add_item(tmp_path, "todo", "an ordinary agent todo")  # source="agent"

    assert _run(monkeypatch, tmp_path) == 0

    assert capsys.readouterr().out == ""


def test_ignores_already_resolved_handed_off_tasks(monkeypatch, tmp_path, capsys):
    config.add_project(tmp_path.name, str(tmp_path))
    item = project_store.add_item(tmp_path, "todo", "sketch the schema", source="human")
    project_store.resolve_item(tmp_path, "todo", item["id"])

    assert _run(monkeypatch, tmp_path) == 0

    assert capsys.readouterr().out == ""


def test_new_session_in_reused_tty_immediately_takes_over_the_tty(monkeypatch, tmp_path):
    # The exact bug this hook exists to close: a new session in a
    # reused tty must claim tty ownership before it has logged anything
    # else, not just once it eventually logs a done/todo/summary.
    config.add_project(tmp_path.name, str(tmp_path))
    monkeypatch.setattr(project_store.process_utils, "current_session_id", lambda: "session-old")
    project_store.add_item(tmp_path, "summary", "old session's summary")
    project_store.add_item(tmp_path, "todo", "old session's todo")

    monkeypatch.setattr(project_store.process_utils, "current_session_id", lambda: "session-new")
    _run(monkeypatch, tmp_path)

    items = project_store.all_items(tmp_path)
    latest_with_tty = max(
        (i for i in items if i.get("terminal_tty")), key=lambda i: i["created_at"]
    )
    assert latest_with_tty["session_id"] == "session-new"


def test_subdirectory_of_a_tracked_project_is_not_a_new_project(monkeypatch, tmp_path):
    # A session opened in `my-app/backend` is work on `my-app`: it used
    # to register "backend" as a second project of its own, splitting
    # the same work across two dashboard cards.
    project_dir = tmp_path / "point-not-so-mid"
    subdir = project_dir / "backend"
    subdir.mkdir(parents=True)
    config.add_project("point-not-so-mid", str(project_dir))

    assert _run(monkeypatch, subdir) == 0

    assert [p["name"] for p in config.list_projects()] == ["point-not-so-mid"]
    assert [i["type"] for i in project_store.all_items(project_dir)] == ["session_start"]
    assert not (subdir / ".claude-dashboard").exists()


def test_first_session_in_a_subdirectory_registers_the_repo(monkeypatch, tmp_path):
    # Nothing tracked yet: the project has to be identified by the repo
    # it belongs to, or it gets named after whichever directory the
    # first session was started in.
    repo = tmp_path / "point-not-so-mid"
    subdir = repo / "backend"
    subdir.mkdir(parents=True)
    (repo / ".git").mkdir()

    assert _run(monkeypatch, subdir) == 0

    assert [(p["name"], p["path"]) for p in config.list_projects()] == [
        ("point-not-so-mid", str(repo))
    ]
    assert [i["type"] for i in project_store.all_items(repo)] == ["session_start"]
    assert not (subdir / ".claude-dashboard").exists()
