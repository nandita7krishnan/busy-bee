"""One-time global wiring, run once via `dashctl setup-global`.

Instead of pasting the CLAUDE.md snippet and wiring the Stop hook into
every tracked project individually, this installs both at the Claude
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


def install_stop_hook(python_path: str = "python3") -> str:
    command = f"{python_path} {STOP_HOOK_PATH}"

    settings: dict = {}
    if SETTINGS_PATH.exists():
        settings = json.loads(SETTINGS_PATH.read_text())

    hooks = settings.setdefault("hooks", {})
    stop_hooks = hooks.setdefault("Stop", [])

    for entry in stop_hooks:
        for h in entry.get("hooks", []):
            if h.get("command") == command:
                return f"already present in {SETTINGS_PATH}"

    stop_hooks.append({"hooks": [{"type": "command", "command": command}]})
    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2) + "\n")
    return f"added to {SETTINGS_PATH}"


def main() -> int:
    print(f"CLAUDE.md snippet: {install_claude_md_snippet()}")
    print(f"Stop hook: {install_stop_hook()}")
    print()
    print("Every Claude Code session on this machine will now log status to")
    print("busy-bee, and dashctl auto-registers a project the first time it")
    print("logs anything -- no more per-project `dashctl init` needed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
