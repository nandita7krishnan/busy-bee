"""dashctl -- the CLI the agent calls mid-session to log status.

    dashctl done "<text>"
    dashctl todo "<text>"
    dashctl blocker "<text>"
    dashctl question "<text>"
    dashctl summary "<text>"
    dashctl resolve blocker|question|todo <id>

`summary` is different from the rest: it's not shown in the Done/Next
lists, just as a short line next to the project name in the dashboard
-- one per project, overwritten each time (not a growing history). Use
it when wrapping up a chunk of work or a session, to capture "where
things stand" in a sentence.

The project is auto-registered as a tracked project the first time
any of the log commands runs (and, earlier still, by the SessionStart
hook as soon as a session opens in it) -- no separate init step needed
once `dashctl setup-global` has wired up the CLAUDE.md snippet and
hooks globally (see global_setup.py).

Also:

    dashctl init [--name NAME]   register the current directory under
                                  an explicit name, instead of the
                                  directory's basename
    dashctl untrack NAME          stop tracking a project and delete
                                  its logged items from the central store
    dashctl setup-global          one-time: installs the CLAUDE.md
                                  snippet and Stop/SessionStart/PostToolUse
                                  hooks at the Claude Code user level so
                                  every project gets tracked automatically

Logs against the project the *session* is working on, not the shell's
current directory -- the agent runs these from wherever it happens to
be at the time, which may be a subdirectory or the scratchpad. See
_project_root.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from busy_bee import config, db, global_setup, placeholder_store, process_utils, project_store


def _project_root() -> Path:
    """The project these logs belong to.

    Asks the session where it was started rather than trusting the
    shell's cwd. dashctl is run through the Bash tool, whose cwd is
    wherever the agent last `cd`'d -- into a `backend/` subdirectory,
    or into the session's scratchpad under /tmp -- which has nothing to
    do with which project the session is working on. Taking the project
    from that is what let a session started in a perfectly ordinary
    repo register a *second* project mid-turn, named after a
    subdirectory, and split its status across two dashboard cards.

    Falls back to the shell's cwd when the session directory isn't
    available (dashctl run by hand outside Claude Code) or doesn't
    identify a project on its own -- notably a session started in
    $HOME, where the directory being worked in is the better guess."""
    session_cwd = process_utils.claude_session_cwd()
    if session_cwd is not None and (
        config.enclosing_project(session_cwd) is not None
        or config.repo_root_for(session_cwd) is not None
    ):
        return config.project_root_for(session_cwd)
    return config.project_root_for(Path.cwd())


_LOG_TYPES = ("done", "todo", "blocker", "question", "summary")

# Matches the "aim for under 12 words" guidance in claude_md_snippet.md.
# A soft nudge, not a hard limit -- prompt wording alone wasn't enough
# (plenty of long entries got logged despite the instructions already
# saying "one-line, plain-language"), but truncating or rejecting the
# text outright would lose information a human might actually want in
# the full-text tooltip. This just makes the ask visible at the moment
# it's easy to fix, without blocking the command.
_CONCISE_WORD_LIMIT = 12


def cmd_log(item_type: str, text: str) -> int:
    root = _project_root()
    config.auto_register(root)
    item = project_store.add_item(root, item_type, text)  # type: ignore[arg-type]
    if item_type in ("blocker", "question", "todo"):
        print(f"logged {item_type} [{item['id']}]: {text}")
    else:
        print(f"logged {item_type}: {text}")

    word_count = len(text.split())
    if word_count > _CONCISE_WORD_LIMIT:
        print(
            f"tip: that's {word_count} words -- the dashboard shows these in a small "
            f"card and truncates long entries. Aim for under {_CONCISE_WORD_LIMIT} "
            "next time (the outcome, not the explanation).",
            file=sys.stderr,
        )
    return 0


def cmd_resolve(item_type: str, item_id: str) -> int:
    ok = project_store.resolve_item(_project_root(), item_type, item_id)  # type: ignore[arg-type]
    if ok:
        print(f"resolved {item_type} [{item_id}]")
        return 0
    print(f"no unresolved {item_type} with id {item_id!r} found", file=sys.stderr)
    return 1


def cmd_init(name: str | None) -> int:
    # The current directory itself, not the project it may sit inside:
    # `init` is the explicit way to track a subdirectory (a repo nested
    # in another one, say) as a project in its own right.
    root = Path.cwd().resolve()
    project_name = name or root.name
    config.add_project(project_name, str(root))
    status_path = config.project_status_path(root)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    if not status_path.exists():
        status_path.write_text("[]")
    print(f"registered {project_name!r} at {root} (tracked by busy-bee)")
    return 0


def cmd_untrack(name: str) -> int:
    removed_from_config = config.remove_project(name)
    db.delete_project(name)
    # A retained placeholder record (one whose folder was created but
    # whose manual tasks were kept dashboard-only, see
    # Api.activate_placeholder_project) is otherwise the one piece of
    # this project's state untrack wouldn't reach.
    placeholder_store.delete(name)
    if not removed_from_config:
        print(f"{name!r} wasn't in config.json (removing any leftover db rows anyway)")
    print(f"untracked {name!r} -- it and its logged items no longer appear on the dashboard")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dashctl", description="Log status for busy-bee.")
    sub = parser.add_subparsers(dest="command", required=True)

    for item_type in _LOG_TYPES:
        p = sub.add_parser(item_type, help=f"log a {item_type} item")
        p.add_argument("text", help="one-line description")

    resolve_p = sub.add_parser("resolve", help="resolve a blocker, question, or todo")
    resolve_p.add_argument("type", choices=["blocker", "question", "todo"])
    resolve_p.add_argument("id", help="item id printed when it was logged")

    init_p = sub.add_parser(
        "init", help="register the current directory under an explicit name"
    )
    init_p.add_argument("--name", default=None, help="project name (defaults to directory name)")

    untrack_p = sub.add_parser(
        "untrack", help="stop tracking a project and remove its logged items"
    )
    untrack_p.add_argument("name", help="project name, as shown on the dashboard")

    sub.add_parser(
        "setup-global",
        help="one-time: install the CLAUDE.md snippet and Stop hook globally",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command in _LOG_TYPES:
        return cmd_log(args.command, args.text)
    if args.command == "resolve":
        return cmd_resolve(args.type, args.id)
    if args.command == "init":
        return cmd_init(args.name)
    if args.command == "untrack":
        return cmd_untrack(args.name)
    if args.command == "setup-global":
        return global_setup.main()

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
