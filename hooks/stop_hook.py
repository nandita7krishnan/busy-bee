#!/usr/bin/env python3
"""Claude Code `Stop` hook -- the safety net described in the PRD.

Fires at the end of a turn. If nothing was logged to dashctl recently,
it blocks the stop and asks the agent to log a one-line status first,
so tracking doesn't depend on the agent remembering unprompted.

Also requires a `dashctl summary` specifically every SUMMARY_INTERVAL
turns, starting with the first -- left purely to the agent's judgment
("wrapping up a chunk of work"), a project's session header tended to
show Claude Code's own auto-generated tab title for a while before any
real summary showed up.

Also requires a `dashctl question` specifically whenever the turn ends
on a question awaiting the user's response (e.g. "want me to go ahead?").
Without this, a turn that already logged a `done`/`summary` earlier
satisfied the generic "something was logged" check below, so a trailing
question never got flagged and the dashboard never showed it -- the
agent's own judgment alone wasn't reliably catching this pattern.

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

from busy_bee import process_utils, project_store  # noqa: E402

RECENT_WINDOW_SECONDS = 120
SUMMARY_INTERVAL = 10  # every Nth turn, starting with the first

# Phrases that signal a turn is waiting on the user even without a
# trailing "?" (e.g. "Let me know how you'd like to proceed.").
_WAITING_PHRASES = ("let me know", "want me to", "should i", "shall i", "waiting on your")


def _last_assistant_text(transcript_path: str | None) -> str | None:
    """Best-effort read of the most recent assistant message's text
    from the session transcript (JSONL, newest entries last). Missing
    or unreadable transcripts just disable the question check below --
    everything else in this hook still runs."""
    if not transcript_path:
        return None
    path = Path(transcript_path)
    if not path.exists():
        return None
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "assistant":
            continue
        content = (entry.get("message") or {}).get("content") or []
        texts = [
            block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"
        ]
        text = "\n".join(t for t in texts if t)
        if text:
            return text
    return None


_WAITING_TAIL_CHARS = 60


def _awaiting_user_response(text: str | None) -> bool:
    """Is this message ending on a question aimed at the user, i.e. the
    turn is stopping to wait for their reply rather than finishing a
    unit of work? The waiting-phrase check only looks at the tail of
    the message, not "does this phrase appear anywhere" -- a message
    that quotes or references an earlier question (e.g. recapping "the
    user was asked 'want me to go ahead?'" before reporting it's done)
    would otherwise falsely trip this every time, even though the
    message itself ends on a plain statement."""
    if not text:
        return False
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.endswith("?"):
        return True
    tail = stripped[-_WAITING_TAIL_CHARS:].lower()
    return any(phrase in tail for phrase in _WAITING_PHRASES)


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

    session_id = process_utils.current_session_id()
    if session_id is not None:
        turn_count, turn_started_at = project_store.bump_turn_count(project_root, session_id)
        needs_summary = (turn_count - 1) % SUMMARY_INTERVAL == 0
        if needs_summary and not project_store.summary_logged_since(
            project_root, session_id, turn_started_at
        ):
            print(
                json.dumps(
                    {
                        "decision": "block",
                        "reason": (
                            f"Turn {turn_count}: also log `dashctl summary \"...\"` "
                            "(one sentence on where things stand) before finishing."
                        ),
                    }
                )
            )
            return 0

        # A blocker/question this session raised on an earlier turn is
        # one the user has since replied to, so it should have been
        # resolved rather than left sitting on the dashboard. Checked
        # here because nothing else can: auto_resolve_dead_sessions
        # only cleans up once the session ends. Self-limiting -- if the
        # thing genuinely is still open, resolve it and log a fresh
        # one, which is the intended model anyway (a flag represents
        # something currently awaiting the user, not a history entry).
        stale = project_store.stale_flags_awaiting_resolve(
            project_root, session_id, turn_started_at
        )
        if stale:
            listed = "; ".join(f"{i['type']} [{i['id']}] {i['text']!r}" for i in stale[:3])
            print(
                json.dumps(
                    {
                        "decision": "block",
                        "reason": (
                            f"The user has replied since you logged: {listed}. "
                            "Resolve what's been answered with `dashctl resolve "
                            "blocker|question <id>` (then re-log it if it's "
                            "somehow still open)."
                        ),
                    }
                )
            )
            return 0

    if _awaiting_user_response(_last_assistant_text(payload.get("transcript_path"))) and not (
        project_store.has_logged_this_turn(
            project_root, since_seconds=RECENT_WINDOW_SECONDS, item_type="question"
        )
    ):
        print(
            json.dumps(
                {
                    "decision": "block",
                    "reason": (
                        "This turn ends on a question for the user -- log it "
                        'specifically: `dashctl question "..."`.'
                    ),
                }
            )
        )
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
