"""Syncs Claude Code's own TodoWrite tool state into dashctl, so the
Next column reflects the agent's actual internal plan instead of
depending on it separately remembering to call `dashctl todo` for the
same items.

Called from a PostToolUse hook matched to the TodoWrite tool (see
hooks/todo_sync_hook.py). Diffs against a small per-project state file
to avoid re-logging the same item every time TodoWrite runs -- agents
call it frequently, each time with the full current list, not just
the delta.

Only syncs into projects already tracked (status.json already exists)
-- doesn't auto-register a directory just because TodoWrite happened
to run there. In practice a project gets tracked within the first
turn anyway (the Stop hook forces some dashctl call), so this only
skips the rare case where TodoWrite fires before anything else has.
"""

from __future__ import annotations

import json
from pathlib import Path

from busy_bee import project_store

STATE_FILENAME = "todo_sync_state.json"


def _state_path(project_root: Path) -> Path:
    return project_root / ".claude-dashboard" / STATE_FILENAME


def _load_state(project_root: Path) -> dict[str, str]:
    path = _state_path(project_root)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(project_root: Path, state: dict[str, str]) -> None:
    path = _state_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))


def is_tracked(project_root: Path) -> bool:
    return (project_root / ".claude-dashboard" / "status.json").exists()


def sync_todos(project_root: Path, todos: list[dict]) -> None:
    if not is_tracked(project_root):
        return

    state = _load_state(project_root)

    for entry in todos:
        content = (entry.get("content") or "").strip()
        status = entry.get("status")
        if not content or status not in ("pending", "in_progress", "completed"):
            continue

        previous = state.get(content)
        if status == "completed":
            if previous != "completed":
                project_store.add_item(project_root, "done", content)
            state[content] = "completed"
        elif previous is None:
            project_store.add_item(project_root, "todo", content)
            state[content] = status
        else:
            state[content] = status

    _save_state(project_root, state)
