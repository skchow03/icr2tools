import math

from sg_viewer.curve_solver import (
    _curve_arc_length,
    _curve_orientation_hint,
    _curve_tangent_heading,
    _project_point_along_heading,
    _solve_curve_drag,
    solve_curve_with_heading_constraint,
)
from sg_viewer.sg_model import SectionPreview


def _make_section(
    *,
    start: tuple[float, float],
    end: tuple[float, float],
    center: tuple[float, float] | None = None,
    radius: float | None = None,
    start_heading: tuple[float, float] | None = None,
    end_heading: tuple[float, float] | None = None,
    length: float | None = None,
) -> SectionPreview:
    return SectionPreview(
        section_id=1,
        type_name="curve",
        previous_id=0,
        next_id=0,
        start=start,
        end=end,
        start_dlong=0.0,
        length=length or 0.0,
        center=center,
        sang1=start_heading[0] if start_heading else None,
        sang2=start_heading[1] if start_heading else None,
        eang1=end_heading[0] if end_heading else None,
        eang2=end_heading[1] if end_heading else None,
        radius=radius,
        start_heading=start_heading,
        end_heading=end_heading,
        polyline=[],
    )


def test_curve_orientation_hint_prefers_geometry():
    start = (0.0, 0.0)
    end = (1.0, 0.0)
    center_left = (0.5, 1.0)
    center_right = (0.5, -1.0)

    ccw_section = _make_section(start=start, end=end, center=center_left)
    cw_section = _make_section(start=start, end=end, center=center_right)

    assert _curve_orientation_hint(ccw_section) == 1.0
    assert _curve_orientation_hint(cw_section) == -1.0


def test_solve_curve_drag_prefers_existing_radius():
    start = (0.0, 0.0)
    end = (100.0, 0.0)
    radius = 100.0
    center = (50.0, math.sqrt(radius**2 - 50.0**2))
    start_heading = _curve_tangent_heading(center, start, 1.0)
    end_heading = _curve_tangent_heading(center, end, 1.0)
    length = _curve_arc_length(center, start, end, radius)
    sect = _make_section(
        start=start,
        end=end,
        center=center,
        radius=radius,
        start_heading=start_heading,
        end_heading=end_heading,
        length=length,
    )

    solved = _solve_curve_drag(sect, start, end, tolerance=1.0)

    assert solved is not None
    assert solved.radius is not None
    assert math.isclose(solved.radius, radius, rel_tol=1e-6)
    assert solved.center is not None
    assert math.isclose(solved.center[0], center[0], rel_tol=1e-6)
    assert math.isclose(solved.center[1], center[1], rel_tol=1e-6)


def test_solve_curve_drag_preserves_fixed_heading():
    start = (10.0, 0.0)
    end = (0.0, 10.0)
    center = (0.0, 0.0)
    radius = math.hypot(*start)
    end_heading = _curve_tangent_heading(center, end, 1.0)
    start_heading = _curve_tangent_heading(center, start, 1.0)
    length = _curve_arc_length(center, start, end, radius)

    sect = _make_section(
        start=start,
        end=end,
        center=center,
        radius=radius,
        start_heading=start_heading,
        end_heading=end_heading,
        length=length,
    )

    moved_start = (8.0, -6.0)
    solved = _solve_curve_drag(sect, moved_start, end, tolerance=1.0)

    assert solved is not None
    assert solved.end_heading is not None
    assert end_heading is not None
    dot = solved.end_heading[0] * end_heading[0] + solved.end_heading[1] * end_heading[1]
    assert math.isclose(dot, 1.0, rel_tol=1e-6)


def test_project_point_along_heading_projects_correctly():
    origin = (1.0, 1.0)
    heading = (1.0, 1.0)
    target = (4.0, 5.0)

    projected = _project_point_along_heading(origin, heading, target)

    assert projected is not None
    expected_projection = (target[0] - origin[0] + target[1] - origin[1]) / math.sqrt(2)
    step = expected_projection / math.sqrt(2)
    assert math.isclose(projected[0], origin[0] + step)
    assert math.isclose(projected[1], origin[1] + step)


def test_solve_curve_with_heading_constraint_matches_requested_heading():
    start = (10.0, 0.0)
    end = (0.0, 10.0)
    center = (0.0, 0.0)
    radius = math.hypot(*start)
    end_heading = _curve_tangent_heading(center, end, 1.0)
    start_heading = _curve_tangent_heading(center, start, 1.0)
    length = _curve_arc_length(center, start, end, radius)

    sect = _make_section(
        start=start,
        end=end,
        center=center,
        radius=radius,
        start_heading=start_heading,
        end_heading=end_heading,
        length=length,
    )

    target_heading = (-1.0, 0.0)
    target_end = (0.0, 12.0)

    solved = solve_curve_with_heading_constraint(
        sect,
        start,
        target_end,
        target_heading,
        heading_applies_to_start=False,
        tolerance=1.0,
    )

    assert solved is not None
    assert solved.end == target_end
    assert solved.end_heading is not None

    normalized_target = (
        target_heading[0] / math.hypot(*target_heading),
        target_heading[1] / math.hypot(*target_heading),
    )
    dot = solved.end_heading[0] * normalized_target[0] + solved.end_heading[1] * normalized_target[1]
    assert math.isclose(dot, 1.0, rel_tol=1e-6)
