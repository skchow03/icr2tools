from sg_viewer.model.preview_fsection import PreviewFSection
from types import SimpleNamespace
from sg_viewer.services.sg_integrity_checks import (
    IntegrityProgress,
    _ft_to_world,
    _world_to_ft,
    build_integrity_report,
)


def _section(
    *,
    section_id: int,
    start: tuple[float, float],
    end: tuple[float, float],
    previous_id: int | None = None,
    next_id: int | None = None,
):
    return SimpleNamespace(
        section_id=section_id,
        source_section_id=section_id,
        type_name="straight",
        previous_id=section_id if previous_id is None else previous_id,
        next_id=section_id if next_id is None else next_id,
        start=start,
        end=end,
        start_dlong=0.0,
        length=((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5,
        center=None,
        sang1=None,
        sang2=None,
        eang1=None,
        eang2=None,
        radius=None,
        start_heading=(1.0, 0.0),
        end_heading=(1.0, 0.0),
        polyline=[start, end],
    )

def _curve_section(*, section_id: int, radius_ft: float):
    radius_world = _ft_to_world(radius_ft)
    arc_radians = 1.0
    return SimpleNamespace(
        section_id=section_id,
        source_section_id=section_id,
        type_name="curve",
        previous_id=section_id,
        next_id=section_id,
        start=(0.0, 0.0),
        end=(radius_world, radius_world),
        start_dlong=0.0,
        length=radius_world * arc_radians,
        center=(0.0, radius_world),
        sang1=0.0,
        sang2=0.0,
        eang1=0.0,
        eang2=0.0,
        radius=radius_world,
        start_heading=(1.0, 0.0),
        end_heading=(0.0, 1.0),
        polyline=[(0.0, 0.0), (radius_world, 0.0)],
    )


def test_feet_world_conversion_uses_6000_units_per_foot() -> None:
    assert _ft_to_world(1.0) == 6000.0
    assert _world_to_ft(6000.0) == 1.0


def test_integrity_report_flags_perpendicular_centerline_spacing_violation() -> None:
    section_a = _section(section_id=0, start=(0.0, 0.0), end=(_ft_to_world(200.0), 0.0))
    section_b = _section(
        section_id=1,
        start=(_ft_to_world(100.0), _ft_to_world(-40.0)),
        end=(_ft_to_world(100.0), _ft_to_world(40.0)),
    )

    report = build_integrity_report(
        [section_a, section_b],
        [[], []],
    ).text

    assert "Sections with < 80 ft perpendicular spacing: 1" in report
    assert "Sampling step: 10 ft" in report



def test_integrity_report_flags_parallel_close_centerline_spacing_violation() -> None:
    section_a = _section(section_id=0, start=(0.0, 0.0), end=(_ft_to_world(200.0), 0.0))
    section_b = _section(
        section_id=1,
        start=(0.0, _ft_to_world(60.0)),
        end=(_ft_to_world(200.0), _ft_to_world(60.0)),
    )

    report = build_integrity_report(
        [section_a, section_b],
        [[], []],
    ).text

    assert "Sections with < 80 ft perpendicular spacing: 2" in report



def test_integrity_report_does_not_flag_collinear_sections_with_only_longitudinal_proximity() -> None:
    section_a = _section(
        section_id=0,
        start=(0.0, 0.0),
        end=(_ft_to_world(200.0), 0.0),
    )
    section_b = _section(
        section_id=1,
        start=(_ft_to_world(220.0), 0.0),
        end=(_ft_to_world(420.0), 0.0),
    )

    report = build_integrity_report([section_a, section_b], [[], []]).text

    assert "Sections with < 80 ft perpendicular spacing: none" in report

def test_integrity_report_ignores_adjacent_perpendicular_centerline_spacing_violation() -> None:
    section_a = _section(
        section_id=0,
        start=(0.0, 0.0),
        end=(_ft_to_world(200.0), 0.0),
        previous_id=1,
        next_id=1,
    )
    section_b = _section(
        section_id=1,
        start=(_ft_to_world(100.0), _ft_to_world(-40.0)),
        end=(_ft_to_world(100.0), _ft_to_world(40.0)),
        previous_id=0,
        next_id=0,
    )

    report = build_integrity_report(
        [section_a, section_b],
        [[], []],
    ).text

    assert "Sections with < 80 ft perpendicular spacing: 1" not in report


def test_integrity_report_flags_boundary_closer_to_other_centerline() -> None:
    section_a = _section(section_id=0, start=(0.0, 0.0), end=(_ft_to_world(100.0), 0.0))
    section_b = _section(section_id=1, start=(0.0, _ft_to_world(10.0)), end=(_ft_to_world(100.0), _ft_to_world(10.0)))
    wide_left_boundary = PreviewFSection(
        start_dlat=_ft_to_world(20.0),
        end_dlat=_ft_to_world(20.0),
        surface_type=0,
        type2=0,
    )

    report = build_integrity_report(
        [section_a, section_b],
        [[wide_left_boundary], []],
    ).text

    assert "Boundary points closer to a different centerline: 1" in report
    assert "section 0 left boundary" in report


def test_integrity_report_ignores_adjacent_boundary_ownership_violation() -> None:
    section_a = _section(
        section_id=0,
        start=(0.0, 0.0),
        end=(_ft_to_world(100.0), 0.0),
        previous_id=1,
        next_id=1,
    )
    section_b = _section(
        section_id=1,
        start=(0.0, _ft_to_world(10.0)),
        end=(_ft_to_world(100.0), _ft_to_world(10.0)),
        previous_id=0,
        next_id=0,
    )
    wide_left_boundary = PreviewFSection(
        start_dlat=_ft_to_world(20.0),
        end_dlat=_ft_to_world(20.0),
        surface_type=0,
        type2=0,
    )

    report = build_integrity_report(
        [section_a, section_b],
        [[wide_left_boundary], []],
    ).text

    assert "Boundary points closer to a different centerline: 1" not in report




def test_segment_spatial_index_matches_unindexed_probe_proximity() -> None:
    from sg_viewer.services.sg_integrity_checks import (
        _build_segment_spatial_index,
        _find_probe_proximity,
    )

    section_a = _section(section_id=0, start=(0.0, 0.0), end=(_ft_to_world(200.0), 0.0))
    section_b = _section(
        section_id=1,
        start=(_ft_to_world(100.0), _ft_to_world(-40.0)),
        end=(_ft_to_world(100.0), _ft_to_world(40.0)),
    )
    section_far = _section(
        section_id=2,
        start=(_ft_to_world(2000.0), _ft_to_world(2000.0)),
        end=(_ft_to_world(2100.0), _ft_to_world(2000.0)),
    )

    sections = [section_a, section_b, section_far]
    all_segments: list[tuple[int, tuple[float, float], tuple[float, float]]] = []
    for idx, section in enumerate(sections):
        all_segments.append((idx, section.polyline[0], section.polyline[1]))

    sample_point = (_ft_to_world(100.0), 0.0)
    sample_normal = (0.0, 1.0)
    probe_half_len_world = _ft_to_world(80.0)

    spatial_index = _build_segment_spatial_index(all_segments, probe_half_len_world)

    indexed_hit = _find_probe_proximity(
        0,
        sample_point,
        sample_normal,
        probe_half_len_world,
        all_segments,
        spatial_index,
        sections,
    )
    unindexed_hit = _find_probe_proximity(
        0,
        sample_point,
        sample_normal,
        probe_half_len_world,
        all_segments,
        None,
        sections,
    )

    assert indexed_hit == 1
    assert indexed_hit == unindexed_hit

def test_integrity_report_emits_progress_updates() -> None:
    section_a = _section(section_id=0, start=(0.0, 0.0), end=(_ft_to_world(200.0), 0.0))
    section_b = _section(
        section_id=1,
        start=(_ft_to_world(100.0), _ft_to_world(-40.0)),
        end=(_ft_to_world(100.0), _ft_to_world(40.0)),
    )

    updates: list[IntegrityProgress] = []

    build_integrity_report([section_a, section_b], [[], []], on_progress=updates.append)

    assert updates
    assert updates[0].message == "Preparing integrity checks"
    assert updates[-1].message == "Integrity checks complete"
    assert updates[-1].current == updates[-1].total


def test_nearest_section_distance_index_matches_unindexed_with_sparse_long_segments() -> None:
    from sg_viewer.services.sg_integrity_checks import (
        _build_section_segment_spatial_index,
        _nearest_section_distance,
    )

    section_source = _section(
        section_id=0,
        start=(0.0, 0.0),
        end=(_ft_to_world(10.0), 0.0),
    )
    section_sparse_long = _section(
        section_id=1,
        start=(0.0, _ft_to_world(1500.0)),
        end=(_ft_to_world(4000.0), _ft_to_world(1500.0)),
    )
    section_far = _section(
        section_id=2,
        start=(0.0, _ft_to_world(2500.0)),
        end=(_ft_to_world(4000.0), _ft_to_world(2500.0)),
    )

    sections = [section_source, section_sparse_long, section_far]
    sample_step_world = _ft_to_world(10.0)
    spatial_index = _build_section_segment_spatial_index(sections, sample_step_world)
    probe_point = (_ft_to_world(2000.0), _ft_to_world(1499.7))

    indexed_nearest = _nearest_section_distance(
        probe_point,
        sections,
        exclude_index=0,
        spatial_index=spatial_index,
    )
    unindexed_nearest = _nearest_section_distance(
        probe_point,
        sections,
        exclude_index=0,
        spatial_index=None,
    )

    assert indexed_nearest[0] == 1
    assert indexed_nearest == unindexed_nearest


def test_integrity_report_centerline_spacing_threshold_boundary_and_formatting() -> None:
    section_a = _section(section_id=0, start=(0.0, 0.0), end=(_ft_to_world(200.0), 0.0))
    section_at_threshold = _section(
        section_id=1,
        start=(0.0, _ft_to_world(80.0)),
        end=(_ft_to_world(200.0), _ft_to_world(80.0)),
    )

    report_at_threshold = build_integrity_report([section_a, section_at_threshold], [[], []]).text

    assert "Sections with < 80 ft perpendicular spacing: none" in report_at_threshold

    section_below_threshold = _section(
        section_id=1,
        start=(0.0, _ft_to_world(79.99)),
        end=(_ft_to_world(200.0), _ft_to_world(79.99)),
    )

    report_below_threshold = build_integrity_report([section_a, section_below_threshold], [[], []]).text

    assert "Sections with < 80 ft perpendicular spacing: 2" in report_below_threshold
    assert "(0.0, 80.0) ft intersects section 1 within ±80 ft" in report_below_threshold


def test_integrity_report_curve_radius_threshold_boundary_and_formatting() -> None:
    radius_threshold = _curve_section(section_id=0, radius_ft=50.0)
    radius_below = _curve_section(section_id=1, radius_ft=49.99)

    report = build_integrity_report([radius_threshold, radius_below], [[], []]).text

    assert "Curves with radius < 50 ft: 1" in report
    assert "section 1: radius=49.99 ft" in report
    assert "section 0: radius=50.00 ft" not in report


def test_boundary_ownership_numpy_batching_matches_fallback_and_uses_batched_distances(monkeypatch) -> None:
    import sg_viewer.services.sg_integrity_checks as integrity_checks

    if integrity_checks.np is None:
        return

    section_a = _section(section_id=0, start=(0.0, 0.0), end=(_ft_to_world(300.0), 0.0))
    section_b = _section(section_id=1, start=(0.0, _ft_to_world(12.0)), end=(_ft_to_world(300.0), _ft_to_world(12.0)))
    section_c = _section(section_id=2, start=(0.0, _ft_to_world(-80.0)), end=(_ft_to_world(300.0), _ft_to_world(-80.0)))
    wide_left_boundary = PreviewFSection(
        start_dlat=_ft_to_world(24.0),
        end_dlat=_ft_to_world(24.0),
        surface_type=0,
        type2=0,
    )

    sections = [section_a, section_b, section_c]
    fsects_by_section = [[wide_left_boundary], [], []]
    sample_step_world = _ft_to_world(10.0)

    progress_numpy = integrity_checks._ProgressTracker(total=1, callback=None)
    progress_fallback = integrity_checks._ProgressTracker(total=1, callback=None)

    scalar_calls = 0
    batched_calls = 0
    original_scalar = integrity_checks._point_to_polyline_distance_numpy
    original_batched = integrity_checks._points_to_polyline_distance_numpy

    def _counted_scalar(*args, **kwargs):
        nonlocal scalar_calls
        scalar_calls += 1
        return original_scalar(*args, **kwargs)

    def _counted_batched(*args, **kwargs):
        nonlocal batched_calls
        batched_calls += 1
        return original_batched(*args, **kwargs)

    monkeypatch.setattr(integrity_checks, "_point_to_polyline_distance_numpy", _counted_scalar)
    monkeypatch.setattr(integrity_checks, "_points_to_polyline_distance_numpy", _counted_batched)

    numpy_lines = integrity_checks._boundary_centerline_ownership_report_numpy(
        sections,
        fsects_by_section,
        sample_step_world,
        progress_numpy,
    )
    fallback_lines = integrity_checks._boundary_centerline_ownership_report_fallback(
        sections,
        fsects_by_section,
        sample_step_world,
        progress_fallback,
    )

    assert numpy_lines == fallback_lines
    assert batched_calls > 0
    assert scalar_calls == 0


def test_integrity_report_uses_start_end_when_polyline_is_missing_for_spacing_checks() -> None:
    section_a = _section(section_id=0, start=(0.0, 0.0), end=(_ft_to_world(200.0), 0.0))
    section_b = _section(
        section_id=1,
        start=(0.0, _ft_to_world(60.0)),
        end=(_ft_to_world(200.0), _ft_to_world(60.0)),
    )
    section_b.polyline = [section_b.start]

    report = build_integrity_report([section_a, section_b], [[], []]).text

    assert "Sections with < 80 ft perpendicular spacing: 2" in report


def test_integrity_report_uses_curve_center_radius_when_radius_field_missing() -> None:
    radius_ft = 49.99
    radius_world = _ft_to_world(radius_ft)
    section = SimpleNamespace(
        section_id=0,
        source_section_id=0,
        type_name="curve",
        previous_id=0,
        next_id=0,
        start=(0.0, 0.0),
        end=(radius_world, radius_world),
        start_dlong=0.0,
        length=radius_world,
        center=(0.0, radius_world),
        sang1=0.0,
        sang2=0.0,
        eang1=0.0,
        eang2=0.0,
        radius=None,
        start_heading=(1.0, 0.0),
        end_heading=(0.0, 1.0),
        polyline=[(0.0, 0.0), (radius_world, 0.0)],
    )

    report = build_integrity_report([section], [[]]).text

    assert "Curves with radius < 50 ft: 1" in report
    assert "section 0: radius=49.99 ft" in report
