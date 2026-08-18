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

from busy_bee import colors

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


_colored_ttys: set[str] = set()


def _hex_to_terminal_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    # Terminal.app's AppleScript color properties are 16-bit per
    # channel (0-65535), not the usual 8-bit (0-255).
    return r * 257, g * 257, b * 257


def color_tab(window_id: str, tab_index: str, hex_color: str) -> None:
    r, g, b = _hex_to_terminal_rgb(hex_color)
    rgb_list = "{%d, %d, %d}" % (r, g, b)
    script = f"""
tell application "Terminal"
    set background color of tab {tab_index} of (first window whose id is {window_id}) to {rgb_list}
end tell
"""
    subprocess.run(["osascript", "-e", script], check=True)


def prune_colored_ttys(live_ttys: set[str]) -> None:
    """Drops any tty that's no longer live from the colored set, so if
    that tty number gets reused by a later, unrelated terminal window,
    it gets colored fresh for whichever project that one belongs to."""
    _colored_ttys.intersection_update(live_ttys)


def sync_session_colors(project_name: str, live_ttys: list[str]) -> None:
    """Colors each of this project's currently-live Terminal tabs to
    match its dashboard card color, the first time we see it live -- a
    visual cue for which project a given terminal window belongs to.
    No-ops for ttys already colored this run, or that aren't an actual
    Terminal.app tab (iTerm isn't scriptable the same way here, and a
    dead tty has no window to find)."""
    color = None
    for tty in live_ttys:
        if tty in _colored_ttys:
            continue
        tab = _find_tab_by_tty(tty)
        if tab is None:
            continue
        if color is None:
            color = colors.project_color(project_name)
        color_tab(tab["window_id"], tab["tab_index"], color)
        _colored_ttys.add(tty)


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
