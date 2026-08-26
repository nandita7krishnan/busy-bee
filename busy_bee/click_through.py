"""Per-pixel click-through for the floating bee widget.

The widget is a frameless, transparent NSWindow -- but transparent
pixels are only a *drawing* property. As far as AppKit's hit testing is
concerned the window is still a solid rectangle, so every click
anywhere in its frame goes to the widget instead of whatever is behind
it. That rectangle is much bigger than the bee looks: the window is
WIDGET_SIZE square and widget.html draws the icon at ICON_FRACTION of
it, centered, so there is a wide empty margin on all four sides that
silently swallowed clicks on the app underneath.

The fix is to keep the window click-through by default
(`ignoresMouseEvents`) and only make it solid while the pointer is
actually over the bee -- its real silhouette, read out of the rendered
icon's alpha channel, which includes the notification badge since
that's drawn into the same PNG. A timer polls the pointer rather than
watching mouse-moved events, because a window that is currently
ignoring mouse events doesn't receive them at all, so an event-driven
version would have no way back once it turned itself off.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Fraction of the window's width the icon occupies -- must match
# `#icon { width/height }` in ui/widget.html (test_click_through.py
# checks the two agree).
ICON_FRACTION = 0.55

# 0-255. The bee is an emoji glyph, so its edges are antialiased into
# fully transparent surroundings; a low threshold keeps the whole
# silhouette without claiming clicks on the faint outer fringe.
_ALPHA_THRESHOLD = 32

# Resolution the silhouette is sampled at. 128 across an icon that
# renders ~135pt wide is finer than a pointer can be aimed anyway.
_MASK_DIM = 128

# The icon is animated (bee-float in widget.html: a couple of px of
# translate plus a +/-4deg rotate), so at any given moment it sits
# slightly off where the static mask says it is. Grow the hit region by
# roughly that much rather than trying to track the animation's phase.
_DRIFT_PT = 6.0

# 50Hz. The pointer has to be over the bee *before* the click for the
# window to be solid by then, so this wants to be comfortably faster
# than a person can move-and-click.
_POLL_INTERVAL = 0.02

_controller = None  # module-scope: an NSTimer's target is not retained


def _alpha_mask(path: Path, dim: int = _MASK_DIM) -> bytearray | None:
    """Redraws the icon into a known 8-bit RGBA bitmap and returns a
    dim*dim row-major mask, 1 where the art is opaque enough to claim a
    click. Drawing into our own bitmap rather than reading the PNG's
    own representation avoids having to care what format it came in as
    -- these render as 16-bit-per-sample, whose byte order is not worth
    reasoning about for this."""
    import AppKit
    import Foundation

    image = AppKit.NSImage.alloc().initWithContentsOfFile_(str(path))
    if image is None:
        return None

    rep = AppKit.NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, dim, dim, 8, 4, True, False, AppKit.NSCalibratedRGBColorSpace, dim * 4, 32
    )
    if rep is None:
        return None

    context = AppKit.NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    AppKit.NSGraphicsContext.saveGraphicsState()
    AppKit.NSGraphicsContext.setCurrentContext_(context)
    image.drawInRect_fromRect_operation_fraction_(
        Foundation.NSMakeRect(0, 0, dim, dim),
        Foundation.NSZeroRect,
        AppKit.NSCompositingOperationCopy,
        1.0,
    )
    AppKit.NSGraphicsContext.restoreGraphicsState()

    data = rep.bitmapData()
    mask = bytearray(dim * dim)
    for i in range(dim * dim):
        if data[i * 4 + 3] >= _ALPHA_THRESHOLD:
            mask[i] = 1
    return mask


def _dilate(mask: bytearray, dim: int, radius: int) -> bytearray:
    """Grows the mask by `radius` cells in every direction, as two
    separable passes. Walks the set cells rather than every cell -- the
    bee covers a minority of the mask."""
    if radius <= 0:
        return mask

    horizontal = bytearray(len(mask))
    for y in range(dim):
        row = y * dim
        for x in range(dim):
            if mask[row + x]:
                for i in range(max(0, x - radius), min(dim, x + radius + 1)):
                    horizontal[row + i] = 1

    grown = bytearray(len(mask))
    for y in range(dim):
        row = y * dim
        for x in range(dim):
            if horizontal[row + x]:
                for j in range(max(0, y - radius), min(dim, y + radius + 1)):
                    grown[j * dim + x] = 1
    return grown


class ClickThrough:
    """Keeps the widget window click-through except over the bee itself."""

    def __init__(self, ns_window, icon_path_provider, fraction: float = ICON_FRACTION):
        self._window = ns_window
        self._icon_path_provider = icon_path_provider
        self._fraction = fraction
        self._mask: bytearray | None = None
        self._mask_path: Path | None = None
        self._poller = None
        self._solid = True  # forced through setIgnoresMouseEvents on the first poll
        self._timer = None

    # -- mask -----------------------------------------------------------

    def refresh_mask(self) -> None:
        """Rebuilds the silhouette if the icon has changed. The badge
        appearing, disappearing or changing width all change which
        pixels are opaque, so the mask can't be built once at startup.
        Called from the app's existing 5s tick rather than from poll()
        -- the count behind it is a database read, which has no place
        running at the polling rate."""
        path = self._icon_path_provider()
        if path is None or path == self._mask_path:
            return
        mask = _alpha_mask(path)
        if mask is None:
            return
        frame = self._window.frame()
        icon_pt = frame.size.width * self._fraction
        radius = round(_DRIFT_PT / (icon_pt / _MASK_DIM)) if icon_pt else 0
        self._mask = _dilate(mask, _MASK_DIM, radius)
        self._mask_path = path

    # -- hit testing ----------------------------------------------------

    def hits(self, screen_x: float, screen_y: float) -> bool:
        if self._mask is None:
            return True  # no silhouette yet: behave as before, solid
        frame = self._window.frame()
        width, height = frame.size.width, frame.size.height
        if not width or not height:
            return False

        # Screen coordinates are y-up; the page's are y-down from the
        # window's top edge, which is what the icon rect is expressed in.
        x = screen_x - frame.origin.x
        y = height - (screen_y - frame.origin.y)

        inset = width * (1 - self._fraction) / 2
        span = width * self._fraction
        u = (x - inset) / span
        v = (y - inset) / span
        if not (0.0 <= u < 1.0 and 0.0 <= v < 1.0):
            return False
        return bool(self._mask[int(v * _MASK_DIM) * _MASK_DIM + int(u * _MASK_DIM)])

    # -- polling --------------------------------------------------------

    def _apply(self, solid: bool) -> None:
        if solid == self._solid:
            return
        self._solid = solid
        self._window.setIgnoresMouseEvents_(not solid)

    def poll(self) -> None:
        import AppKit

        # Never flip mid-drag. easy_drag moves the window to follow the
        # pointer, so the pointer stays on the bee in practice -- but if
        # it ever got ahead of the window, turning the window
        # click-through underneath a held mouse button would drop the
        # drag on the floor.
        if AppKit.NSEvent.pressedMouseButtons() != 0:
            return

        if self._window.isVisible():
            location = AppKit.NSEvent.mouseLocation()
            self._apply(self.hits(location.x, location.y))

    def start(self) -> None:
        import AppKit

        # Defining the poller class is a one-time ObjC class
        # registration -- running start() twice would try to register
        # the same name again and raise.
        if self._timer is not None:
            return

        class _Poller(AppKit.NSObject):
            def tick_(poller_self, _timer):  # noqa: N805 -- PyObjC selector
                self.poll()

        self._poller = _Poller.alloc().init()
        self._timer = AppKit.NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(
            _POLL_INTERVAL, self._poller, "tick:", None, True
        )
        # Common modes, not the default one: during a window drag or an
        # open menu the run loop switches modes and a default-mode timer
        # stops firing until that ends.
        AppKit.NSRunLoop.currentRunLoop().addTimer_forMode_(
            self._timer, AppKit.NSRunLoopCommonModes
        )
        self.refresh_mask()
        self._window.setIgnoresMouseEvents_(True)
        self._solid = False


def install(widget_window, icon_path_provider) -> ClickThrough | None:
    """Wires click-through onto the pywebview window. Main thread only
    (it touches AppKit). Returns None if the native window isn't
    reachable, leaving the widget solid as before rather than failing
    the app's startup over it -- but says so, since the symptom
    otherwise is just the original bug quietly still being there."""
    global _controller

    if _controller is not None:
        return _controller

    from webview.platforms.cocoa import BrowserView

    browser_view = BrowserView.instances.get(widget_window.uid)
    ns_window = getattr(browser_view, "window", None)
    if ns_window is None:
        print(
            "busy-bee: no native window for the widget -- click-through disabled, "
            "the widget's transparent margin will keep swallowing clicks.",
            file=sys.stderr,
        )
        return None

    _controller = ClickThrough(ns_window, icon_path_provider)
    _controller.start()
    return _controller
