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

# Went through several attempts for the light-mode target: HSL L=0.14
# and 0.22 (too dark, and inconsistently so across hues -- HSL
# lightness doesn't track perceived brightness, see the luminance
# comment on _lightness_for_target_luminance); then a very pale
# near-white (target luminance 0.90, saturation capped at 0.18) that
# fixed readability but overcorrected -- capped that low, different
# projects' pastels were nearly indistinguishable from each other and
# from plain white, defeating the point (also supposed to visibly tie
# back to the project's own dashboard card color). 0.55 saturation
# fixed that; luminance itself nudged lighter twice more since (0.85 ->
# 0.88 -> 0.92) chasing "closer to white" while re-checking each time
# that 0.55 saturation still keeps all 8 hues visibly distinct.
_TERMINAL_BG_TARGET_LUMINANCE_LIGHT = 0.92
# First dark-mode pass reused the light-mode 0.55 saturation cap at
# luminance 0.16 -- confirmed live as "terrible": at that saturation, a
# hue like the indigo project color came out as a vivid near-neon blue
# rather than a muted dark-UI surface (typical dark editor/terminal
# backgrounds are both darker and far less saturated than their light-
# mode counterparts, not just an inverted version of the same recipe).
# Dropped luminance further and capped saturation much harder so the
# tint reads as "dark surface with a whisper of hue," not a bright
# color that happens to be dark.
_TERMINAL_BG_TARGET_LUMINANCE_DARK = 0.10
_TERMINAL_BG_SATURATION_CAP_LIGHT = 0.55
_TERMINAL_BG_SATURATION_CAP_DARK = 0.30


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


def terminal_background_color(name: str, dark: bool = False) -> str:
    """A tint of the project's color, for use as a full Terminal tab
    background. The vivid PROJECT_COLORS work fine as a thin accent
    (the popover card's left border), but are far too saturated/bright
    to paint an entire terminal background with, and even a
    darkened/desaturated variant fights with Claude Code's own text
    colors -- which are calibrated for whichever background the
    terminal is actually running against. Keeps the same hue (still
    visually ties the tab to its dashboard card), though both the
    target *perceived* brightness and the saturation cap flip: a pale
    near-white tint for a light-background terminal (dark=False, the
    default) or a muted dark near-black tint for a dark-background one
    (dark=True) -- see the comments on
    _TERMINAL_BG_TARGET_LUMINANCE_LIGHT/_DARK and
    _TERMINAL_BG_SATURATION_CAP_LIGHT/_DARK for why a flat HSL
    lightness (or one shared saturation cap) can't hit either target
    consistently on its own."""
    base_r, base_g, base_b = _hex_to_rgb01(project_color(name))
    hue, _lightness, saturation = colorsys.rgb_to_hls(base_r, base_g, base_b)
    saturation = min(saturation, _TERMINAL_BG_SATURATION_CAP_DARK if dark else _TERMINAL_BG_SATURATION_CAP_LIGHT)
    target = _TERMINAL_BG_TARGET_LUMINANCE_DARK if dark else _TERMINAL_BG_TARGET_LUMINANCE_LIGHT
    lightness = _lightness_for_target_luminance(hue, saturation, target)
    r, g, b = colorsys.hls_to_rgb(hue, lightness, saturation)
    return _rgb01_to_hex((r, g, b))
