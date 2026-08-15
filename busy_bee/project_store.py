"""Per-project status store: the JSON file dashctl reads and writes.

Lives at <project_root>/.claude-dashboard/status.json. This is the
"local status store" in the architecture diagram -- append-only, full
history retained, one file per project. The aggregator later reads this
file and merges it into the central SQLite store.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

ItemType = Literal["done", "todo", "blocker", "question"]
VALID_TYPES: tuple[ItemType, ...] = ("done", "todo", "blocker", "question")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status_file(project_root: Path) -> Path:
    return project_root / ".claude-dashboard" / "status.json"


def _load(project_root: Path) -> list[dict]:
    path = _status_file(project_root)
    if not path.exists():
        return []
    with path.open() as f:
        return json.load(f)


def _save(project_root: Path, items: list[dict]) -> None:
    path = _status_file(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(items, f, indent=2)
    tmp.replace(path)


def add_item(project_root: Path, item_type: ItemType, text: str, source: str = "agent") -> dict:
    if item_type not in VALID_TYPES:
        raise ValueError(f"invalid item type: {item_type!r} (must be one of {VALID_TYPES})")
    items = _load(project_root)
    item = {
        "id": uuid.uuid4().hex[:12],
        "type": item_type,
        "text": text,
        "created_at": _now(),
        "resolved_at": None,
        "source": source,
    }
    items.append(item)
    _save(project_root, items)
    return item


def resolve_item(project_root: Path, item_type: ItemType, item_id: str) -> bool:
    if item_type not in ("blocker", "question"):
        raise ValueError("only blocker or question items can be resolved")
    items = _load(project_root)
    for item in items:
        if item["id"] == item_id and item["type"] == item_type:
            if item["resolved_at"] is None:
                item["resolved_at"] = _now()
            _save(project_root, items)
            return True
    return False


def all_items(project_root: Path) -> list[dict]:
    return _load(project_root)


def has_logged_this_turn(project_root: Path, since_seconds: int = 120) -> bool:
    """Used by the Stop hook: did anything get logged recently?"""
    items = _load(project_root)
    if not items:
        return False
    latest = max(items, key=lambda i: i["created_at"])
    latest_dt = datetime.fromisoformat(latest["created_at"])
    delta = datetime.now(timezone.utc) - latest_dt
    return delta.total_seconds() <= since_seconds
