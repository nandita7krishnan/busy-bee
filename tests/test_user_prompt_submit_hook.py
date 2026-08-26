import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

from busy_bee import project_store

HOOK_PATH = Path(__file__).resolve().parent.parent / "hooks" / "user_prompt_submit_hook.py"
_spec = importlib.util.spec_from_file_location("user_prompt_submit_hook", HOOK_PATH)
user_prompt_submit_hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(user_prompt_submit_hook)


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "a-timeline"
    (root / ".claude-dashboard").mkdir(parents=True)
    (root / ".claude-dashboard" / "status.json").write_text("[]")
    monkeypatch.setattr(project_store.process_utils, "find_claude_ancestor_tty", lambda: "ttys002")
    monkeypatch.setattr(project_store.process_utils, "current_session_id", lambda: "session-a")
    return root


def _run(monkeypatch, cwd, session_id="session-a"):
    payload = {"cwd": str(cwd), "session_id": session_id, "prompt": "ok go ahead"}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    return user_prompt_submit_hook.main()


def _open_flags(root):
    return [
        i
        for i in project_store.all_items(root)
        if i["type"] in ("blocker", "question") and i["resolved_at"] is None
    ]


def test_replying_clears_this_sessions_blocker_and_question(monkeypatch, project):
    project_store.add_item(project, "question", "which auth flow?")
    project_store.add_item(project, "blocker", "needs the staging creds")

    assert _run(monkeypatch, project) == 0

    assert _open_flags(project) == []


def test_replying_leaves_done_and_todo_items_alone(monkeypatch, project):
    # Only flags mean "waiting on you" -- an unresolved todo is the
    # agent's own plan and has nothing to do with the user replying.
    project_store.add_item(project, "todo", "wire up the hook")
    project_store.add_item(project, "done", "read the config")

    assert _run(monkeypatch, project) == 0

    todo = [i for i in project_store.all_items(project) if i["type"] == "todo"]
    assert todo[0]["resolved_at"] is None


def test_another_sessions_flags_are_not_cleared(monkeypatch, project):
    # Two live sessions in one project: answering one doesn't answer the
    # other, so its question has to stay on the dashboard.
    monkeypatch.setattr(project_store.process_utils, "current_session_id", lambda: "session-b")
    project_store.add_item(project, "question", "rename the column?")

    assert _run(monkeypatch, project, session_id="session-a") == 0

    assert [i["text"] for i in _open_flags(project)] == ["rename the column?"]


def test_already_resolved_flags_keep_their_original_timestamp(monkeypatch, project):
    item = project_store.add_item(project, "question", "which auth flow?")
    project_store.resolve_item(project, "question", item["id"])
    resolved_at = project_store.all_items(project)[0]["resolved_at"]

    assert _run(monkeypatch, project) == 0

    assert project_store.all_items(project)[0]["resolved_at"] == resolved_at


def test_untracked_directory_is_a_no_op(monkeypatch, tmp_path):
    plain = tmp_path / "not-a-project"
    plain.mkdir()
    assert _run(monkeypatch, plain) == 0
    assert project_store.all_items(plain) == []


def test_missing_session_id_leaves_everything_alone(monkeypatch, project):
    # Without a session to scope to, clearing anything would take out
    # other terminals' flags too -- so it does nothing at all.
    monkeypatch.setattr(user_prompt_submit_hook.process_utils, "current_session_id", lambda: None)
    project_store.add_item(project, "question", "which auth flow?")

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": str(project)})))
    assert user_prompt_submit_hook.main() == 0

    assert len(_open_flags(project)) == 1


def test_hook_prints_nothing_on_stdout(monkeypatch, project, capsys):
    # UserPromptSubmit injects a zero-exit hook's stdout into the
    # model's context, so anything printed here lands in the
    # conversation as if the user had typed it.
    project_store.add_item(project, "question", "which auth flow?")
    _run(monkeypatch, project)
    assert capsys.readouterr().out == ""
