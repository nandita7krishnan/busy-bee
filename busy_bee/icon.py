"""Renders the bee icon used in the menu bar and Dock.

Two variants:
- render_plain_bee(): just the bee, no badge -- used as the Dock icon's
  base image (the Dock badge itself is drawn natively by macOS via
  NSDockTile.badgeLabel, so baking a badge into this one would double
  it up).
- render_tray_icon(count): bee with a composited red-circle/white-number
  badge in the corner -- used for the menu bar status item, which has
  no native badge API equivalent to the Dock's, so this is drawn by
  hand to look the same.

Both are cached to disk under ~/.claude-dashboard/ and only re-rendered
when the badge count actually changes, since rumps'/AppKit's icon
setters read from a file path, not an in-memory image.
"""

from __future__ import annotations

from pathlib import Path

from busy_bee.config import HOME_DIR

PLAIN_ICON_PATH = HOME_DIR / "bee_icon.png"
TRAY_ICON_DIR = HOME_DIR / "tray_icons"
WIDGET_ICON_DIR = HOME_DIR / "widget_icons"

_BEE = "🐝"


def _draw_bee(image, size: float) -> None:
    import AppKit
    import Foundation

    # 0.72 (original) left too little internal margin: an emoji glyph's
    # actual ink (antennae, legs, wings) extends beyond the font's
    # nominal metrics box, and on top of that the badge (see
    # _draw_badge) visually overlaps the top-right quadrant where the
    # antennae are -- found by actually looking at the composited
    # render with a badge, not just the bare bee alone, which is what
    # earlier verification had checked. 0.60 leaves real headroom.
    font = AppKit.NSFont.systemFontOfSize_(size * 0.60)
    attrs = {AppKit.NSFontAttributeName: font}
    text = Foundation.NSString.stringWithString_(_BEE)
    text_size = text.sizeWithAttributes_(attrs)
    text.drawAtPoint_withAttributes_(
        Foundation.NSMakePoint((size - text_size.width) / 2, (size - text_size.height) / 2 - size * 0.04),
        attrs,
    )


def _draw_badge(image, size: float, count: int) -> None:
    import AppKit
    import Foundation

    # 0.5 (half the entire icon's diameter!) visually swallowed the
    # bee's head/antennae in the top-right quadrant where both the bee
    # art and the badge naturally sit -- confirmed by looking directly
    # at the composited render, not just checking the bee and badge
    # each render correctly in isolation. 0.34 is proportioned closer
    # to how macOS's own Dock badges relate to the icon behind them.
    label = str(count) if count < 100 else "99+"
    diameter = size * 0.34
    # The white halo below expands *outward* from this rect by 8% of
    # the diameter -- placing the badge flush against the corner (no
    # margin) meant that expansion had nowhere to go and got clipped
    # by the canvas edge. Pixel-scanned the actual rendered PNG's alpha
    # channel to confirm: non-transparent content touched x=size-1 and
    # y=0 exactly, a hard cut, not a rendering artifact. Margin here
    # needs to exceed the halo's 8% expansion; using 12% for headroom.
    margin = diameter * 0.16 + 1.5  # flat pixel term so it survives
    # rounding at the tray icon's much smaller render size (44pt vs the
    # widget's 128pt) -- a purely proportional margin was eaten by
    # antialiasing/rounding at that scale even though the same fraction
    # left comfortable margin at the larger size.
    rect = Foundation.NSMakeRect(size - diameter - margin, size - diameter - margin, diameter, diameter)

    AppKit.NSColor.whiteColor().setFill()
    AppKit.NSBezierPath.bezierPathWithOvalInRect_(
        Foundation.NSInsetRect(rect, -diameter * 0.08, -diameter * 0.08)
    ).fill()

    AppKit.NSColor.systemRedColor().setFill()
    AppKit.NSBezierPath.bezierPathWithOvalInRect_(rect).fill()

    badge_font = AppKit.NSFont.boldSystemFontOfSize_(diameter * 0.58)
    badge_attrs = {
        AppKit.NSFontAttributeName: badge_font,
        AppKit.NSForegroundColorAttributeName: AppKit.NSColor.whiteColor(),
    }
    text = Foundation.NSString.stringWithString_(label)
    text_size = text.sizeWithAttributes_(badge_attrs)
    text.drawAtPoint_withAttributes_(
        Foundation.NSMakePoint(
            rect.origin.x + (diameter - text_size.width) / 2,
            rect.origin.y + (diameter - text_size.height) / 2,
        ),
        badge_attrs,
    )


def _render(path: Path, size: int, count: int | None) -> Path:
    import AppKit
    import Foundation

    HOME_DIR.mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)

    image = AppKit.NSImage.alloc().initWithSize_(Foundation.NSMakeSize(size, size))
    image.lockFocus()
    _draw_bee(image, size)
    if count:
        _draw_badge(image, size, count)
    image.unlockFocus()

    bitmap = AppKit.NSBitmapImageRep.alloc().initWithData_(image.TIFFRepresentation())
    png_data = bitmap.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, None)
    png_data.writeToFile_atomically_(str(path), True)
    return path


def render_plain_bee(size: int = 512) -> Path:
    if not PLAIN_ICON_PATH.exists():
        _render(PLAIN_ICON_PATH, size, None)
    return PLAIN_ICON_PATH


def render_tray_icon(count: int, size: int = 44) -> Path:
    path = TRAY_ICON_DIR / f"tray_{count}.png"
    if not path.exists():
        _render(path, size, count)
    return path


def render_widget_icon(count: int, size: int = 128) -> Path:
    """Separate from render_tray_icon: that one's cache key is `count`
    alone (not size), so reusing it at a different size for the larger
    floating widget would collide with the menu bar's cached file."""
    path = WIDGET_ICON_DIR / f"widget_{count}.png"
    if not path.exists():
        _render(path, size, count)
    return path
