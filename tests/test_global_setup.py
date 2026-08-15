import json

import pytest

from busy_bee import global_setup


@pytest.fixture(autouse=True)
def isolated_claude_dir(tmp_path, monkeypatch):
    claude_dir = tmp_path / ".claude"
    monkeypatch.setattr(global_setup, "CLAUDE_DIR", claude_dir)
    monkeypatch.setattr(global_setup, "CLAUDE_MD_PATH", claude_dir / "CLAUDE.md")
    monkeypatch.setattr(global_setup, "SETTINGS_PATH", claude_dir / "settings.json")
    yield


def test_install_claude_md_snippet_creates_file():
    result = global_setup.install_claude_md_snippet()
    assert "appended" in result
    content = global_setup.CLAUDE_MD_PATH.read_text()
    assert global_setup.MARKER_START in content
    assert global_setup.MARKER_END in content
    assert "busy-bee status tracking" in content


def test_install_claude_md_snippet_preserves_existing_content():
    global_setup.CLAUDE_DIR.mkdir(parents=True)
    global_setup.CLAUDE_MD_PATH.write_text("# My existing preferences\n\nSome notes here.\n")

    global_setup.install_claude_md_snippet()

    content = global_setup.CLAUDE_MD_PATH.read_text()
    assert "My existing preferences" in content
    assert "Some notes here." in content
    assert global_setup.MARKER_START in content


def test_install_claude_md_snippet_is_idempotent():
    global_setup.install_claude_md_snippet()
    first = global_setup.CLAUDE_MD_PATH.read_text()
    result = global_setup.install_claude_md_snippet()
    second = global_setup.CLAUDE_MD_PATH.read_text()

    assert "updated" in result
    assert first == second
    assert first.count(global_setup.MARKER_START) == 1


def test_install_stop_hook_creates_settings():
    result = global_setup.install_stop_hook(python_path="python3")
    assert "added" in result

    settings = json.loads(global_setup.SETTINGS_PATH.read_text())
    commands = [
        h["command"]
        for entry in settings["hooks"]["Stop"]
        for h in entry["hooks"]
    ]
    assert any("stop_hook.py" in c for c in commands)


def test_install_stop_hook_preserves_other_hooks():
    global_setup.CLAUDE_DIR.mkdir(parents=True)
    global_setup.SETTINGS_PATH.write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [{"hooks": [{"type": "command", "command": "some-other-hook"}]}]
                },
                "otherSetting": True,
            }
        )
    )

    global_setup.install_stop_hook(python_path="python3")

    settings = json.loads(global_setup.SETTINGS_PATH.read_text())
    assert settings["otherSetting"] is True
    commands = [
        h["command"]
        for entry in settings["hooks"]["Stop"]
        for h in entry["hooks"]
    ]
    assert "some-other-hook" in commands
    assert any("stop_hook.py" in c for c in commands)


def test_install_stop_hook_is_idempotent():
    global_setup.install_stop_hook(python_path="python3")
    result = global_setup.install_stop_hook(python_path="python3")
    assert "already present" in result

    settings = json.loads(global_setup.SETTINGS_PATH.read_text())
    assert len(settings["hooks"]["Stop"]) == 1
