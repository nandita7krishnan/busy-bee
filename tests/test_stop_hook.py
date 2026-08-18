import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

from busy_bee import project_store

HOOK_PATH = Path(__file__).resolve().parent.parent / "hooks" / "stop_hook.py"
_spec = importlib.util.spec_from_file_location("stop_hook", HOOK_PATH)
stop_hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stop_hook)


@pytest.fixture(autouse=True)
def fixed_session(monkeypatch):
    monkeypatch.setattr(stop_hook.process_utils, "find_claude_ancestor_tty", lambda: "ttys002")
    monkeypatch.setattr(project_store.process_utils, "find_claude_ancestor_tty", lambda: "ttys002")
    monkeypatch.setattr(stop_hook.process_utils, "current_session_id", lambda: "session-1")
    monkeypatch.setattr(project_store.process_utils, "current_session_id", lambda: "session-1")
    yield


def _run(monkeypatch, capsys, cwd, extra_payload=None):
    payload = {"cwd": str(cwd), **(extra_payload or {})}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    stop_hook.main()
    out = capsys.readouterr().out.strip()
    return json.loads(out) if out else None


def test_untracked_project_is_a_noop(monkeypatch, capsys, tmp_path):
    assert _run(monkeypatch, capsys, tmp_path) is None


def test_stop_hook_active_short_circuits(monkeypatch, capsys, tmp_path):
    project_store.add_item(tmp_path, "done", "did a thing")
    assert _run(monkeypatch, capsys, tmp_path, {"stop_hook_active": True}) is None


def test_first_turn_requires_a_summary_specifically(monkeypatch, capsys, tmp_path):
    project_store.add_item(tmp_path, "done", "did a thing")  # creates status.json, turn 1

    result = _run(monkeypatch, capsys, tmp_path)

    assert result["decision"] == "block"
    assert "summary" in result["reason"]


def test_first_turn_satisfied_once_a_summary_is_logged(monkeypatch, capsys, tmp_path):
    project_store.add_item(tmp_path, "done", "did a thing")
    project_store.add_item(tmp_path, "summary", "where things stand")

    assert _run(monkeypatch, capsys, tmp_path) is None


def test_turns_two_through_ten_only_need_any_item(monkeypatch, capsys, tmp_path):
    project_store.add_item(tmp_path, "summary", "seed")  # creates status.json, satisfies turn 1
    assert _run(monkeypatch, capsys, tmp_path) is None  # turn 1

    for turn in range(2, 11):
        project_store.add_item(tmp_path, "done", f"turn {turn} work")
        assert _run(monkeypatch, capsys, tmp_path) is None  # turns 2..10


def test_eleventh_turn_requires_a_summary_again(monkeypatch, capsys, tmp_path):
    project_store.add_item(tmp_path, "summary", "seed")
    assert _run(monkeypatch, capsys, tmp_path) is None  # turn 1
    for turn in range(2, 11):
        project_store.add_item(tmp_path, "done", f"turn {turn} work")
        assert _run(monkeypatch, capsys, tmp_path) is None  # turns 2..10

    project_store.add_item(tmp_path, "done", "turn 11 work, no summary")
    result = _run(monkeypatch, capsys, tmp_path)

    assert result["decision"] == "block"
    assert "summary" in result["reason"]


def test_new_session_in_reused_tty_does_not_inherit_old_sessions_turn_count(
    monkeypatch, capsys, tmp_path
):
    # Same terminal tty (the OS reuses it), but a brand new `claude`
    # invocation -- a fresh session_id. The old session's turns (and its
    # already-satisfied summary requirement) must not carry over.
    project_store.add_item(tmp_path, "summary", "old session seed")  # old session, turn 1
    for turn in range(2, 11):
        project_store.add_item(tmp_path, "done", f"old session turn {turn}")
        assert _run(monkeypatch, capsys, tmp_path) is None

    monkeypatch.setattr(stop_hook.process_utils, "current_session_id", lambda: "session-2")
    monkeypatch.setattr(project_store.process_utils, "current_session_id", lambda: "session-2")

    project_store.add_item(tmp_path, "done", "new session first turn")
    result = _run(monkeypatch, capsys, tmp_path)

    assert result["decision"] == "block"
    assert "summary" in result["reason"]


def test_no_session_id_falls_back_to_general_check(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(stop_hook.process_utils, "current_session_id", lambda: None)
    project_store.add_item(tmp_path, "done", "did a thing")

    assert _run(monkeypatch, capsys, tmp_path) is None


def test_no_session_id_and_nothing_logged_blocks_generally(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(stop_hook.process_utils, "current_session_id", lambda: None)
    status_dir = tmp_path / ".claude-dashboard"
    status_dir.mkdir()
    (status_dir / "status.json").write_text("[]")

    result = _run(monkeypatch, capsys, tmp_path)

    assert result["decision"] == "block"
    assert "dashctl done" in result["reason"]
