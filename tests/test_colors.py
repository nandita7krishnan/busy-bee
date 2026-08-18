from busy_bee import colors


def test_project_color_is_deterministic():
    assert colors.project_color("busy-bee") == colors.project_color("busy-bee")


def test_project_color_is_one_of_the_palette():
    assert colors.project_color("some-project") in colors.PROJECT_COLORS


def test_project_color_differs_for_different_names_generally():
    # Not a guarantee (8 buckets, pigeonhole applies eventually), but
    # these two shouldn't collide -- catches an accidentally-constant hash.
    assert colors.project_color("alpha") != colors.project_color("zeta-project-9")


def test_terminal_background_color_is_deterministic():
    assert colors.terminal_background_color("busy-bee") == colors.terminal_background_color(
        "busy-bee"
    )


def test_terminal_background_color_is_dark():
    # The whole point: readable as a full-screen background, unlike
    # the vivid card-accent palette it's derived from.
    import colorsys

    for name in ("busy-bee", "social-media-optimizer", "some-other-project"):
        hex_color = colors.terminal_background_color(name)
        r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5))
        _, lightness, saturation = colorsys.rgb_to_hls(r, g, b)
        assert lightness < 0.25
        # Small tolerance for 8-bit RGB rounding on the way back from
        # the capped HLS value -- not perfectly reversible.
        assert saturation <= colors._TERMINAL_BG_SATURATION_CAP + 0.01


def test_terminal_background_color_keeps_the_same_hue_as_project_color():
    import colorsys

    name = "busy-bee"
    bg = colors.terminal_background_color(name)
    accent = colors.project_color(name)

    bg_hue = colorsys.rgb_to_hls(*(int(bg[i : i + 2], 16) / 255 for i in (1, 3, 5)))[0]
    accent_hue = colorsys.rgb_to_hls(*(int(accent[i : i + 2], 16) / 255 for i in (1, 3, 5)))[0]
    assert abs(bg_hue - accent_hue) < 0.01
