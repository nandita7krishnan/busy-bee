"""Manual "placeholder" project cards -- created straight from the
dashboard UI, before any folder exists on disk.

Lives at ~/.claude-dashboard/placeholders.json, deliberately separate
from both config.json and the central SQLite store:

- config.json's `projects` list is what aggregator.sync_all() iterates
  every poll (see aggregator.py:88-100) -- a placeholder with no real
  path would blow up that loop the moment it tried to Path() it. It
  also gets read-modify-written by `dashctl auto_register` from every
  terminal in every tracked project, so a UI write racing that would
  lose one side of the whole file.
- db.py's `projects` table is a derived cache the aggregator rebuilds
  from each project's status.json every 5s (aggregator.py:41-57) --
  placeholder tasks are authoritative user input with no status.json
  to rebuild from, so they'd be the one row nothing could regenerate.
  `projects.path` is also NOT NULL (db.py:36), with no concept of "no
  path yet".

A separate file sidesteps both: invisible to config.list_projects(),
no schema to migrate, and -- the sharpest constraint -- nothing here
ever calls mkdir on a project path. project_store._save does
(project_store.py:41), which is exactly why placeholder tasks must
never be written through project_store: doing so would create the
project's folder on disk before the user ever clicks "Create folder".
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from busy_bee import config

FILENAME = "placeholders.json"

_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path() -> Path:
    # A function, not a module-level constant, so tests only need to
    # monkeypatch config.HOME_DIR (same pattern as config.CONFIG_PATH).
    return config.HOME_DIR / FILENAME


def load() -> list[dict]:
    path = _path()
    if not path.exists():
        return []
    with path.open() as f:
        return json.load(f).get("placeholders", [])


def _save(placeholders: list[dict]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump({"placeholders": placeholders}, f, indent=2)
    tmp.replace(path)


def get(name: str) -> dict | None:
    return next((p for p in load() if p["name"] == name), None)


def list_pending() -> list[dict]:
    """Placeholders that haven't been activated yet -- still just a
    card, no folder on disk."""
    return [p for p in load() if p["activated_path"] is None]


def list_retained() -> list[dict]:
    """Placeholders that WERE activated but whose tasks were kept
    dashboard-only (the user declined the handoff-to-Claude prompt) --
    still tracked here so their manual tasks keep showing on the now-
    real project's card."""
    return [p for p in load() if p["activated_path"] is not None]


def _validate_name(name: str, existing_names: set[str]) -> None:
    if not name or not name.strip():
        raise ValueError("project name can't be blank")
    if "/" in name:
        raise ValueError("project name can't contain '/'")
    if name.startswith("."):
        raise ValueError("project name can't start with '.'")
    if name in existing_names:
        raise ValueError(f"a project named {name!r} already exists")


def create(name: str) -> dict:
    """Adds a new placeholder card. Raises ValueError for a blank name,
    one containing '/' or starting with '.' (both would misbehave as a
    future folder name), or one that collides with an existing
    placeholder OR an already-tracked project (config.json) -- the
    dashboard should never show two cards for the same name."""
    with _LOCK:
        placeholders = load()
        tracked_names = {p["name"] for p in config.list_projects()}
        existing_names = {p["name"] for p in placeholders} | tracked_names
        _validate_name(name, existing_names)
        record = {
            "name": name,
            "created_at": _now(),
            "activated_path": None,
            "tasks": [],
        }
        placeholders.append(record)
        _save(placeholders)
        return record


def delete(name: str) -> bool:
    with _LOCK:
        placeholders = load()
        remaining = [p for p in placeholders if p["name"] != name]
        if len(remaining) == len(placeholders):
            return False
        _save(remaining)
        return True


def mark_activated(name: str, path: str) -> None:
    """Records that this placeholder's folder now exists at `path`,
    without deleting the record -- used when the user declines the
    task-handoff prompt, so the manual tasks stay retrievable and can
    still be attached to the now-real project's card."""
    with _LOCK:
        placeholders = load()
        for p in placeholders:
            if p["name"] == name:
                p["activated_path"] = path
                _save(placeholders)
                return


def add_task(name: str, text: str) -> dict:
    if not text or not text.strip():
        raise ValueError("task text can't be blank")
    with _LOCK:
        placeholders = load()
        record = next((p for p in placeholders if p["name"] == name), None)
        if record is None:
            raise ValueError(f"no placeholder project named {name!r}")
        task = {
            "id": uuid.uuid4().hex[:12],
            "text": text.strip(),
            "created_at": _now(),
            "resolved_at": None,
        }
        record["tasks"].append(task)
        _save(placeholders)
        return task


def set_task_resolved(name: str, task_id: str, resolved: bool) -> bool:
    """The two-way primitive nothing else in the codebase has --
    project_store.resolve_item (project_store.py:119-129) only ever
    sets resolved_at, never clears it. A manual task's checkbox needs
    both directions, and un-resolving deliberately stays out of
    dashctl/agent territory (that's still one-way), scoped to this
    dashboard-only store instead."""
    with _LOCK:
        placeholders = load()
        record = next((p for p in placeholders if p["name"] == name), None)
        if record is None:
            return False
        for task in record["tasks"]:
            if task["id"] == task_id:
                task["resolved_at"] = _now() if resolved else None
                _save(placeholders)
                return True
        return False
