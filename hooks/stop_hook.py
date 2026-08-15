#!/usr/bin/env python3
"""Claude Code `Stop` hook -- the safety net described in the PRD.

Fires at the end of a turn. If nothing was logged to dashctl recently,
it blocks the stop and asks the agent to log a one-line status first,
so tracking doesn't depend on the agent remembering unprompted.

Wire it up in the project's .claude/settings.json:

{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 /path/to/busy-bee/hooks/stop_hook.py"
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

RECENT_WINDOW_SECONDS = 120


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}

    # Avoid looping forever: if this hook already fired once and blocked
    # the stop this turn, don't block it again.
    if payload.get("stop_hook_active"):
        return 0

    cwd = payload.get("cwd") or str(Path.cwd())
    project_root = Path(cwd)

    status_file = project_root / ".claude-dashboard" / "status.json"
    if not status_file.exists():
        # Project isn't tracked by busy-bee -- nothing to enforce.
        return 0

    if project_store.has_logged_this_turn(project_root, since_seconds=RECENT_WINDOW_SECONDS):
        return 0

    print(
        json.dumps(
            {
                "decision": "block",
                "reason": (
                    "Before finishing, log a one-line status with dashctl: "
                    "`dashctl done \"...\"`, `dashctl todo \"...\"`, "
                    "`dashctl blocker \"...\"`, or `dashctl question \"...\"`."
                ),
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
