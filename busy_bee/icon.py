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

    font = AppKit.NSFont.systemFontOfSize_(size * 0.72)
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

    label = str(count) if count < 100 else "99+"
    diameter = size * 0.5
    rect = Foundation.NSMakeRect(size - diameter, size - diameter, diameter, diameter)

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
