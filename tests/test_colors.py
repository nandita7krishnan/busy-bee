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


def test_terminal_background_color_hits_target_luminance_consistently():
    # The actual point: every hue in the palette should read as
    # *equally* bright, not just "dark enough somewhere" -- a flat HSL
    # lightness target doesn't do that (blue contributes far less to
    # perceived brightness than green at the same HSL-L), which is
    # exactly what made busy-bee's blue-purple look noticeably darker
    # than proj-c's yellow-green at a supposedly identical setting.
    names = ["proj-0", "proj-1", "proj-2", "proj-3", "proj-4", "proj-5", "proj-6", "proj-7"]
    for name in names:
        hex_color = colors.terminal_background_color(name)
        r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5))
        luminance = colors._relative_luminance((r, g, b))
        assert abs(luminance - colors._TERMINAL_BG_TARGET_LUMINANCE) < 0.02


def test_terminal_background_color_caps_saturation():
    import colorsys

    for name in ("busy-bee", "social-media-optimizer", "some-other-project"):
        hex_color = colors.terminal_background_color(name)
        r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5))
        _, _lightness, saturation = colorsys.rgb_to_hls(r, g, b)
        # Tolerance for 8-bit RGB rounding on the way back from the
        # capped HLS value -- not perfectly reversible, and more
        # pronounced now that saturation is capped quite low.
        assert saturation <= colors._TERMINAL_BG_SATURATION_CAP + 0.02


def test_terminal_background_color_keeps_the_same_hue_as_project_color():
    import colorsys

    name = "busy-bee"
    bg = colors.terminal_background_color(name)
    accent = colors.project_color(name)

    bg_hue = colorsys.rgb_to_hls(*(int(bg[i : i + 2], 16) / 255 for i in (1, 3, 5)))[0]
    accent_hue = colorsys.rgb_to_hls(*(int(accent[i : i + 2], 16) / 255 for i in (1, 3, 5)))[0]
    assert abs(bg_hue - accent_hue) < 0.01
