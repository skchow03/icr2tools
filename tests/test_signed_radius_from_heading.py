from sg_viewer.sg_geometry import signed_radius_from_heading


def test_signed_radius_prefers_left_when_cross_positive():
    heading = (1.0, 0.0)
    start = (0.0, 0.0)
    center_left = (0.0, 10.0)

    signed_radius = signed_radius_from_heading(heading, start, center_left, 50.0)

    assert signed_radius == 50.0


def test_signed_radius_prefers_right_when_cross_negative():
    heading = (0.0, 1.0)
    start = (0.0, 0.0)
    center_right = (5.0, 0.0)

    signed_radius = signed_radius_from_heading(heading, start, center_right, 75.0)

    assert signed_radius == -75.0


def test_signed_radius_returns_original_when_direction_unknown():
    heading = (0.0, 0.0)
    start = (1.0, 1.0)
    center = (2.0, 2.0)

    signed_radius = signed_radius_from_heading(heading, start, center, 25.0)

    assert signed_radius == 25.0
