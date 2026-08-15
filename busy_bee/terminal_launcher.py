"""Click-to-resume: if a `claude` process is already running in this
project's directory in some open Terminal tab, focuses that tab
(that's the "same window" the user actually wants back). Only if no
such session exists does it open a new window and start one with
`claude --continue`.

Detection works by asking Terminal.app for every open tab's tty, then
checking which processes are attached to each tty and reading the cwd
of any `claude` process found there via lsof. iTerm isn't supported
for reuse detection (its scripting model differs enough to need
separate handling) -- it always opens a new window.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

LIST_TABS_APPLESCRIPT = """
tell application "Terminal"
    set output to ""
    repeat with w in windows
        set winId to id of w
        set tabCount to count of tabs of w
        repeat with i from 1 to tabCount
            set ttyName to tty of tab i of w
            set output to output & winId & "|" & i & "|" & ttyName & linefeed
        end repeat
    end repeat
    return output
end tell
"""

FOCUS_TAB_APPLESCRIPT = """
tell application "Terminal"
    activate
    set targetWindow to (first window whose id is {window_id})
    set selected tab of targetWindow to tab {tab_index} of targetWindow
    set index of targetWindow to 1
end tell
"""

NEW_TERMINAL_WINDOW_APPLESCRIPT = """
tell application "Terminal"
    activate
    do script "cd {path} && claude --continue"
end tell
"""

NEW_ITERM_WINDOW_APPLESCRIPT = """
tell application "iTerm"
    activate
    set newWindow to (create window with default profile)
    tell current session of newWindow
        write text "cd {path} && claude --continue"
    end tell
end tell
"""


def _list_terminal_tabs() -> list[dict]:
    result = subprocess.run(
        ["osascript", "-e", LIST_TABS_APPLESCRIPT], capture_output=True, text=True
    )
    if result.returncode != 0:
        return []
    tabs = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("|")
        if len(parts) != 3:
            continue
        window_id, tab_index, tty = parts
        tabs.append({"window_id": window_id, "tab_index": tab_index, "tty": tty})
    return tabs


def _claude_cwd_for_tty(tty: str) -> str | None:
    """If a `claude` process is attached to this tty, returns its cwd."""
    tty_device = tty.replace("/dev/", "")
    ps = subprocess.run(
        ["ps", "-t", tty_device, "-o", "pid=,command="], capture_output=True, text=True
    )
    if ps.returncode != 0:
        return None

    claude_pid = None
    for line in ps.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        pid, _, command = line.partition(" ")
        if command and Path(command.split()[0]).name == "claude":
            claude_pid = pid
            break
    if claude_pid is None:
        return None

    lsof = subprocess.run(
        ["lsof", "-a", "-p", claude_pid, "-d", "cwd", "-Fn"], capture_output=True, text=True
    )
    if lsof.returncode != 0:
        return None
    for line in lsof.stdout.splitlines():
        if line.startswith("n"):
            return line[1:]
    return None


def find_existing_session(path: str) -> dict | None:
    """Returns the {window_id, tab_index} of a Terminal tab already
    running `claude` in `path`, or None if there isn't one."""
    for tab in _list_terminal_tabs():
        if _claude_cwd_for_tty(tab["tty"]) == path:
            return tab
    return None


def _focus_terminal_tab(window_id: str, tab_index: str) -> None:
    script = FOCUS_TAB_APPLESCRIPT.format(window_id=window_id, tab_index=tab_index)
    subprocess.run(["osascript", "-e", script], check=True)


def resume_project(path: str, terminal_app: str = "Terminal") -> None:
    resolved_path = str(Path(path).resolve())

    if terminal_app.lower() == "terminal":
        existing = find_existing_session(resolved_path)
        if existing is not None:
            _focus_terminal_tab(existing["window_id"], existing["tab_index"])
            return

    quoted_path = shlex.quote(resolved_path)
    script = (
        NEW_ITERM_WINDOW_APPLESCRIPT
        if terminal_app.lower() == "iterm"
        else NEW_TERMINAL_WINDOW_APPLESCRIPT
    ).format(path=quoted_path)
    subprocess.run(["osascript", "-e", script], check=True)
