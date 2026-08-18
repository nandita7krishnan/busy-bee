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

# A fixed HSL lightness (tried first at 0.14, then 0.22) still read as
# noticeably darker for blue/purple projects than for yellow/green ones
# even at the "same" setting -- confirmed by computing WCAG relative
# luminance for each: busy-bee's blue-purple hue only reached 0.145 at
# L=0.22 while proj-c's yellow-green hue reached 0.229 at that same L.
# That's because HSL lightness doesn't track perceived brightness --
# green contributes ~10x more to how bright a color looks than blue
# does (the 0.7152 vs 0.0722 weights below). Targeting a fixed
# *luminance* instead (found per-hue via binary search over L) makes
# every project's background read as equally light regardless of hue,
# and fixes the "still too dark" feedback at its actual root cause
# instead of just nudging one global number again.
_TERMINAL_BG_TARGET_LUMINANCE = 0.38
_TERMINAL_BG_SATURATION_CAP = 0.42


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
    """A dark, desaturated variant of the project's color, for use as
    a full Terminal tab background. The vivid PROJECT_COLORS work fine
    as a thin accent (the popover card's left border), but are far too
    saturated/bright to paint an entire terminal background with --
    real screenshot showed Claude Code's own text becoming hard to
    read against them. Keeps the same hue (still visually ties the tab
    to its dashboard card), capped saturation, and a lightness solved
    per-hue to hit a consistent target *perceived* brightness -- see
    the comment on _TERMINAL_BG_TARGET_LUMINANCE for why a flat HSL
    lightness doesn't do that on its own."""
    base_r, base_g, base_b = _hex_to_rgb01(project_color(name))
    hue, _lightness, saturation = colorsys.rgb_to_hls(base_r, base_g, base_b)
    saturation = min(saturation, _TERMINAL_BG_SATURATION_CAP)
    lightness = _lightness_for_target_luminance(hue, saturation, _TERMINAL_BG_TARGET_LUMINANCE)
    r, g, b = colorsys.hls_to_rgb(hue, lightness, saturation)
    return _rgb01_to_hex((r, g, b))
