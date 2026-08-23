#!/usr/bin/env python3
"""Claude Code `SessionStart` hook -- registers the directory a new
session opens in (if it isn't tracked yet) and logs a 'session_start'
marker, before the session has done anything else.

Closes a gap the Stop hook's session-scoping can't: a brand new session
in a terminal tty the OS just reused (its previous occupant now closed)
has no items of its own yet, so every "most recent session_id logged
for this tty" lookup still resolves to the old, unrelated session --
the dashboard shows that old session's title and todo list until the
new one gets around to logging something itself. This hook closes that
window by recording the new session_id as early as possible.

It registers untracked directories rather than skipping them, which is
the same gap seen from the other side: a session opening in a
not-yet-tracked project used to log nothing at all, so the reused tty
stayed attributed to whichever *other* project last logged from it --
the dashboard grew a stale session card (and painted the new terminal)
under that unrelated project instead of showing a new card for the
directory actually being worked in. Registering here means a project
appears the moment work starts in it, not on its first `dashctl` call.

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

from busy_bee import config, project_store  # noqa: E402


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}

    cwd = payload.get("cwd") or str(Path.cwd())
    project_root = Path(cwd).expanduser().resolve()

    # Same rule the `dashctl` log commands use, so both entry points
    # track (and skip) exactly the same directories.
    config.auto_register(project_root)
    if project_root not in {Path(p["path"]) for p in config.list_projects()}:
        # Deliberately not tracked (notably $HOME, which isn't a
        # project) -- nothing to log against.
        return 0

    project_store.mark_session_start(project_root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
