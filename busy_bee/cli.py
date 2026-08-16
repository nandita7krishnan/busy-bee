"""dashctl -- the CLI the agent calls mid-session to log status.

    dashctl done "<text>"
    dashctl todo "<text>"
    dashctl blocker "<text>"
    dashctl question "<text>"
    dashctl resolve blocker|question <id>

The current directory is auto-registered as a tracked project the
first time any of the log commands runs -- no separate init step
needed once `dashctl setup-global` has wired up the CLAUDE.md snippet
and Stop hook globally (see global_setup.py).

Also:

    dashctl init [--name NAME]   register the current directory under
                                  an explicit name, instead of the
                                  directory's basename
    dashctl setup-global          one-time: installs the CLAUDE.md
                                  snippet and Stop hook at the Claude
                                  Code user level so every project
                                  gets tracked automatically

Operates on the current working directory as the project root -- the
agent runs these from inside the project, same as any other CLI tool
in its session.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from busy_bee import config, global_setup, project_store


def _project_root() -> Path:
    return Path.cwd().resolve()


def _auto_register(root: Path) -> None:
    """Registers the project under its directory name if it isn't
    already tracked. A no-op (besides a cheap config read) if it is.

    Skips the home directory itself -- a Claude Code session run
    directly in $HOME (not inside an actual project) would otherwise
    silently register "yourusername" as a tracked project. `dashctl
    init` still allows it explicitly, if that's really what's wanted.
    """
    if root == Path.home():
        return
    known_paths = {p["path"] for p in config.list_projects()}
    if str(root) not in known_paths:
        config.add_project(root.name, str(root))


def cmd_log(item_type: str, text: str) -> int:
    root = _project_root()
    _auto_register(root)
    item = project_store.add_item(root, item_type, text)  # type: ignore[arg-type]
    if item_type in ("blocker", "question"):
        print(f"logged {item_type} [{item['id']}]: {text}")
    else:
        print(f"logged {item_type}: {text}")
    return 0


def cmd_resolve(item_type: str, item_id: str) -> int:
    ok = project_store.resolve_item(_project_root(), item_type, item_id)  # type: ignore[arg-type]
    if ok:
        print(f"resolved {item_type} [{item_id}]")
        return 0
    print(f"no unresolved {item_type} with id {item_id!r} found", file=sys.stderr)
    return 1


def cmd_init(name: str | None) -> int:
    root = _project_root()
    project_name = name or root.name
    config.add_project(project_name, str(root))
    status_path = config.project_status_path(root)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    if not status_path.exists():
        status_path.write_text("[]")
    print(f"registered {project_name!r} at {root} (tracked by busy-bee)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dashctl", description="Log status for busy-bee.")
    sub = parser.add_subparsers(dest="command", required=True)

    for item_type in ("done", "todo", "blocker", "question"):
        p = sub.add_parser(item_type, help=f"log a {item_type} item")
        p.add_argument("text", help="one-line description")

    resolve_p = sub.add_parser("resolve", help="resolve a blocker or question")
    resolve_p.add_argument("type", choices=["blocker", "question"])
    resolve_p.add_argument("id", help="item id printed when it was logged")

    init_p = sub.add_parser(
        "init", help="register the current directory under an explicit name"
    )
    init_p.add_argument("--name", default=None, help="project name (defaults to directory name)")

    sub.add_parser(
        "setup-global",
        help="one-time: install the CLAUDE.md snippet and Stop hook globally",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command in ("done", "todo", "blocker", "question"):
        return cmd_log(args.command, args.text)
    if args.command == "resolve":
        return cmd_resolve(args.type, args.id)
    if args.command == "init":
        return cmd_init(args.name)
    if args.command == "setup-global":
        return global_setup.main()

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
