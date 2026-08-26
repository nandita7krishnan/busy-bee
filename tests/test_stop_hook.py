import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

from busy_bee import project_store

HOOK_PATH = Path(__file__).resolve().parent.parent / "hooks" / "stop_hook.py"
_spec = importlib.util.spec_from_file_location("stop_hook", HOOK_PATH)
stop_hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stop_hook)


@pytest.fixture(autouse=True)
def fixed_session(monkeypatch):
    monkeypatch.setattr(stop_hook.process_utils, "find_claude_ancestor_tty", lambda: "ttys002")
    monkeypatch.setattr(project_store.process_utils, "find_claude_ancestor_tty", lambda: "ttys002")
    monkeypatch.setattr(stop_hook.process_utils, "current_session_id", lambda: "session-1")
    monkeypatch.setattr(project_store.process_utils, "current_session_id", lambda: "session-1")
    yield


def _run(monkeypatch, capsys, cwd, extra_payload=None):
    payload = {"cwd": str(cwd), **(extra_payload or {})}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    stop_hook.main()
    out = capsys.readouterr().out.strip()
    return json.loads(out) if out else None


def test_untracked_project_is_a_noop(monkeypatch, capsys, tmp_path):
    assert _run(monkeypatch, capsys, tmp_path) is None


def test_stop_hook_active_short_circuits(monkeypatch, capsys, tmp_path):
    project_store.add_item(tmp_path, "done", "did a thing")
    assert _run(monkeypatch, capsys, tmp_path, {"stop_hook_active": True}) is None


def test_first_turn_requires_a_summary_specifically(monkeypatch, capsys, tmp_path):
    project_store.add_item(tmp_path, "done", "did a thing")  # creates status.json, turn 1

    result = _run(monkeypatch, capsys, tmp_path)

    assert result["decision"] == "block"
    assert "summary" in result["reason"]


def test_first_turn_satisfied_once_a_summary_is_logged(monkeypatch, capsys, tmp_path):
    project_store.add_item(tmp_path, "done", "did a thing")
    project_store.add_item(tmp_path, "summary", "where things stand")

    assert _run(monkeypatch, capsys, tmp_path) is None


def test_turns_two_through_ten_only_need_any_item(monkeypatch, capsys, tmp_path):
    project_store.add_item(tmp_path, "summary", "seed")  # creates status.json, satisfies turn 1
    assert _run(monkeypatch, capsys, tmp_path) is None  # turn 1

    for turn in range(2, 11):
        project_store.add_item(tmp_path, "done", f"turn {turn} work")
        assert _run(monkeypatch, capsys, tmp_path) is None  # turns 2..10


def test_eleventh_turn_requires_a_summary_again(monkeypatch, capsys, tmp_path):
    project_store.add_item(tmp_path, "summary", "seed")
    assert _run(monkeypatch, capsys, tmp_path) is None  # turn 1
    for turn in range(2, 11):
        project_store.add_item(tmp_path, "done", f"turn {turn} work")
        assert _run(monkeypatch, capsys, tmp_path) is None  # turns 2..10

    project_store.add_item(tmp_path, "done", "turn 11 work, no summary")
    result = _run(monkeypatch, capsys, tmp_path)

    assert result["decision"] == "block"
    assert "summary" in result["reason"]


def test_new_session_in_reused_tty_does_not_inherit_old_sessions_turn_count(
    monkeypatch, capsys, tmp_path
):
    # Same terminal tty (the OS reuses it), but a brand new `claude`
    # invocation -- a fresh session_id. The old session's turns (and its
    # already-satisfied summary requirement) must not carry over.
    project_store.add_item(tmp_path, "summary", "old session seed")  # old session, turn 1
    for turn in range(2, 11):
        project_store.add_item(tmp_path, "done", f"old session turn {turn}")
        assert _run(monkeypatch, capsys, tmp_path) is None

    monkeypatch.setattr(stop_hook.process_utils, "current_session_id", lambda: "session-2")
    monkeypatch.setattr(project_store.process_utils, "current_session_id", lambda: "session-2")

    project_store.add_item(tmp_path, "done", "new session first turn")
    result = _run(monkeypatch, capsys, tmp_path)

    assert result["decision"] == "block"
    assert "summary" in result["reason"]


def test_no_session_id_falls_back_to_general_check(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(stop_hook.process_utils, "current_session_id", lambda: None)
    project_store.add_item(tmp_path, "done", "did a thing")

    assert _run(monkeypatch, capsys, tmp_path) is None


def test_no_session_id_and_nothing_logged_blocks_generally(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(stop_hook.process_utils, "current_session_id", lambda: None)
    status_dir = tmp_path / ".claude-dashboard"
    status_dir.mkdir()
    (status_dir / "status.json").write_text("[]")

    result = _run(monkeypatch, capsys, tmp_path)

    assert result["decision"] == "block"
    assert "dashctl done" in result["reason"]


def _write_transcript(tmp_path, assistant_text):
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": assistant_text}]},
            }
        )
        + "\n"
    )
    return transcript


