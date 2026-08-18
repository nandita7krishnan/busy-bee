"""Per-project identity colors -- palette and hash kept identical to
the popover UI's own copy (busy_bee/ui/popover.js:projectColorClass,
busy_bee/ui/popover.css --proj-N) so a project's dashboard card color
and its Terminal window color always match. JS and Python can't share
source, so if you touch one, touch both.
"""

from __future__ import annotations

PROJECT_COLORS = [
    "#5b8def",
    "#9b59b6",
    "#16a085",
    "#e67e22",
    "#e84393",
    "#00b8d9",
    "#6c5ce7",
    "#8e9b1f",
]


def project_color(name: str) -> str:
    h = 0
    for ch in name:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return PROJECT_COLORS[h % len(PROJECT_COLORS)]
