from datetime import datetime, timedelta, timezone
from pathlib import Path

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


def test_claude_session_start_times_subtracts_elapsed_time(monkeypatch):
    monkeypatch.setattr(
        pu.subprocess,
        "run",
        lambda cmd, **k: FakeResult(stdout="ttys001    05:00 claude\n"),
    )
    now = datetime.now(timezone.utc)

    started = datetime.fromisoformat(pu.claude_session_start_times()["ttys001"])

    assert timedelta(minutes=4, seconds=55) <= now - started <= timedelta(minutes=5, seconds=5)


def test_claude_session_start_times_parses_hours_and_days(monkeypatch):
    monkeypatch.setattr(
        pu.subprocess,
        "run",
        lambda cmd, **k: FakeResult(
            stdout="ttys001    01:02:03 claude\nttys002 2-03:00:00 claude\n"
        ),
    )
    now = datetime.now(timezone.utc)
    starts = pu.claude_session_start_times()

    assert abs((now - datetime.fromisoformat(starts["ttys001"])) - timedelta(hours=1, minutes=2, seconds=3)) < timedelta(seconds=5)
    assert abs((now - datetime.fromisoformat(starts["ttys002"])) - timedelta(days=2, hours=3)) < timedelta(seconds=5)


def test_claude_session_start_times_ignores_other_processes(monkeypatch):
    monkeypatch.setattr(
        pu.subprocess,
        "run",
        lambda cmd, **k: FakeResult(stdout="ttys001    05:00 -zsh\n??    05:00 claude\n"),
    )
    assert pu.claude_session_start_times() == {}


def test_claude_session_start_times_keeps_earliest_claude_on_a_tty(monkeypatch):
    # A nested/sub-`claude` on the same tty mustn't shorten the window
    # its parent session's items are judged against.
    monkeypatch.setattr(
        pu.subprocess,
        "run",
        lambda cmd, **k: FakeResult(stdout="ttys001 02:00:00 claude\nttys001    01:00 claude\n"),
    )
    now = datetime.now(timezone.utc)

    started = datetime.fromisoformat(pu.claude_session_start_times()["ttys001"])

    assert abs((now - started) - timedelta(hours=2)) < timedelta(seconds=5)


def test_claude_session_start_times_skips_unparseable_elapsed_time(monkeypatch):
    # Left out entirely rather than guessed at -- callers fall back to
    # their unfiltered behaviour instead of hiding a live session.
    monkeypatch.setattr(
        pu.subprocess,
        "run",
        lambda cmd, **k: FakeResult(stdout="ttys001 nonsense claude\n"),
    )
    assert pu.claude_session_start_times() == {}



def test_claude_session_cwd_reads_the_sessions_directory(monkeypatch):
    monkeypatch.setattr(pu, "find_claude_ancestor_pid", lambda: "4242")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return FakeResult(stdout="p4242\nfcwd\nn/Users/x/point-not-so-mid\n")

    monkeypatch.setattr(pu.subprocess, "run", fake_run)

    assert pu.claude_session_cwd() == Path("/Users/x/point-not-so-mid")
    assert "4242" in calls[0]


def test_claude_session_cwd_is_none_outside_a_session(monkeypatch):
    monkeypatch.setattr(pu, "find_claude_ancestor_pid", lambda: None)
    monkeypatch.delenv("CLAUDE_PID", raising=False)

    assert pu.claude_session_cwd() is None


def test_claude_session_cwd_survives_a_missing_lsof(monkeypatch):
    monkeypatch.setattr(pu, "find_claude_ancestor_pid", lambda: "4242")

    def boom(cmd, **kwargs):
        raise FileNotFoundError("lsof")

    monkeypatch.setattr(pu.subprocess, "run", boom)

    assert pu.claude_session_cwd() is None
