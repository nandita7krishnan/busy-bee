"""Click-to-resume: opens a terminal, cds into the project, and resumes
the Claude Code session with `claude --continue`.
"""

from __future__ import annotations

import shlex
import subprocess

TERMINAL_APPLESCRIPT = """
tell application "Terminal"
    activate
    do script "cd {path} && claude --continue"
end tell
"""

ITERM_APPLESCRIPT = """
tell application "iTerm"
    activate
    set newWindow to (create window with default profile)
    tell current session of newWindow
        write text "cd {path} && claude --continue"
    end tell
end tell
"""


def resume_project(path: str, terminal_app: str = "Terminal") -> None:
    quoted_path = shlex.quote(path)
    script = (ITERM_APPLESCRIPT if terminal_app.lower() == "iterm" else TERMINAL_APPLESCRIPT).format(
        path=quoted_path
    )
    subprocess.run(["osascript", "-e", script], check=True)
