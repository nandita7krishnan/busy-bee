#!/usr/bin/env python3
"""Claude Code `SessionStart` hook -- logs a 'session_start' marker the
moment a new session begins, before it's done anything else.

Closes a gap the Stop hook's session-scoping can't: a brand new session
in a terminal tty the OS just reused (its previous occupant now closed)
has no items of its own yet, so every "most recent session_id logged
for this tty" lookup still resolves to the old, unrelated session --
the dashboard shows that old session's title and todo list until the
new one gets around to logging something itself. This hook closes that
window by recording the new session_id as early as possible.

Wire it up in the project's .claude/settings.json:

{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 /path/to/busy-bee/hooks/session_start_hook.py"
          }
        ]
      }
    ]
  }
}
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from busy_bee import project_store  # noqa: E402


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}

    cwd = payload.get("cwd") or str(Path.cwd())
    project_root = Path(cwd)

    status_file = project_root / ".claude-dashboard" / "status.json"
    if not status_file.exists():
        # Project isn't tracked by busy-bee -- nothing to enforce.
        return 0

    project_store.mark_session_start(project_root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
