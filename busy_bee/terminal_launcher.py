"""Click-to-resume: if the tty recorded for this project (see
process_utils.py / project_store.latest_terminal_tty) still has a live
`claude` process attached, focuses that Terminal tab -- that's the
existing conversation the user actually wants back. Only opens a new
window and starts a fresh `claude --continue` if there's no recorded
tty, or the process on it is gone.

iTerm isn't supported for reuse detection (its scripting model differs
enough to need separate handling) -- it always opens a new window.
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


def _tty_has_live_claude(tty: str) -> bool:
    tty_device = tty.replace("/dev/", "")
    result = subprocess.run(["ps", "-t", tty_device, "-o", "comm="], capture_output=True, text=True)
    if result.returncode != 0:
        return False
    return any(Path(line.strip()).name == "claude" for line in result.stdout.splitlines())


def _find_tab_by_tty(tty: str) -> dict | None:
    tty_device = tty.replace("/dev/", "")
    for tab in _list_terminal_tabs():
        if tab["tty"].replace("/dev/", "") == tty_device:
            return tab
    return None


def _focus_terminal_tab(window_id: str, tab_index: str) -> None:
    script = FOCUS_TAB_APPLESCRIPT.format(window_id=window_id, tab_index=tab_index)
    subprocess.run(["osascript", "-e", script], check=True)


def resume_project(path: str, terminal_app: str = "Terminal", tty: str | None = None) -> None:
    if terminal_app.lower() == "terminal" and tty and _tty_has_live_claude(tty):
        tab = _find_tab_by_tty(tty)
        if tab is not None:
            _focus_terminal_tab(tab["window_id"], tab["tab_index"])
            return

    resolved_path = str(Path(path).resolve())
    quoted_path = shlex.quote(resolved_path)
    script = (
        NEW_ITERM_WINDOW_APPLESCRIPT
        if terminal_app.lower() == "iterm"
        else NEW_TERMINAL_WINDOW_APPLESCRIPT
    ).format(path=quoted_path)
    subprocess.run(["osascript", "-e", script], check=True)
