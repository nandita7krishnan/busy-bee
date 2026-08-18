from busy_bee import colors


def test_project_color_is_deterministic():
    assert colors.project_color("busy-bee") == colors.project_color("busy-bee")


def test_project_color_is_one_of_the_palette():
    assert colors.project_color("some-project") in colors.PROJECT_COLORS


def test_project_color_differs_for_different_names_generally():
    # Not a guarantee (8 buckets, pigeonhole applies eventually), but
    # these two shouldn't collide -- catches an accidentally-constant hash.
    assert colors.project_color("alpha") != colors.project_color("zeta-project-9")
