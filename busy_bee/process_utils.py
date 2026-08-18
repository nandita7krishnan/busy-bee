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
