"""Pixel-level checks on the rendered icon, not just "does it load" --
that's what let the badge-overlapping-antennae and halo-touching-edge
bugs both ship undetected the first time. Scans the actual alpha
channel of the rendered PNG rather than trusting the drawing math.
"""

import AppKit
import pytest

from busy_bee import icon


def _alpha_bounding_box(path):
    img = AppKit.NSImage.alloc().initWithContentsOfFile_(str(path))
    rep = AppKit.NSBitmapImageRep.alloc().initWithData_(img.TIFFRepresentation())
    w, h = rep.pixelsWide(), rep.pixelsHigh()
    min_x, min_y, max_x, max_y = w, h, 0, 0
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            if rep.colorAtX_y_(x, y).alphaComponent() > 0.05:
                min_x, min_y = min(min_x, x), min(min_y, y)
                max_x, max_y = max(max_x, x), max(max_y, y)
    return {
        "width": w,
        "height": h,
        "left_margin": min_x / w,
        "right_margin": (w - max_x) / w,
        "top_margin": min_y / h,
        "bottom_margin": (h - max_y) / h,
    }


@pytest.fixture(autouse=True)
def isolated_icon_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(icon, "PLAIN_ICON_PATH", tmp_path / "bee_icon.png")
    monkeypatch.setattr(icon, "TRAY_ICON_DIR", tmp_path / "tray_icons")
    monkeypatch.setattr(icon, "WIDGET_ICON_DIR", tmp_path / "widget_icons")
    yield


def test_bare_bee_has_margin_on_every_side():
    path = icon.render_widget_icon(0, size=128)
    margins = _alpha_bounding_box(path)
    # A real emoji glyph's ink extends beyond the font's nominal
    # metrics box -- some margin here isn't optional headroom, it's
    # required or the drawn content clips against the canvas edge.
    assert margins["left_margin"] > 0.05
    assert margins["right_margin"] > 0.05
    assert margins["top_margin"] > 0.05
    assert margins["bottom_margin"] > 0.05


def test_badged_bee_has_margin_on_every_side():
    # The badge sits in the same top-right quadrant as the bee's
    # antennae -- this is the case that actually clipped in practice
    # (both the badge's own white halo touching the canvas edge, and
    # the badge visually swallowing the antennae), not the bare bee.
    for count in (1, 2, 9, 42):
        path = icon.render_widget_icon(count, size=128)
        margins = _alpha_bounding_box(path)
        assert margins["left_margin"] > 0, f"count={count}"
        assert margins["right_margin"] > 0, f"count={count}"
        assert margins["top_margin"] > 0, f"count={count}"
        assert margins["bottom_margin"] > 0, f"count={count}"


def test_badged_tray_icon_has_margin_on_every_side():
    # Same badge-halo-touching-edge bug, but specifically at the tray
    # icon's much smaller render size (44pt vs the widget's 128pt) --
    # a margin defined as a pure fraction of the badge diameter turned
    # out to round away to nothing at this scale even though the same
    # fraction left real margin at the larger widget size. Caught by
    # actually checking this size, not just assuming smaller scales the
    # same way.
    for count in (1, 2, 9, 42):
        path = icon.render_tray_icon(count, size=44)
        margins = _alpha_bounding_box(path)
        assert margins["left_margin"] > 0, f"count={count}"
        assert margins["right_margin"] > 0, f"count={count}"
        assert margins["top_margin"] > 0, f"count={count}"
        assert margins["bottom_margin"] > 0, f"count={count}"


