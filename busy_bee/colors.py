"""Per-project identity colors -- palette and hash kept identical to
the popover UI's own copy (busy_bee/ui/popover.js:projectColorClass,
busy_bee/ui/popover.css --proj-N) so a project's dashboard card color
and its Terminal window color always match. JS and Python can't share
source, so if you touch one, touch both.
"""

from __future__ import annotations

import colorsys

# Index 0-2 chosen deliberately (pink, blue, purple) per explicit
# request. First pass used a new #ff6f91 for "pink" and dropped the
# original #e84393 magenta as a near-duplicate -- turned out #ff6f91
# read as more of a mauve/purple in practice, and #e84393 was the
# color meant by "pink" all along. Restored it, moved to the front.
PROJECT_COLORS = [
    "#e84393",
    "#5b8def",
    "#9b59b6",
    "#16a085",
    "#e67e22",
    "#00b8d9",
    "#6c5ce7",
    "#8e9b1f",
]

# Went through several attempts: HSL L=0.14 and 0.22 (too dark, and
# inconsistently so across hues -- HSL lightness doesn't track
# perceived brightness, see the luminance comment on
# _lightness_for_target_luminance); then a very pale near-white
# (target luminance 0.90, saturation capped at 0.18) that fixed
# readability but overcorrected -- capped that low, different projects'
# pastels were nearly indistinguishable from each other and from plain
# white, defeating the point (also supposed to visibly tie back to the
# project's own dashboard card color). Landed on 0.85/0.55 as the
# balance, then nudged to 0.88 on request for a touch lighter still --
# checked the 0.55 saturation cap still keeps all 8 hues visibly
# distinct at 0.88 before landing here.
_TERMINAL_BG_TARGET_LUMINANCE = 0.88
_TERMINAL_BG_SATURATION_CAP = 0.55


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
