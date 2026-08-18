from pathlib import Path

import pytest

from busy_bee import cli, config, db, project_store


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "cfg" / "config.json")
    monkeypatch.setattr(config, "HOME_DIR", tmp_path / "cfg")
    monkeypatch.setattr(project_store.process_utils, "find_claude_ancestor_tty", lambda: None)
    monkeypatch.setattr(project_store.process_utils, "current_session_id", lambda: None)
    yield


def test_done_and_todo_logged(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["done", "shipped it"]) == 0
    assert cli.main(["todo", "write docs"]) == 0
    out = capsys.readouterr().out
    assert "logged done: shipped it" in out
    assert "logged todo [" in out and "]: write docs" in out

    status_file = tmp_path / ".claude-dashboard" / "status.json"
    assert status_file.exists()


def test_log_nudges_toward_conciseness_without_blocking(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    long_text = " ".join(["word"] * 20)
    assert cli.main(["done", long_text]) == 0  # doesn't fail the command

    out = capsys.readouterr()
    assert f"logged done: {long_text}" in out.out  # full text still logged, not truncated
    assert "tip:" in out.err
    assert "20 words" in out.err


def test_log_stays_quiet_when_concise(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    cli.main(["done", "shipped it"])
    err = capsys.readouterr().err
    assert err == ""


def test_todo_then_resolve(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    cli.main(["todo", "write docs"])
    out = capsys.readouterr().out
    item_id = out.split("[")[1].split("]")[0]

    assert cli.main(["resolve", "todo", item_id]) == 0
    out = capsys.readouterr().out
    assert f"resolved todo [{item_id}]" in out


def test_summary_logged_without_id(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["summary", "auth flow mostly done, tests pending"]) == 0
    out = capsys.readouterr().out
    assert "logged summary: auth flow mostly done, tests pending" in out
    assert "[" not in out  # no id printed, unlike blocker/question


def test_log_auto_registers_project_without_init(tmp_path, monkeypatch):
    project_dir = tmp_path / "auto-proj"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    assert config.list_projects() == []
    cli.main(["done", "shipped it"])

    projects = config.list_projects()
    assert len(projects) == 1
    assert projects[0]["name"] == "auto-proj"
    assert projects[0]["path"] == str(project_dir.resolve())


def test_log_does_not_auto_register_home_directory(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.chdir(fake_home)

    cli.main(["done", "just poking around"])
    assert config.list_projects() == []


def test_log_does_not_duplicate_registration(tmp_path, monkeypatch):
    project_dir = tmp_path / "auto-proj"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    cli.main(["done", "first"])
    cli.main(["todo", "second"])
    cli.main(["blocker", "third"])

    assert len(config.list_projects()) == 1


def test_blocker_then_resolve(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    cli.main(["blocker", "need creds"])
    out = capsys.readouterr().out
    item_id = out.split("[")[1].split("]")[0]

    assert cli.main(["resolve", "blocker", item_id]) == 0
    out = capsys.readouterr().out
    assert f"resolved blocker [{item_id}]" in out


def test_resolve_unknown_id_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    exit_code = cli.main(["resolve", "blocker", "nope"])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "no unresolved blocker" in err


def test_init_registers_project(tmp_path, monkeypatch):
    project_dir = tmp_path / "my-proj"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    assert cli.main(["init"]) == 0

    projects = config.list_projects()
    assert len(projects) == 1
    assert projects[0]["name"] == "my-proj"
    assert projects[0]["path"] == str(project_dir)


def test_untrack_removes_project_from_config_and_db(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "cfg" / "db.sqlite")
    db.init_db()

    project_dir = tmp_path / "stray-proj"
    config.add_project("stray-proj", str(project_dir))
    db.upsert_project("stray-proj", str(project_dir))
    db.upsert_item(
        project="stray-proj",
        item_type="done",
        text="logged before being untracked",
        created_at="2026-08-18T00:00:00+00:00",
        resolved_at=None,
        source="agent",
        source_id=None,
    )

    assert cli.main(["untrack", "stray-proj"]) == 0
    out = capsys.readouterr().out
    assert "untracked 'stray-proj'" in out

    assert config.list_projects() == []
    assert db.get_project("stray-proj") is None
    assert db.get_recent_done("stray-proj") == []


def test_untrack_unknown_project_still_clears_db(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "cfg" / "db.sqlite")
    db.init_db()

    assert cli.main(["untrack", "never-registered"]) == 0
    out = capsys.readouterr().out
    assert "wasn't in config.json" in out
    assert "untracked 'never-registered'" in out
