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


def auto_register(project_root: Path) -> bool:
    """Registers a directory under its own name if it isn't already
    tracked, so a project starts appearing on the dashboard the moment
    someone works in it -- no separate `dashctl init` step. Returns
    True if it was newly registered.

    Lives here rather than in cli.py because two entry points need the
    exact same rule: `dashctl <log command>` (cli.py) and the
    SessionStart hook, which registers as soon as a session opens in an
    untracked directory instead of waiting for its first log.

    Skips the home directory itself -- a Claude Code session run
    directly in $HOME (not inside an actual project) would otherwise
    silently register "yourusername" as a tracked project. `dashctl
    init` still allows it explicitly, if that's really what's wanted.
    """
    root = Path(project_root).expanduser().resolve()
    if root == Path.home():
        return False
    if str(root) in {p["path"] for p in list_projects()}:
        return False
    add_project(root.name, str(root))
    return True


def project_status_path(project_path: str | Path) -> Path:
    return Path(project_path) / PROJECT_STATUS_DIR / PROJECT_STATUS_FILE
