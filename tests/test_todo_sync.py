import pytest

from busy_bee import project_store, todo_sync


@pytest.fixture(autouse=True)
def no_real_tty_lookup(monkeypatch):
    monkeypatch.setattr(project_store.process_utils, "find_claude_ancestor_tty", lambda: None)
    yield


def test_sync_skips_untracked_project(tmp_path):
    todo_sync.sync_todos(tmp_path, [{"content": "do a thing", "status": "pending"}])
    assert project_store.all_items(tmp_path) == []


def test_sync_logs_pending_and_in_progress_as_todo(tmp_path):
    project_store.add_item(tmp_path, "done", "already tracked")  # creates status.json
    todo_sync.sync_todos(
        tmp_path,
        [
            {"content": "write tests", "status": "pending"},
            {"content": "fix the bug", "status": "in_progress"},
        ],
    )
    items = project_store.all_items(tmp_path)
    todos = [i for i in items if i["type"] == "todo"]
    assert {i["text"] for i in todos} == {"write tests", "fix the bug"}


def test_sync_logs_completed_as_done(tmp_path):
    project_store.add_item(tmp_path, "done", "already tracked")
    todo_sync.sync_todos(tmp_path, [{"content": "ship it", "status": "completed"}])
    items = project_store.all_items(tmp_path)
    done = [i for i in items if i["type"] == "done"]
    assert "ship it" in {i["text"] for i in done}


def test_sync_does_not_relog_unchanged_items(tmp_path):
    project_store.add_item(tmp_path, "done", "already tracked")
    todos = [{"content": "write tests", "status": "pending"}]
    todo_sync.sync_todos(tmp_path, todos)
    todo_sync.sync_todos(tmp_path, todos)
    todo_sync.sync_todos(tmp_path, todos)

    items = project_store.all_items(tmp_path)
    matching = [i for i in items if i["type"] == "todo" and i["text"] == "write tests"]
    assert len(matching) == 1


def test_sync_logs_done_once_when_transitioning_to_completed(tmp_path):
    project_store.add_item(tmp_path, "done", "already tracked")
    content = "write tests"

    todo_sync.sync_todos(tmp_path, [{"content": content, "status": "pending"}])
    todo_sync.sync_todos(tmp_path, [{"content": content, "status": "in_progress"}])
    todo_sync.sync_todos(tmp_path, [{"content": content, "status": "completed"}])
    todo_sync.sync_todos(tmp_path, [{"content": content, "status": "completed"}])

    items = project_store.all_items(tmp_path)
    done_matches = [i for i in items if i["type"] == "done" and i["text"] == content]
    todo_matches = [i for i in items if i["type"] == "todo" and i["text"] == content]
    assert len(done_matches) == 1
    assert len(todo_matches) == 1  # logged once when first seen as pending


def test_sync_ignores_malformed_entries(tmp_path):
    project_store.add_item(tmp_path, "done", "already tracked")
    todo_sync.sync_todos(
        tmp_path,
        [
            {"content": "", "status": "pending"},
            {"status": "pending"},
            {"content": "fine", "status": "unknown_status"},
        ],
    )
    items = project_store.all_items(tmp_path)
    todos = [i for i in items if i["type"] == "todo"]
    assert todos == []
