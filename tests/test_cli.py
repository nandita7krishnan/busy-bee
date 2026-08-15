import pytest

from busy_bee import cli, config


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "cfg" / "config.json")
    monkeypatch.setattr(config, "HOME_DIR", tmp_path / "cfg")
    yield


def test_done_and_todo_logged(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["done", "shipped it"]) == 0
    assert cli.main(["todo", "write docs"]) == 0
    out = capsys.readouterr().out
    assert "logged done: shipped it" in out
    assert "logged todo: write docs" in out

    status_file = tmp_path / ".claude-dashboard" / "status.json"
    assert status_file.exists()


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
