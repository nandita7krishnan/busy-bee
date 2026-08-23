from pathlib import Path

import pytest

from busy_bee import config, db, placeholder_store


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME_DIR", tmp_path / "cfg")
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "cfg" / "config.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "cfg" / "db.sqlite")
    db.init_db()
    yield


def test_create_placeholder_persists_across_loads():
    placeholder_store.create("new-thing")
    assert [p["name"] for p in placeholder_store.load()] == ["new-thing"]
    assert placeholder_store.get("new-thing")["activated_path"] is None
    assert placeholder_store.get("new-thing")["tasks"] == []


def test_create_placeholder_rejects_duplicate_name():
    placeholder_store.create("dup")
    try:
        placeholder_store.create("dup")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_create_placeholder_rejects_name_already_tracked_as_a_project():
    config.add_project("already-tracked", "/tmp/already-tracked")
    try:
        placeholder_store.create("already-tracked")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_create_placeholder_rejects_blank_name():
    try:
        placeholder_store.create("   ")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_create_placeholder_rejects_name_with_slash():
    try:
        placeholder_store.create("nested/name")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_create_placeholder_rejects_name_starting_with_dot():
    try:
        placeholder_store.create(".hidden")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_add_task_returns_task_with_id_and_null_resolved_at():
    placeholder_store.create("proj")
    task = placeholder_store.add_task("proj", "sketch the schema")
    assert task["text"] == "sketch the schema"
    assert task["resolved_at"] is None
    assert task["id"]


def test_add_task_rejects_blank_text():
    placeholder_store.create("proj")
    try:
        placeholder_store.add_task("proj", "   ")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_add_task_rejects_unknown_project():
    try:
        placeholder_store.add_task("nope", "text")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_set_task_resolved_marks_and_then_unmarks_the_same_task():
    placeholder_store.create("proj")
    task = placeholder_store.add_task("proj", "write tests")

    assert placeholder_store.set_task_resolved("proj", task["id"], True) is True
    resolved_task = next(t for t in placeholder_store.get("proj")["tasks"] if t["id"] == task["id"])
    assert resolved_task["resolved_at"] is not None

    assert placeholder_store.set_task_resolved("proj", task["id"], False) is True
    unresolved_task = next(t for t in placeholder_store.get("proj")["tasks"] if t["id"] == task["id"])
    assert unresolved_task["resolved_at"] is None


def test_set_task_resolved_returns_false_for_unknown_task_id():
    placeholder_store.create("proj")
    assert placeholder_store.set_task_resolved("proj", "does-not-exist", True) is False


def test_set_task_resolved_returns_false_for_unknown_project():
    assert placeholder_store.set_task_resolved("nope", "some-id", True) is False


def test_creating_a_placeholder_and_tasks_creates_no_project_directory_on_disk(tmp_path):
    placeholder_store.create("never-a-folder")
    placeholder_store.add_task("never-a-folder", "do a thing")
    placeholder_store.set_task_resolved("never-a-folder", placeholder_store.get("never-a-folder")["tasks"][0]["id"], True)

    # Only the config home (and its placeholders.json/db.sqlite) may
    # exist -- nothing resembling a project folder anywhere under
    # tmp_path. This is the load-bearing guarantee against
    # project_store._save's mkdir side effect.
    created = {p.relative_to(tmp_path) for p in tmp_path.rglob("*")}
    assert created <= {
        Path("cfg"),
        Path("cfg/placeholders.json"),
        Path("cfg/db.sqlite"),
        Path("cfg/config.json"),
    }


def test_mark_activated_retains_the_record_and_its_tasks():
    placeholder_store.create("proj")
    placeholder_store.add_task("proj", "a task")

    placeholder_store.mark_activated("proj", "/tmp/proj")

    record = placeholder_store.get("proj")
    assert record["activated_path"] == "/tmp/proj"
    assert len(record["tasks"]) == 1
    assert placeholder_store.list_pending() == []
    assert [p["name"] for p in placeholder_store.list_retained()] == ["proj"]


def test_delete_placeholder_removes_it_and_its_tasks():
    placeholder_store.create("proj")
    placeholder_store.add_task("proj", "a task")

    assert placeholder_store.delete("proj") is True
    assert placeholder_store.get("proj") is None
    assert placeholder_store.load() == []


def test_delete_unknown_placeholder_returns_false():
    assert placeholder_store.delete("nope") is False
