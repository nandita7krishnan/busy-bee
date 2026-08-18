"""Per-project identity colors -- palette and hash kept identical to
the popover UI's own copy (busy_bee/ui/popover.js:projectColorClass,
busy_bee/ui/popover.css --proj-N) so a project's dashboard card color
and its Terminal window color always match. JS and Python can't share
source, so if you touch one, touch both.
"""

from __future__ import annotations

import colorsys

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

# How dark/desaturated a terminal background needs to be to stay out of
# the way of Claude Code's own text colors (calibrated for a near-black
# or near-white background, not an arbitrary bright one). Chosen and
# checked against real screenshots of Claude Code's actual text colors
# on top of each swatch -- see terminal_background_color.
_TERMINAL_BG_LIGHTNESS = 0.14
_TERMINAL_BG_SATURATION_CAP = 0.38


def _hex_to_rgb01(hex_color: str) -> tuple[float, float, float]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) / 255 for i in (0, 2, 4))


def _rgb01_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02x}" for c in rgb)


def project_color(name: str) -> str:
    h = 0
    for ch in name:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return PROJECT_COLORS[h % len(PROJECT_COLORS)]


def terminal_background_color(name: str) -> str:
    """A dark, desaturated variant of the project's color, for use as
    a full Terminal tab background. The vivid PROJECT_COLORS work fine
    as a thin accent (the popover card's left border), but are far too
    saturated/bright to paint an entire terminal background with --
    real screenshot showed Claude Code's own text becoming hard to
    read against them. Keeps the same hue (still visually ties the tab
    to its dashboard card) at a much lower lightness and capped
    saturation, the same idea real dark-terminal-theme palettes
    (Dracula, Nord, etc.) use for background hues."""
    base_r, base_g, base_b = _hex_to_rgb01(project_color(name))
    hue, _lightness, saturation = colorsys.rgb_to_hls(base_r, base_g, base_b)
    saturation = min(saturation, _TERMINAL_BG_SATURATION_CAP)
    r, g, b = colorsys.hls_to_rgb(hue, _TERMINAL_BG_LIGHTNESS, saturation)
    return _rgb01_to_hex((r, g, b))
