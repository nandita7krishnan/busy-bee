#!/usr/bin/env python3
"""Claude Code PostToolUse hook, matched to the TodoWrite tool --
syncs the agent's own todo list into dashctl. See
busy_bee/todo_sync.py for the actual logic.

Wire it up in ~/.claude/settings.json (done automatically by
`dashctl setup-global` / global_setup.py):

{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "TodoWrite",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /path/to/busy-bee/hooks/todo_sync_hook.py"
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

from busy_bee import todo_sync  # noqa: E402


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    if payload.get("tool_name") != "TodoWrite":
        return 0

    todos = (payload.get("tool_input") or {}).get("todos")
    if not isinstance(todos, list):
        return 0

    cwd = payload.get("cwd") or str(Path.cwd())
    todo_sync.sync_todos(Path(cwd), todos)
    return 0


if __name__ == "__main__":
    sys.exit(main())
