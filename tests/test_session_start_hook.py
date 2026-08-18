import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

from busy_bee import project_store

HOOK_PATH = Path(__file__).resolve().parent.parent / "hooks" / "session_start_hook.py"
_spec = importlib.util.spec_from_file_location("session_start_hook", HOOK_PATH)
session_start_hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(session_start_hook)


@pytest.fixture(autouse=True)
def fixed_session(monkeypatch):
    monkeypatch.setattr(project_store.process_utils, "find_claude_ancestor_tty", lambda: "ttys002")
    monkeypatch.setattr(project_store.process_utils, "current_session_id", lambda: "session-new")
    yield


def _run(monkeypatch, cwd, extra_payload=None):
    payload = {"cwd": str(cwd), **(extra_payload or {})}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    return session_start_hook.main()


def test_untracked_project_is_a_noop(monkeypatch, tmp_path):
    assert _run(monkeypatch, tmp_path) == 0
    assert project_store.all_items(tmp_path) == []


def test_tracked_project_logs_a_session_start_marker(monkeypatch, tmp_path):
    project_store.add_item(tmp_path, "done", "earlier, unrelated session's work")

    _run(monkeypatch, tmp_path)

    items = project_store.all_items(tmp_path)
    assert items[-1]["type"] == "session_start"
    assert items[-1]["session_id"] == "session-new"


def test_new_session_in_reused_tty_immediately_takes_over_the_tty(monkeypatch, tmp_path):
    # The exact bug this hook exists to close: a new session in a
    # reused tty must claim tty ownership before it has logged anything
    # else, not just once it eventually logs a done/todo/summary.
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
