from busy_bee import process_utils as pu


class FakeResult:
    def __init__(self, stdout=""):
        self.stdout = stdout


def test_live_claude_ttys_returns_ttys_running_claude(monkeypatch):
    monkeypatch.setattr(
        pu.subprocess,
        "run",
        lambda cmd, **k: FakeResult(
            stdout="ttys001 claude\nttys002 -zsh\nttys003 claude\n"
        ),
    )
    assert pu.live_claude_ttys() == {"ttys001", "ttys003"}


def test_live_claude_ttys_matches_claude_by_basename(monkeypatch):
    monkeypatch.setattr(
        pu.subprocess,
        "run",
        lambda cmd, **k: FakeResult(stdout="ttys001 /opt/homebrew/bin/claude\n"),
    )
    assert pu.live_claude_ttys() == {"ttys001"}


def test_live_claude_ttys_excludes_no_tty_processes(monkeypatch):
    monkeypatch.setattr(
        pu.subprocess,
        "run",
        lambda cmd, **k: FakeResult(stdout="?? claude\n"),
    )
    assert pu.live_claude_ttys() == set()


def test_live_claude_ttys_empty_when_none_running(monkeypatch):
    monkeypatch.setattr(pu.subprocess, "run", lambda cmd, **k: FakeResult(stdout=""))
    assert pu.live_claude_ttys() == set()
