from sg_viewer.model.preview_fsection import PreviewFSection
from types import SimpleNamespace
from sg_viewer.services.sg_integrity_checks import FT_TO_WORLD, IntegrityProgress, build_integrity_report


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


def test_integrity_report_flags_perpendicular_centerline_spacing_violation() -> None:
    section_a = _section(section_id=0, start=(0.0, 0.0), end=(200.0 * FT_TO_WORLD, 0.0))
    section_b = _section(
        section_id=1,
        start=(100.0 * FT_TO_WORLD, -40.0 * FT_TO_WORLD),
        end=(100.0 * FT_TO_WORLD, 40.0 * FT_TO_WORLD),
    )

    report = build_integrity_report(
        [section_a, section_b],
        [[], []],
    ).text

    assert "Sections with < 80 ft perpendicular spacing: 1" in report
    assert "Sampling step: 10 ft" in report



def test_integrity_report_flags_parallel_close_centerline_spacing_violation() -> None:
    section_a = _section(section_id=0, start=(0.0, 0.0), end=(200.0 * FT_TO_WORLD, 0.0))
    section_b = _section(
        section_id=1,
        start=(0.0, 60.0 * FT_TO_WORLD),
        end=(200.0 * FT_TO_WORLD, 60.0 * FT_TO_WORLD),
    )

    report = build_integrity_report(
        [section_a, section_b],
        [[], []],
    ).text

    assert "Sections with < 80 ft perpendicular spacing: 2" in report

def test_integrity_report_ignores_adjacent_perpendicular_centerline_spacing_violation() -> None:
    section_a = _section(
        section_id=0,
        start=(0.0, 0.0),
        end=(200.0 * FT_TO_WORLD, 0.0),
        previous_id=1,
        next_id=1,
    )
    section_b = _section(
        section_id=1,
        start=(100.0 * FT_TO_WORLD, -40.0 * FT_TO_WORLD),
        end=(100.0 * FT_TO_WORLD, 40.0 * FT_TO_WORLD),
        previous_id=0,
        next_id=0,
    )

    report = build_integrity_report(
        [section_a, section_b],
        [[], []],
    ).text

    assert "Sections with < 80 ft perpendicular spacing: 1" not in report


def test_integrity_report_flags_boundary_closer_to_other_centerline() -> None:
    section_a = _section(section_id=0, start=(0.0, 0.0), end=(100.0 * FT_TO_WORLD, 0.0))
    section_b = _section(section_id=1, start=(0.0, 10.0 * FT_TO_WORLD), end=(100.0 * FT_TO_WORLD, 10.0 * FT_TO_WORLD))
    wide_left_boundary = PreviewFSection(
        start_dlat=20.0 * FT_TO_WORLD,
        end_dlat=20.0 * FT_TO_WORLD,
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
        end=(100.0 * FT_TO_WORLD, 0.0),
        previous_id=1,
        next_id=1,
    )
    section_b = _section(
        section_id=1,
        start=(0.0, 10.0 * FT_TO_WORLD),
        end=(100.0 * FT_TO_WORLD, 10.0 * FT_TO_WORLD),
        previous_id=0,
        next_id=0,
    )
    wide_left_boundary = PreviewFSection(
        start_dlat=20.0 * FT_TO_WORLD,
        end_dlat=20.0 * FT_TO_WORLD,
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

    section_a = _section(section_id=0, start=(0.0, 0.0), end=(200.0 * FT_TO_WORLD, 0.0))
    section_b = _section(
        section_id=1,
        start=(100.0 * FT_TO_WORLD, -40.0 * FT_TO_WORLD),
        end=(100.0 * FT_TO_WORLD, 40.0 * FT_TO_WORLD),
    )
    section_far = _section(
        section_id=2,
        start=(2000.0 * FT_TO_WORLD, 2000.0 * FT_TO_WORLD),
        end=(2100.0 * FT_TO_WORLD, 2000.0 * FT_TO_WORLD),
    )

    sections = [section_a, section_b, section_far]
    all_segments: list[tuple[int, tuple[float, float], tuple[float, float]]] = []
    for idx, section in enumerate(sections):
        all_segments.append((idx, section.polyline[0], section.polyline[1]))

    sample_point = (100.0 * FT_TO_WORLD, 0.0)
    sample_normal = (0.0, 1.0)
    probe_half_len_world = 80.0 * FT_TO_WORLD

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
    section_a = _section(section_id=0, start=(0.0, 0.0), end=(200.0 * FT_TO_WORLD, 0.0))
    section_b = _section(
        section_id=1,
        start=(100.0 * FT_TO_WORLD, -40.0 * FT_TO_WORLD),
        end=(100.0 * FT_TO_WORLD, 40.0 * FT_TO_WORLD),
    )

    updates: list[IntegrityProgress] = []

    build_integrity_report([section_a, section_b], [[], []], on_progress=updates.append)

    assert updates
    assert updates[0].message == "Preparing integrity checks"
    assert updates[-1].message == "Integrity checks complete"
    assert updates[-1].current == updates[-1].total
