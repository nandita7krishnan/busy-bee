"""Finds which terminal tty the current process is actually running
inside, by walking up its parent chain to the nearest ancestor process
named `claude`.

This exists because Claude Code's Bash tool doesn't give its
subprocesses a real controlling terminal (each command runs as a
detached `/bin/zsh -c '...'` with no tty of its own), and the top-level
`claude` process's own reported cwd doesn't move when the Bash tool
`cd`s around (that's tracked internally by Claude Code, not at the OS
level) -- so neither the dashctl subprocess's own tty nor `claude`'s
cwd can identify which terminal a status log came from. Its process
ancestry can: every Bash tool subprocess is a descendant of the one
`claude` process for that terminal tab, regardless of directory or its
own tty. dashctl records the result so terminal_launcher can later
focus that same tab instead of opening a new one.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta, timezone


def _ppid_and_comm(pid: str) -> tuple[str, str] | None:
    result = subprocess.run(["ps", "-o", "ppid=,comm=", "-p", pid], capture_output=True, text=True)
    line = result.stdout.strip()
    if not line:
        return None
    ppid, _, comm = line.partition(" ")
    return ppid.strip(), comm.strip()


def find_claude_ancestor_tty(max_hops: int = 20) -> str | None:
    """Returns the bare tty device name (e.g. "ttys002") of the nearest
    ancestor process named `claude`, or None if there isn't one (e.g.
    dashctl was run outside a Claude Code session)."""
    pid = str(os.getpid())
    for _ in range(max_hops):
        info = _ppid_and_comm(pid)
        if info is None:
            return None
        ppid, comm = info
        if comm.rsplit("/", 1)[-1] == "claude":
            result = subprocess.run(["ps", "-o", "tty=", "-p", pid], capture_output=True, text=True)
            tty = result.stdout.strip()
            return tty if tty and tty != "??" else None
        if not ppid or ppid in ("0", "1"):
            return None
        pid = ppid
    return None


def current_session_id() -> str | None:
    """The Claude Code session id (a UUID Claude Code assigns per
    invocation, distinct even across two `claude` runs in the same
    terminal tty), from the CLAUDE_CODE_SESSION_ID env var it sets on
    every process it spawns. Used to scope "this session's" history so
    a fresh session doesn't inherit an unrelated old session's items
    just because the OS happened to reuse the same tty."""
    return os.environ.get("CLAUDE_CODE_SESSION_ID")


def live_claude_ttys() -> set[str]:
    """Every tty device name that currently has a running `claude`
    process attached. Used to tell whether a previously-logged session
    is still open or the terminal it ran in has since closed --
    process state, not a time-since-last-log guess."""
    result = subprocess.run(["ps", "-eo", "tty=,comm="], capture_output=True, text=True)
    ttys: set[str] = set()
    for line in result.stdout.splitlines():
        tty, _, comm = line.strip().partition(" ")
        tty = tty.strip()
        comm = comm.strip()
        if not tty or tty == "??":
            continue
        if comm.rsplit("/", 1)[-1] == "claude":
            ttys.add(tty)
    return ttys


def _parse_etime(value: str) -> timedelta | None:
    """Parses `ps -o etime` ("[[dd-]hh:]mm:ss") into a timedelta.

    Elapsed time rather than `ps -o lstart`, whose output is a
    locale- and timezone-dependent string ("Mon Aug 18 15:03:33 2026")
    that has to be parsed back into an aware datetime to be compared
    with anything; subtracting an elapsed time from `now` sidesteps
    both."""
    days = 0
    if "-" in value:
        day_part, _, value = value.partition("-")
        try:
            days = int(day_part)
        except ValueError:
            return None
    parts = value.split(":")
    if len(parts) == 2:
        parts = ["0", *parts]
    if len(parts) != 3:
        return None
    try:
        hours, minutes, seconds = (int(p) for p in parts)
    except ValueError:
        return None
    return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)


def claude_session_start_times() -> dict[str, str]:
    """When the `claude` process currently attached to each live tty
    started, as an ISO8601 UTC timestamp.

    Lets callers tell a still-relevant log from a leftover one on a
    *reused* tty: macOS hands the same tty device (ttys013, say) to a
    new terminal window once the previous occupant closes, so items
    logged by that earlier, long-gone session are still on file against
    this tty. Anything logged before the tty's current `claude` process
    even existed belongs to that dead session, whatever project it was
    for -- which is how a brand new session in an untracked directory
    used to resurrect an unrelated project's old session card (and get
    its terminal painted that project's color).

    The *earliest* start time wins when a tty has more than one
    `claude` on it (a nested/sub-session shouldn't shorten the window
    its parent's items are judged against). Ttys whose elapsed time
    can't be parsed are simply left out, so callers fall back to their
    previous, unfiltered behaviour rather than dropping a live session."""
    result = subprocess.run(["ps", "-eo", "tty=,etime=,comm="], capture_output=True, text=True)
    now = datetime.now(timezone.utc)
    starts: dict[str, datetime] = {}
    for line in result.stdout.splitlines():
        parts = line.strip().split(maxsplit=2)
        if len(parts) != 3:
            continue
        tty, etime, comm = parts
        if tty == "??" or comm.rsplit("/", 1)[-1] != "claude":
            continue
        elapsed = _parse_etime(etime)
        if elapsed is None:
            continue
        started = now - elapsed
        if tty not in starts or started < starts[tty]:
            starts[tty] = started
    return {tty: dt.isoformat() for tty, dt in starts.items()}


def logged_before_session_start(created_at: str, session_started_at: str | None) -> bool:
    """Was an item logged before the `claude` process currently on its
    tty started -- i.e. by an earlier session that has since exited and
    left its tty number to be reused?

    False whenever the start time is unknown or either timestamp is
    unparseable: every caller uses this to hide or resolve something, so
    an unreadable timestamp should mean "leave it alone", never "assume
    it's stale"."""
    if session_started_at is None:
        return False
    try:
        return datetime.fromisoformat(created_at) < datetime.fromisoformat(session_started_at)
    except (TypeError, ValueError):
        return False