def test_trailing_question_requires_dashctl_question_even_if_something_else_logged(
    monkeypatch, capsys, tmp_path
):
    project_store.add_item(tmp_path, "summary", "seed")  # turn 1
    assert _run(monkeypatch, capsys, tmp_path) is None

    # A done/summary earlier this turn already satisfies the generic
    # check, but the turn ends on a question -- that must still block.
    project_store.add_item(tmp_path, "done", "tuned the prompts")
    transcript = _write_transcript(tmp_path, "Want me to go ahead and do that now?")

    result = _run(monkeypatch, capsys, tmp_path, {"transcript_path": str(transcript)})

    assert result["decision"] == "block"
    assert "dashctl question" in result["reason"]


def test_trailing_question_satisfied_once_a_question_is_logged(monkeypatch, capsys, tmp_path):
    project_store.add_item(tmp_path, "summary", "seed")  # turn 1
    assert _run(monkeypatch, capsys, tmp_path) is None

    project_store.add_item(tmp_path, "done", "tuned the prompts")
    project_store.add_item(tmp_path, "question", "want me to go ahead and do that now?")
    transcript = _write_transcript(tmp_path, "Want me to go ahead and do that now?")

    assert _run(monkeypatch, capsys, tmp_path, {"transcript_path": str(transcript)}) is None


def test_waiting_phrase_without_question_mark_also_blocks(monkeypatch, capsys, tmp_path):
    project_store.add_item(tmp_path, "summary", "seed")  # turn 1
    assert _run(monkeypatch, capsys, tmp_path) is None

    project_store.add_item(tmp_path, "done", "tuned the prompts")
    transcript = _write_transcript(tmp_path, "Let me know how you'd like to proceed.")

    result = _run(monkeypatch, capsys, tmp_path, {"transcript_path": str(transcript)})

    assert result["decision"] == "block"
    assert "dashctl question" in result["reason"]


def test_non_question_ending_does_not_require_a_question(monkeypatch, capsys, tmp_path):
    project_store.add_item(tmp_path, "summary", "seed")  # turn 1
    assert _run(monkeypatch, capsys, tmp_path) is None

    project_store.add_item(tmp_path, "done", "tuned the prompts")
    transcript = _write_transcript(tmp_path, "Tuned both prompts and reran the smoke test; all green.")

    assert _run(monkeypatch, capsys, tmp_path, {"transcript_path": str(transcript)}) is None


def test_quoted_question_earlier_in_message_does_not_false_positive(monkeypatch, capsys, tmp_path):
    # The message recaps/quotes an earlier question but itself ends on
    # a plain statement -- must not require dashctl question.
    project_store.add_item(tmp_path, "summary", "seed")  # turn 1
    assert _run(monkeypatch, capsys, tmp_path) is None

    project_store.add_item(tmp_path, "done", "tuned the prompts")
    transcript = _write_transcript(
        tmp_path,
        'This should have caught the exact case from earlier -- "Want me to go ahead '
        "and do that now?\" will now force a `dashctl question` call before the turn can end.",
    )

    assert _run(monkeypatch, capsys, tmp_path, {"transcript_path": str(transcript)}) is None


def test_missing_transcript_path_skips_question_check(monkeypatch, capsys, tmp_path):
    project_store.add_item(tmp_path, "summary", "seed")  # turn 1
    assert _run(monkeypatch, capsys, tmp_path) is None

    project_store.add_item(tmp_path, "done", "tuned the prompts")
    assert _run(monkeypatch, capsys, tmp_path) is None


def test_summary_and_question_are_reported_together(monkeypatch, capsys, tmp_path):
    # Turn 1 owes a summary and also ends on a question. Reporting only
    # the summary let the question slip: the follow-up turn that logs it
    # short-circuits at stop_hook_active, so the question check never
    # runs again and the question never reaches the dashboard.
    project_store.add_item(tmp_path, "done", "did a thing")  # creates status.json, turn 1
    transcript = _write_transcript(tmp_path, "Want me to go ahead and do that now?")

    result = _run(monkeypatch, capsys, tmp_path, {"transcript_path": str(transcript)})

    assert result["decision"] == "block"
    assert "summary" in result["reason"]
    assert "dashctl question" in result["reason"]


def test_generic_reminder_is_dropped_when_a_question_is_already_demanded(
    monkeypatch, capsys, tmp_path
):
    # Nothing logged this turn and the turn ends on a question -- the
    # `dashctl question` call being asked for satisfies the generic
    # check too, so don't ask for both.
    project_store.add_item(tmp_path, "summary", "seed")  # turn 1
    assert _run(monkeypatch, capsys, tmp_path) is None

    transcript = _write_transcript(tmp_path, "Want me to go ahead and do that now?")
    result = _run(monkeypatch, capsys, tmp_path, {"transcript_path": str(transcript)})

    assert result["decision"] == "block"
    assert "dashctl question" in result["reason"]
    assert "dashctl todo" not in result["reason"]
