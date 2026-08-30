"""Global config for busy-bee: where the central store lives and which
projects the aggregator should watch.

Config lives at ~/.claude-dashboard/config.json:

{
  "projects": [
    {"name": "my-project", "path": "/Users/you/code/my-project"}
  ],
  "poll_interval_seconds": 5,
  "terminal_app": "Terminal"   // or "iTerm"
}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

HOME_DIR = Path.home() / ".claude-dashboard"
CONFIG_PATH = HOME_DIR / "config.json"
DB_PATH = HOME_DIR / "db.sqlite"

PROJECT_STATUS_DIR = ".claude-dashboard"
PROJECT_STATUS_FILE = "status.json"

DEFAULT_CONFIG = {
    "projects": [],
    "poll_interval_seconds": 5,
    "terminal_app": "Terminal",
}


class ProjectConfig(TypedDict):
    name: str
    path: str


def ensure_home_dir() -> None:
    HOME_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    ensure_home_dir()
    if not CONFIG_PATH.exists():
        fresh = json.loads(json.dumps(DEFAULT_CONFIG))
        save_config(fresh)
        return fresh
    with CONFIG_PATH.open() as f:
        return json.load(f)


def save_config(config: dict) -> None:
    ensure_home_dir()
    with CONFIG_PATH.open("w") as f:
        json.dump(config, f, indent=2)


def add_project(name: str, path: str) -> None:
    config = load_config()
    projects: list[ProjectConfig] = config.setdefault("projects", [])
    resolved = str(Path(path).expanduser().resolve())
    for p in projects:
        if p["name"] == name:
            p["path"] = resolved
            save_config(config)
            return
    projects.append({"name": name, "path": resolved})
    save_config(config)


def remove_project(name: str) -> bool:
    config = load_config()
    projects: list[ProjectConfig] = config.get("projects", [])
    remaining = [p for p in projects if p["name"] != name]
    if len(remaining) == len(projects):
        return False
    config["projects"] = remaining
    save_config(config)
    return True


def list_projects() -> list[ProjectConfig]:
    return load_config().get("projects", [])


def enclosing_project(path: str | Path) -> ProjectConfig | None:
    """The tracked project `path` belongs to -- itself, if it's a
    tracked root, otherwise the nearest tracked ancestor. Returns None
    if it sits outside every tracked project.

    Subdirectories matter because a session's cwd isn't always the
    project root: opening Claude Code in `my-app/backend` (or running
    `dashctl` from there) is still work on `my-app`. Matching tracked
    roots by exact path only, it read as a directory nothing knew
    about, so it got registered as a second project called "backend"
    sitting next to its own parent on the dashboard, with its status
    split across two cards.

    Nearest, not first, when tracked projects nest: a repo explicitly
    registered inside another one (via `dashctl init`) was tracked
    separately on purpose, so work in it belongs to the inner project,
    not the outer."""
    root = Path(path).expanduser().resolve()
    candidates = [
        p for p in list_projects() if root == Path(p["path"]) or Path(p["path"]) in root.parents
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: len(Path(p["path"]).parts))


def repo_root_for(path: str | Path) -> Path | None:
    """The top of the git repository `path` sits in, or None if it
    isn't in one.

    This is what makes a directory a *project* rather than just a
    directory. Without it, "project" meant "whatever directory the
    session happened to open in", so the first session started in
    `my-app/backend` registered `backend` -- and a later session
    started in `my-app` itself then registered that too, as a second,
    unrelated-looking project for the same repo. enclosing_project only
    catches the second of those; by then the wrong name is already the
    one on the dashboard.

    Walks up looking for `.git` instead of shelling out to `git
    rev-parse`: this runs from hooks on every session start and every
    user prompt, where a subprocess per call is a real cost, and a
    `.git` entry (a directory normally, a file in a worktree or
    submodule) is exactly what git itself looks for. Stops before
    $HOME, so a dotfiles repo checked out at ~ doesn't turn the whole
    home directory into one giant project."""
    root = Path(path).expanduser().resolve()
    home = Path.home()
    for candidate in (root, *root.parents):
        if candidate == home or candidate == candidate.parent:
            return None
        if (candidate / ".git").exists():
            return candidate
    return None


def project_root_for(path: str | Path) -> Path:
    """The directory status for `path` should be logged against: the
    tracked project containing it, else the repository it's part of,
    else `path` itself (the caller then decides whether to register it
    -- see auto_register).

    A tracked project wins over the repository root because tracking it
    was deliberate: a subdirectory registered with `dashctl init`, or a
    project whose folder isn't a repo at all, shouldn't be silently
    re-pointed at some enclosing repo."""
    enclosing = enclosing_project(path)
    if enclosing is not None:
        return Path(enclosing["path"])
    return repo_root_for(path) or Path(path).expanduser().resolve()


def auto_register(project_root: Path) -> bool:
    """Registers a directory under its own name if it isn't already
    part of a tracked project, so a project starts appearing on the
    dashboard the moment someone works in it -- no separate `dashctl
    init` step. Returns True if it was newly registered.

    Lives here rather than in cli.py because two entry points need the
    exact same rule: `dashctl <log command>` (cli.py) and the
    SessionStart hook, which registers as soon as a session opens in an
    untracked directory instead of waiting for its first log.

    Registers the project the directory belongs to, not the directory
    itself: a subdirectory of an already-tracked project isn't a new
    project (see enclosing_project), and a directory inside a git repo
    registers the repo (see repo_root_for) -- otherwise the name and
    identity a project gets are decided by wherever its first session
    happened to be started.

    Skips the home directory itself -- a Claude Code session run
    directly in $HOME (not inside an actual project) would otherwise
    silently register "yourusername" as a tracked project. `dashctl
    init` still allows it explicitly, if that's really what's wanted.
    """
    root = Path(project_root).expanduser().resolve()
    if root == Path.home():
        return False
    if enclosing_project(root) is not None:
        return False
    root = project_root_for(root)
    add_project(root.name, str(root))
    return True


def project_status_path(project_path: str | Path) -> Path:
    return Path(project_path) / PROJECT_STATUS_DIR / PROJECT_STATUS_FILE
