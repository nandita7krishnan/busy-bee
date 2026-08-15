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


def test_claude_cwd_for_tty_finds_claude_process(monkeypatch):
    calls = []

    def fake_run(cmd, capture_output, text):
        calls.append(cmd)
        if cmd[0] == "ps":
            return FakeResult(stdout=" 4022 -zsh\n 4098 claude\n")
        if cmd[0] == "lsof":
            assert "4098" in cmd
            return FakeResult(stdout="p4098\nfcwd\nn/Users/me/my-project\n")
        raise AssertionError(f"unexpected command {cmd}")

    monkeypatch.setattr(tl.subprocess, "run", fake_run)
    assert tl._claude_cwd_for_tty("/dev/ttys000") == "/Users/me/my-project"


def test_claude_cwd_for_tty_returns_none_without_claude_process(monkeypatch):
    monkeypatch.setattr(
        tl.subprocess, "run", lambda cmd, **k: FakeResult(stdout=" 9891 -zsh\n")
    )
    assert tl._claude_cwd_for_tty("/dev/ttys003") is None


def test_find_existing_session_matches_by_cwd(monkeypatch):
    monkeypatch.setattr(
        tl,
        "_list_terminal_tabs",
        lambda: [
            {"window_id": "1", "tab_index": "1", "tty": "/dev/ttys000"},
            {"window_id": "2", "tab_index": "1", "tty": "/dev/ttys001"},
        ],
    )
    cwds = {"/dev/ttys000": "/Users/me/other-project", "/dev/ttys001": "/Users/me/my-project"}
    monkeypatch.setattr(tl, "_claude_cwd_for_tty", lambda tty: cwds.get(tty))

    result = tl.find_existing_session("/Users/me/my-project")
    assert result == {"window_id": "2", "tab_index": "1", "tty": "/dev/ttys001"}


def test_find_existing_session_returns_none_when_no_match(monkeypatch):
    monkeypatch.setattr(tl, "_list_terminal_tabs", lambda: [])
    assert tl.find_existing_session("/Users/me/my-project") is None


def test_resume_project_focuses_existing_session(monkeypatch):
    focused = {}
    monkeypatch.setattr(
        tl, "find_existing_session", lambda path: {"window_id": "9", "tab_index": "2"}
    )
    monkeypatch.setattr(
        tl, "_focus_terminal_tab", lambda wid, idx: focused.update(window_id=wid, tab_index=idx)
    )

    def fail_if_called(cmd, **k):
        raise AssertionError("should not open a new window when a session already exists")

    monkeypatch.setattr(tl.subprocess, "run", fail_if_called)

    tl.resume_project("/Users/me/my-project")
    assert focused == {"window_id": "9", "tab_index": "2"}


def test_resume_project_opens_new_window_when_no_existing_session(monkeypatch, tmp_path):
    monkeypatch.setattr(tl, "find_existing_session", lambda path: None)
    calls = []
    monkeypatch.setattr(tl.subprocess, "run", lambda cmd, **k: calls.append(cmd))

    tl.resume_project(str(tmp_path))
    assert len(calls) == 1
    assert calls[0][0] == "osascript"
    assert "claude --continue" in calls[0][2]
