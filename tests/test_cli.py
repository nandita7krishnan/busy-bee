from pathlib import Path

import pytest

from busy_bee import cli, config, db, project_store


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "cfg" / "config.json")
    monkeypatch.setattr(config, "HOME_DIR", tmp_path / "cfg")
    monkeypatch.setattr(project_store.process_utils, "find_claude_ancestor_tty", lambda: None)
    monkeypatch.setattr(project_store.process_utils, "current_session_id", lambda: None)
    # No enclosing Claude Code session by default, so these exercise the
    # cwd fallback. Without it the suite picks up the *real* session
    # running it -- which is exactly the signal _project_root is built
    # on, so the tests that want it say so explicitly instead.
    monkeypatch.setattr(cli.process_utils, "claude_session_cwd", lambda: None)
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


def test_untrack_also_forgets_a_retained_dashboard_task_list(tmp_path, monkeypatch, capsys):
    from busy_bee import placeholder_store

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "cfg" / "db.sqlite")
    db.init_db()

    project_dir = tmp_path / "proj"
    placeholder_store.create("proj")
    placeholder_store.add_task("proj", "leftover manual task")
    config.add_project("proj", str(project_dir))
    db.upsert_project("proj", str(project_dir))
    placeholder_store.mark_activated("proj", str(project_dir))

    assert cli.main(["untrack", "proj"]) == 0

    assert placeholder_store.get("proj") is None


def test_untrack_unknown_project_still_clears_db(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "cfg" / "db.sqlite")
    db.init_db()

    assert cli.main(["untrack", "never-registered"]) == 0
    out = capsys.readouterr().out
    assert "wasn't in config.json" in out
    assert "untracked 'never-registered'" in out


def test_log_from_subdirectory_goes_to_the_enclosing_project(tmp_path, monkeypatch):
    project_dir = tmp_path / "point-not-so-mid"
    subdir = project_dir / "backend"
    subdir.mkdir(parents=True)
    config.add_project("point-not-so-mid", str(project_dir))

    monkeypatch.chdir(subdir)
    assert cli.main(["done", "wired up the API"]) == 0

    # No second project called "backend" sitting next to its own parent.
    assert [p["name"] for p in config.list_projects()] == ["point-not-so-mid"]
    assert [i["text"] for i in project_store.all_items(project_dir)] == ["wired up the API"]
    assert not (subdir / ".claude-dashboard").exists()


def test_log_from_subdirectory_uses_the_nearest_tracked_project(tmp_path, monkeypatch):
    outer = tmp_path / "outer"
    inner = outer / "vendored" / "inner"
    deeper = inner / "src"
    deeper.mkdir(parents=True)
    config.add_project("outer", str(outer))
    config.add_project("inner", str(inner))  # explicitly tracked in its own right

    monkeypatch.chdir(deeper)
    assert cli.main(["done", "inner work"]) == 0

    assert [i["text"] for i in project_store.all_items(inner)] == ["inner work"]
    assert project_store.all_items(outer) == []


def test_init_still_tracks_a_subdirectory_explicitly(tmp_path, monkeypatch, capsys):
    project_dir = tmp_path / "point-not-so-mid"
    subdir = project_dir / "backend"
    subdir.mkdir(parents=True)
    config.add_project("point-not-so-mid", str(project_dir))

    monkeypatch.chdir(subdir)
    assert cli.main(["init"]) == 0
    capsys.readouterr()

    assert {p["name"]: p["path"] for p in config.list_projects()} == {
        "point-not-so-mid": str(project_dir),
        "backend": str(subdir),
    }


def test_first_session_in_a_subdirectory_registers_the_repo_not_the_subdirectory(
    tmp_path, monkeypatch
):
    # The other half of the same bug: nothing is tracked yet, so
    # enclosing_project can't help -- without a notion of the repo, the
    # subdirectory's own name is what the project gets called forever.
    repo = tmp_path / "point-not-so-mid"
    subdir = repo / "backend"
    subdir.mkdir(parents=True)
    (repo / ".git").mkdir()

    monkeypatch.chdir(subdir)
    assert cli.main(["done", "wired up the API"]) == 0

    assert [(p["name"], p["path"]) for p in config.list_projects()] == [
        ("point-not-so-mid", str(repo))
    ]
    assert [i["text"] for i in project_store.all_items(repo)] == ["wired up the API"]


def test_directory_outside_any_repo_is_still_registered_as_itself(tmp_path, monkeypatch):
    # Not every project folder is a git repo -- those keep working the
    # way they did, registered under their own name.
    project_dir = tmp_path / "Grocery Shopping"
    project_dir.mkdir()

    monkeypatch.chdir(project_dir)
    assert cli.main(["done", "planned the week"]) == 0

    assert [p["path"] for p in config.list_projects()] == [str(project_dir)]


def test_dotfiles_repo_at_home_does_not_swallow_projects_beneath_it(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".git").mkdir(parents=True)
    project_dir = home / "a-timeline"
    project_dir.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    monkeypatch.chdir(project_dir)
    assert cli.main(["done", "sketched the timeline"]) == 0

    assert [(p["name"], p["path"]) for p in config.list_projects()] == [
        ("a-timeline", str(project_dir))
    ]


def test_logs_go_to_the_session_directory_not_the_shells_cwd(tmp_path, monkeypatch):
    # The way this actually happened: the session was opened in the
    # project, then the agent cd'd into a subdirectory to work and
    # logged from there.
    repo = tmp_path / "point-not-so-mid"
    subdir = repo / "backend"
    subdir.mkdir(parents=True)
    (repo / ".git").mkdir()
    monkeypatch.setattr(cli.process_utils, "claude_session_cwd", lambda: repo)

    monkeypatch.chdir(subdir)
    assert cli.main(["done", "wired up the API"]) == 0

    assert [(p["name"], p["path"]) for p in config.list_projects()] == [
        ("point-not-so-mid", str(repo))
    ]
    assert [i["text"] for i in project_store.all_items(repo)] == ["wired up the API"]


def test_logs_from_the_session_scratchpad_still_reach_the_project(tmp_path, monkeypatch):
    # Same failure, different destination: the agent cd's into its
    # scratchpad under /tmp, which isn't inside the project at all.
    repo = tmp_path / "point-not-so-mid"
    repo.mkdir()
    (repo / ".git").mkdir()
    scratchpad = tmp_path / "scratch" / "scratchpad"
    scratchpad.mkdir(parents=True)
    monkeypatch.setattr(cli.process_utils, "claude_session_cwd", lambda: repo)

    monkeypatch.chdir(scratchpad)
    assert cli.main(["done", "ran the script"]) == 0

    assert [p["path"] for p in config.list_projects()] == [str(repo)]
    assert not (scratchpad / ".claude-dashboard").exists()


def test_session_started_in_home_falls_back_to_the_working_directory(tmp_path, monkeypatch):
    # $HOME identifies no project, so the directory actually being
    # worked in is the better guess -- the pre-existing behaviour.
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setattr(cli.process_utils, "claude_session_cwd", lambda: home)
    project_dir = home / "a-timeline"
    project_dir.mkdir()

    monkeypatch.chdir(project_dir)
    assert cli.main(["done", "sketched the timeline"]) == 0

    assert [p["path"] for p in config.list_projects()] == [str(project_dir)]
