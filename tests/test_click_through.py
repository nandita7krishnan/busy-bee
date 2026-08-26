import re
from pathlib import Path
from types import SimpleNamespace

from busy_bee import click_through

WIDGET_HTML = Path(__file__).resolve().parent.parent / "busy_bee" / "ui" / "widget.html"

WINDOW_ORIGIN_X = 100.0
WINDOW_ORIGIN_Y = 200.0
WINDOW_SIZE = 245.0  # matches app.WIDGET_SIZE


class _FakeWindow:
    def __init__(self):
        self.origin = SimpleNamespace(x=WINDOW_ORIGIN_X, y=WINDOW_ORIGIN_Y)
        self.ignores_mouse_events = None
        self.set_calls = 0

    def frame(self):
        return SimpleNamespace(
            origin=self.origin,
            size=SimpleNamespace(width=WINDOW_SIZE, height=WINDOW_SIZE),
        )

    def setIgnoresMouseEvents_(self, value):  # noqa: N802 -- AppKit selector
        self.ignores_mouse_events = value
        self.set_calls += 1

    def isVisible(self):  # noqa: N802 -- AppKit selector
        return True


def _controller(mask=None):
    c = click_through.ClickThrough(_FakeWindow(), lambda: None)
    c._mask = mask
    return c


def _screen_point(u, v):
    """Screen coordinates (y-up) of a point at (u, v) within the icon,
    each 0..1 across the icon's own box."""
    inset = WINDOW_SIZE * (1 - click_through.ICON_FRACTION) / 2
    span = WINDOW_SIZE * click_through.ICON_FRACTION
    css_x = inset + u * span
    css_y = inset + v * span
    return WINDOW_ORIGIN_X + css_x, WINDOW_ORIGIN_Y + (WINDOW_SIZE - css_y)


def _mask_with_cell(gx, gy):
    dim = click_through._MASK_DIM
    mask = bytearray(dim * dim)
    mask[gy * dim + gx] = 1
    return mask


def test_icon_fraction_matches_the_widget_css():
    # The hit test maps screen points through the icon's on-page box, so
    # a CSS-only resize would silently aim the mask at the wrong region.
    css = WIDGET_HTML.read_text()
    block = css[css.index("#icon {") :]
    percent = float(re.search(r"width:\s*([\d.]+)%", block).group(1))
    assert percent / 100 == click_through.ICON_FRACTION


def test_the_silhouette_is_solid():
    controller = _controller(_mask_with_cell(64, 64))
    dim = click_through._MASK_DIM
    assert controller.hits(*_screen_point(64.5 / dim, 64.5 / dim))


def test_transparent_pixels_inside_the_icon_box_are_click_through():
    # Even within the icon's own box most pixels are empty -- the bee is
    # a silhouette, not a square.
    controller = _controller(_mask_with_cell(64, 64))
    dim = click_through._MASK_DIM
    assert not controller.hits(*_screen_point(10.5 / dim, 10.5 / dim))


def test_the_empty_margin_around_the_icon_is_click_through():
    # The reported bug: the window is much larger than the art, and the
    # margin used to swallow clicks meant for the app behind it.
    controller = _controller(bytearray([1]) * (click_through._MASK_DIM ** 2))
    assert not controller.hits(WINDOW_ORIGIN_X + 4, WINDOW_ORIGIN_Y + WINDOW_SIZE - 4)


def test_a_point_outside_the_window_misses():
    controller = _controller(bytearray([1]) * (click_through._MASK_DIM ** 2))
    assert not controller.hits(WINDOW_ORIGIN_X - 50, WINDOW_ORIGIN_Y + 50)


def test_without_a_mask_the_window_stays_solid():
    # Fall back to the old always-clickable behaviour rather than a
    # widget that can't be clicked at all.
    assert _controller(None).hits(*_screen_point(0.5, 0.5))


def test_dilate_grows_a_cell_in_both_axes():
    dim = 8
    mask = bytearray(dim * dim)
    mask[4 * dim + 4] = 1

    grown = click_through._dilate(mask, dim, 1)

    assert [(i % dim, i // dim) for i, v in enumerate(grown) if v] == [
        (x, y) for y in (3, 4, 5) for x in (3, 4, 5)
    ]


def test_dilate_is_a_noop_at_zero_radius():
    mask = bytearray([0, 1, 0, 0])
    assert click_through._dilate(mask, 2, 0) is mask


def test_the_window_is_only_told_about_actual_changes():
    controller = _controller(_mask_with_cell(64, 64))
    window = controller._window
    controller._solid = False

    controller._apply(False)
    assert window.set_calls == 0

    controller._apply(True)
    controller._apply(True)
    assert window.set_calls == 1
    assert window.ignores_mouse_events is False
