"""One-time global wiring, run once via `dashctl setup-global`.

Instead of pasting the CLAUDE.md snippet and wiring the hooks into
every tracked project individually, this installs them at the Claude
Code *user* level (~/.claude/CLAUDE.md and ~/.claude/settings.json),
so every project on the machine gets them automatically. Combined with
dashctl auto-registering a project the first time it logs anything
(see cli.py), this means tracking a new side project requires zero
manual setup -- just start working in it.

Idempotent: safe to run more than once (e.g. after moving the repo, or
after a fresh Claude Code install wipes ~/.claude/settings.json).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"
CLAUDE_MD_PATH = CLAUDE_DIR / "CLAUDE.md"
SETTINGS_PATH = CLAUDE_DIR / "settings.json"

REPO_ROOT = Path(__file__).resolve().parent.parent
SNIPPET_PATH = REPO_ROOT / "claude_md_snippet.md"
STOP_HOOK_PATH = REPO_ROOT / "hooks" / "stop_hook.py"
TODO_SYNC_HOOK_PATH = REPO_ROOT / "hooks" / "todo_sync_hook.py"
SESSION_START_HOOK_PATH = REPO_ROOT / "hooks" / "session_start_hook.py"
USER_PROMPT_SUBMIT_HOOK_PATH = REPO_ROOT / "hooks" / "user_prompt_submit_hook.py"

MARKER_START = "<!-- busy-bee:start -->"
MARKER_END = "<!-- busy-bee:end -->"


def install_claude_md_snippet() -> str:
    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    snippet = SNIPPET_PATH.read_text().strip()
    block = f"{MARKER_START}\n{snippet}\n{MARKER_END}\n"

    existing = CLAUDE_MD_PATH.read_text() if CLAUDE_MD_PATH.exists() else ""
    if MARKER_START in existing and MARKER_END in existing:
        start = existing.index(MARKER_START)
        end = existing.index(MARKER_END) + len(MARKER_END)
        updated = existing[:start] + block + existing[end:].lstrip("\n")
        CLAUDE_MD_PATH.write_text(updated)
        return f"updated existing block in {CLAUDE_MD_PATH}"

    separator = "\n\n" if existing and not existing.endswith("\n\n") else ""
    CLAUDE_MD_PATH.write_text(existing + separator + block)
    return f"appended to {CLAUDE_MD_PATH}"


def _install_hook(event: str, command: str, matcher: str | None = None) -> str:
    settings: dict = {}
    if SETTINGS_PATH.exists():
        settings = json.loads(SETTINGS_PATH.read_text())

    hooks = settings.setdefault("hooks", {})
    event_hooks = hooks.setdefault(event, [])

    for entry in event_hooks:
        for h in entry.get("hooks", []):
            if h.get("command") == command:
                return f"already present in {SETTINGS_PATH}"

    entry = {"hooks": [{"type": "command", "command": command}]}
    if matcher is not None:
        entry["matcher"] = matcher
    event_hooks.append(entry)

    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2) + "\n")
    return f"added to {SETTINGS_PATH}"


def install_stop_hook(python_path: str = "python3") -> str:
    return _install_hook("Stop", f"{python_path} {STOP_HOOK_PATH}")


def install_todo_sync_hook(python_path: str = "python3") -> str:
    return _install_hook(
        "PostToolUse", f"{python_path} {TODO_SYNC_HOOK_PATH}", matcher="TodoWrite"
    )


def install_session_start_hook(python_path: str = "python3") -> str:
    return _install_hook("SessionStart", f"{python_path} {SESSION_START_HOOK_PATH}")


def install_user_prompt_submit_hook(python_path: str = "python3") -> str:
    return _install_hook(
        "UserPromptSubmit", f"{python_path} {USER_PROMPT_SUBMIT_HOOK_PATH}"
    )


def main() -> int:
    print(f"CLAUDE.md snippet: {install_claude_md_snippet()}")
    print(f"Stop hook: {install_stop_hook()}")
    print(f"TodoWrite sync hook: {install_todo_sync_hook()}")
    print(f"SessionStart hook: {install_session_start_hook()}")
    print(f"UserPromptSubmit hook: {install_user_prompt_submit_hook()}")
    print()
    print("Every Claude Code session on this machine will now log status to")
    print("busy-bee, and dashctl auto-registers a project the first time it")
    print("logs anything -- no more per-project `dashctl init` needed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
