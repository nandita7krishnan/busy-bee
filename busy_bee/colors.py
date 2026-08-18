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

# Went through two dark/medium attempts (HSL L=0.14, then 0.22 -- both
# still read as "too dark", and inconsistently so across hues, since
# HSL lightness doesn't track perceived brightness -- see the luminance
# comment on _lightness_for_target_luminance). Direct feedback then
# reframed the actual goal: Claude Code's own text already reads well
# on a plain white background, and its many different text colors
# (white/gray/blue links/etc.) were never going to all have good
# contrast against any one mid-brightness color anyway. So instead of
# hunting for a "dark theme that works," target a pale, near-white tint
# instead -- barely-there color on top of what's essentially still a
# white background, still enough to tell projects apart at a glance.
_TERMINAL_BG_TARGET_LUMINANCE = 0.90
_TERMINAL_BG_SATURATION_CAP = 0.18


def _hex_to_rgb01(hex_color: str) -> tuple[float, float, float]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) / 255 for i in (0, 2, 4))


def _rgb01_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02x}" for c in rgb)


def _relative_luminance(rgb01: tuple[float, float, float]) -> float:
    """WCAG-style perceived brightness -- not the same as HSL lightness."""
    r, g, b = rgb01
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _lightness_for_target_luminance(hue: float, saturation: float, target: float) -> float:
    lo, hi = 0.0, 1.0
    for _ in range(30):
        mid = (lo + hi) / 2
        if _relative_luminance(colorsys.hls_to_rgb(hue, mid, saturation)) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def project_color(name: str) -> str:
    h = 0
    for ch in name:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return PROJECT_COLORS[h % len(PROJECT_COLORS)]


def terminal_background_color(name: str) -> str:
    """A pale, barely-there tint of the project's color, for use as a
    full Terminal tab background. The vivid PROJECT_COLORS work fine as
    a thin accent (the popover card's left border), but are far too
    saturated/bright to paint an entire terminal background with, and
    even a darkened/desaturated variant fights with Claude Code's many
    different text colors, which are calibrated for a plain white
    background. Keeps the same hue (still visually ties the tab to its
    dashboard card), heavily capped saturation, and a lightness solved
    per-hue to hit a consistent target *perceived* brightness near
    white -- see the comment on _TERMINAL_BG_TARGET_LUMINANCE for why a
    flat HSL lightness doesn't do that on its own."""
    base_r, base_g, base_b = _hex_to_rgb01(project_color(name))
    hue, _lightness, saturation = colorsys.rgb_to_hls(base_r, base_g, base_b)
    saturation = min(saturation, _TERMINAL_BG_SATURATION_CAP)
    lightness = _lightness_for_target_luminance(hue, saturation, _TERMINAL_BG_TARGET_LUMINANCE)
    r, g, b = colorsys.hls_to_rgb(hue, lightness, saturation)
    return _rgb01_to_hex((r, g, b))
