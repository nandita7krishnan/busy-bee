from busy_bee import terminal_launcher as tl


class FakeResult:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


def test_list_terminal_tabs_parses_osascript_output(monkeypatch):
    def fake_run(cmd, capture_output, text):
        return FakeResult(stdout="437|1|/dev/ttys001\n1226|2|/dev/ttys002\n")

    monkeypatch.setattr(tl.subprocess, "run", fake_run)
    tabs = tl._list_terminal_tabs()
    assert tabs == [
        {"window_id": "437", "tab_index": "1", "tty": "/dev/ttys001"},
        {"window_id": "1226", "tab_index": "2", "tty": "/dev/ttys002"},
    ]


def test_list_terminal_tabs_returns_empty_on_failure(monkeypatch):
    monkeypatch.setattr(tl.subprocess, "run", lambda *a, **k: FakeResult(returncode=1))
    assert tl._list_terminal_tabs() == []


def test_tty_has_live_claude_true_when_claude_attached(monkeypatch):
    monkeypatch.setattr(
        tl.subprocess, "run", lambda cmd, **k: FakeResult(stdout="-zsh\nclaude\n")
    )
    assert tl._tty_has_live_claude("ttys002") is True


def test_tty_has_live_claude_false_without_claude(monkeypatch):
    monkeypatch.setattr(tl.subprocess, "run", lambda cmd, **k: FakeResult(stdout="-zsh\n"))
    assert tl._tty_has_live_claude("ttys003") is False


def test_find_tab_by_tty_normalizes_dev_prefix(monkeypatch):
    monkeypatch.setattr(
        tl,
        "_list_terminal_tabs",
        lambda: [{"window_id": "9", "tab_index": "2", "tty": "/dev/ttys002"}],
    )
    assert tl._find_tab_by_tty("ttys002") == {
        "window_id": "9",
        "tab_index": "2",
        "tty": "/dev/ttys002",
    }
    assert tl._find_tab_by_tty("ttys999") is None


def test_resume_project_focuses_existing_session_when_tty_alive(monkeypatch):
    focused = {}
    monkeypatch.setattr(tl, "_tty_has_live_claude", lambda tty: True)
    monkeypatch.setattr(
        tl, "_find_tab_by_tty", lambda tty: {"window_id": "9", "tab_index": "2"}
    )
    monkeypatch.setattr(
        tl, "_focus_terminal_tab", lambda wid, idx: focused.update(window_id=wid, tab_index=idx)
    )

    def fail_if_called(cmd, **k):
        raise AssertionError("should not open a new window when a live session exists")

    monkeypatch.setattr(tl.subprocess, "run", fail_if_called)

    tl.resume_project("/Users/me/my-project", tty="ttys002")
    assert focused == {"window_id": "9", "tab_index": "2"}


def test_resume_project_opens_new_window_when_no_tty_recorded(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(tl.subprocess, "run", lambda cmd, **k: calls.append(cmd) or FakeResult())

    tl.resume_project(str(tmp_path), tty=None)
    assert len(calls) == 1
    assert calls[0][0] == "osascript"
    assert "claude --continue" in calls[0][2]


def test_resume_project_opens_new_window_when_tty_is_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(tl, "_tty_has_live_claude", lambda tty: False)

    def fail_if_focus_attempted(*a, **k):
        raise AssertionError("should not try to focus a dead tty")

    monkeypatch.setattr(tl, "_find_tab_by_tty", fail_if_focus_attempted)

    calls = []
    monkeypatch.setattr(tl.subprocess, "run", lambda cmd, **k: calls.append(cmd) or FakeResult())

    tl.resume_project(str(tmp_path), tty="ttys002")
    assert len(calls) == 1
    assert "claude --continue" in calls[0][2]


def test_resume_project_ignores_tty_for_iterm(tmp_path, monkeypatch):
    def fail_if_called(*a, **k):
        raise AssertionError("tty reuse detection is Terminal.app-only")

    monkeypatch.setattr(tl, "_tty_has_live_claude", fail_if_called)

    calls = []
    monkeypatch.setattr(tl.subprocess, "run", lambda cmd, **k: calls.append(cmd) or FakeResult())

    tl.resume_project(str(tmp_path), terminal_app="iTerm", tty="ttys002")
    assert len(calls) == 1
    assert "iTerm" in calls[0][2]
