#!/usr/bin/env python3
"""Claude Code `UserPromptSubmit` hook -- clears this session's open
blockers/questions the moment the user replies to it.

A blocker/question on the dashboard means "this session is waiting on
you right now", and the tray + Dock badge is built on that reading. The
moment you send a message, it isn't true any more -- but until this
hook existed, nothing cleared the flag promptly. `dashctl resolve`
depends on the agent remembering, and the Stop hook can only nudge for
it once the *next* turn ends, which is however long that turn takes;
auto_resolve_dead_sessions deliberately waits for the session to end
entirely. So a question answered eight minutes ago kept the badge red,
which is exactly the failure the badge is supposed to make impossible.

Scoped to the session that's being replied to (payload `session_id`),
not the whole project: with two live sessions in one project, answering
one shouldn't clear the other's flags.

This makes the Stop hook's stale_flags_awaiting_resolve nudge go quiet
in normal operation -- it's kept as the safety net for sessions this
hook never ran in (installed mid-session, or a machine where only some
of the hooks landed).

Emits nothing on stdout: for UserPromptSubmit specifically, stdout on a
zero exit is injected into the model's context as extra prompt content,
so anything printed here would end up in the conversation.

Wire it up in the project's .claude/settings.json:

{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 /path/to/busy-bee/hooks/user_prompt_submit_hook.py"
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

from busy_bee import config, process_utils, project_store  # noqa: E402


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}

    cwd = payload.get("cwd") or str(Path.cwd())
    # A session opened in a subdirectory is still working on the
    # project that contains it -- its flags live in that project's
    # store, not in a .claude-dashboard of the subdirectory's own.
    project_root = config.project_root_for(cwd)

    if not (project_root / ".claude-dashboard" / "status.json").exists():
        # Project isn't tracked by busy-bee -- no flags to clear.
        return 0

    # Payload first, env var as the fallback: the hook process is
    # spawned by Claude Code so CLAUDE_CODE_SESSION_ID is normally set
    # too, but the payload is the authoritative copy. Without a session
    # id there's no safe scope to resolve within -- clearing every
    # unresolved flag in the project would take out other terminals'
    # too -- so do nothing rather than guess.
    session_id = payload.get("session_id") or process_utils.current_session_id()
    if not session_id:
        return 0

    project_store.resolve_flags_on_user_reply(project_root, session_id)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        # This hook sits between the user pressing enter and their
        # message being processed. Nothing it does is important enough
        # to be worth an error in front of every single prompt, so any
        # failure degrades to "the flag stays up", which is just the
        # old behaviour.
        print(f"busy-bee: could not clear session flags: {exc!r}", file=sys.stderr)
        sys.exit(0)
