from __future__ import annotations

import math

from sg_viewer.model.preview_fsection import PreviewFSection
from sg_viewer.model.sg_model import SectionPreview
from sg_viewer.services.mrk_io import MarkTextureSpec, MarkUvRect, generate_wall_mark_file


def _section(index: int, start_dlong: float, length: float) -> SectionPreview:
    return SectionPreview(
        section_id=index,
        source_section_id=index,
        type_name="straight",
        previous_id=index - 1,
        next_id=index + 1,
        start=(0.0, 0.0),
        end=(1.0, 0.0),
        start_dlong=start_dlong,
        length=length,
        center=None,
        sang1=None,
        sang2=None,
        eang1=None,
        eang2=None,
        radius=None,
        start_heading=None,
        end_heading=None,
        polyline=[(0.0, 0.0), (1.0, 0.0)],
    )


def _curve_section(
    index: int,
    *,
    start_dlong: float,
    radius: float,
    start_angle: float,
    end_angle: float,
    sample_count: int = 32,
) -> SectionPreview:
    points = [
        (
            radius * math.cos(start_angle + (end_angle - start_angle) * (step / sample_count)),
            radius * math.sin(start_angle + (end_angle - start_angle) * (step / sample_count)),
        )
        for step in range(sample_count + 1)
    ]
    return SectionPreview(
        section_id=index,
        source_section_id=index,
        type_name="curve",
        previous_id=index - 1,
        next_id=index + 1,
        start=points[0],
        end=points[-1],
        start_dlong=start_dlong,
        length=abs(end_angle - start_angle) * abs(radius),
        center=(0.0, 0.0),
        sang1=None,
        sang2=None,
        eang1=None,
        eang2=None,
        radius=radius,
        start_heading=None,
        end_heading=None,
        polyline=points,
    )


def test_generate_wall_mark_file_creates_entries_per_boundary() -> None:
    sections = [_section(0, 0.0, 1000.0), _section(1, 1000.0, 1000.0)]
    fsects_by_section = [
        [
            PreviewFSection(start_dlat=100.0, end_dlat=100.0, surface_type=7, type2=0),
            PreviewFSection(start_dlat=-100.0, end_dlat=-100.0, surface_type=8, type2=0),
        ],
        [
            PreviewFSection(start_dlat=100.0, end_dlat=100.0, surface_type=7, type2=0),
            PreviewFSection(start_dlat=-100.0, end_dlat=-100.0, surface_type=8, type2=0),
        ],
    ]

    mark_file = generate_wall_mark_file(
        sections=sections,
        fsects_by_section=fsects_by_section,
        mip_name="walldk",
        uv_rect=MarkUvRect(0, 0, 1023, 15),
        target_wall_length=500.0,
    )

    assert len(mark_file.entries) == 8
    assert {entry.boundary_id for entry in mark_file.entries} == {0, 1}
    assert all(entry.mip_name == "walldk" for entry in mark_file.entries)
    assert mark_file.entries[0].start.section == 0


def test_generate_wall_mark_file_validates_input_lengths() -> None:
    sections = [_section(0, 0.0, 1000.0)]

    try:
        generate_wall_mark_file(
            sections=sections,
            fsects_by_section=[],
            mip_name="walldk",
            uv_rect=MarkUvRect(0, 0, 1, 1),
        )
    except ValueError as exc:
        assert "Section count does not match" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_generate_wall_mark_file_applies_repeating_texture_pattern() -> None:
    sections = [_section(0, 0.0, 1000.0)]
    fsects_by_section = [
        [
            PreviewFSection(start_dlat=100.0, end_dlat=100.0, surface_type=7, type2=0),
        ],
    ]

    mark_file = generate_wall_mark_file(
        sections=sections,
        fsects_by_section=fsects_by_section,
        mip_name="fallback",
        uv_rect=MarkUvRect(0, 0, 1, 1),
        texture_pattern=(
            MarkTextureSpec("wall_a", MarkUvRect(0, 0, 10, 10)),
            MarkTextureSpec("wall_b", MarkUvRect(11, 0, 20, 10)),
        ),
        target_wall_length=250.0,
    )

    assert [entry.mip_name for entry in mark_file.entries] == ["wall_a", "wall_b", "wall_a", "wall_b"]
    assert [entry.uv_rect for entry in mark_file.entries] == [
        MarkUvRect(0, 0, 10, 10),
        MarkUvRect(11, 0, 20, 10),
        MarkUvRect(0, 0, 10, 10),
        MarkUvRect(11, 0, 20, 10),
    ]


def test_generate_wall_mark_file_flips_u_for_right_side_walls() -> None:
    sections = [_section(0, 0.0, 1000.0)]
    fsects_by_section = [
        [
            PreviewFSection(start_dlat=120.0, end_dlat=120.0, surface_type=7, type2=0),
            PreviewFSection(start_dlat=-120.0, end_dlat=-120.0, surface_type=7, type2=0),
        ],
    ]

    mark_file = generate_wall_mark_file(
        sections=sections,
        fsects_by_section=fsects_by_section,
        mip_name="wall",
        uv_rect=MarkUvRect(10, 2, 90, 14),
        target_wall_length=500.0,
    )

    left_entry = next(entry for entry in mark_file.entries if entry.boundary_id == 1)
    right_entry = next(entry for entry in mark_file.entries if entry.boundary_id == 0)
    assert left_entry.uv_rect == MarkUvRect(10, 2, 90, 14)
    assert right_entry.uv_rect == MarkUvRect(90, 2, 10, 14)


def test_generate_wall_mark_file_curve_uses_offset_length_for_divisions() -> None:
    sections = [_curve_section(0, start_dlong=0.0, radius=100.0, start_angle=0.0, end_angle=math.pi / 2.0)]
    fsects_by_section = [
        [
            PreviewFSection(start_dlat=14.0, end_dlat=14.0, surface_type=7, type2=0),
            PreviewFSection(start_dlat=-14.0, end_dlat=-14.0, surface_type=7, type2=0),
        ]
    ]

    mark_file = generate_wall_mark_file(
        sections=sections,
        fsects_by_section=fsects_by_section,
        mip_name="wall",
        uv_rect=MarkUvRect(0, 0, 1, 1),
        target_wall_length=14.0,
    )

    boundary_counts = {
        boundary_id: sum(1 for entry in mark_file.entries if entry.boundary_id == boundary_id)
        for boundary_id in {entry.boundary_id for entry in mark_file.entries}
    }
    assert sorted(boundary_counts.values()) == [10, 13]


def test_generate_wall_mark_file_curve_respects_turn_direction_for_inside_outside() -> None:
    sections = [_curve_section(0, start_dlong=0.0, radius=-100.0, start_angle=0.0, end_angle=-math.pi / 2.0)]
    fsects_by_section = [
        [
            PreviewFSection(start_dlat=14.0, end_dlat=14.0, surface_type=7, type2=0),
            PreviewFSection(start_dlat=-14.0, end_dlat=-14.0, surface_type=7, type2=0),
        ]
    ]

    mark_file = generate_wall_mark_file(
        sections=sections,
        fsects_by_section=fsects_by_section,
        mip_name="wall",
        uv_rect=MarkUvRect(0, 0, 1, 1),
        target_wall_length=14.0,
    )

    boundary_counts = {
        boundary_id: sum(1 for entry in mark_file.entries if entry.boundary_id == boundary_id)
        for boundary_id in {entry.boundary_id for entry in mark_file.entries}
    }
    assert sorted(boundary_counts.values()) == [10, 13]


def test_generate_wall_mark_file_two_texture_pattern_allows_single_wall_remainder() -> None:
    sections = [_section(0, 0.0, 20.0)]
    fsects_by_section = [
        [
            PreviewFSection(start_dlat=0.0, end_dlat=0.0, surface_type=7, type2=0),
        ]
    ]

    mark_file = generate_wall_mark_file(
        sections=sections,
        fsects_by_section=fsects_by_section,
        mip_name="fallback",
        uv_rect=MarkUvRect(0, 0, 1, 1),
        texture_pattern=(
            MarkTextureSpec("wall_a", MarkUvRect(0, 0, 10, 10)),
            MarkTextureSpec("wall_b", MarkUvRect(11, 0, 20, 10)),
        ),
        target_wall_length=14.0,
    )

    assert [entry.mip_name for entry in mark_file.entries] == ["wall_a"]


def test_generate_wall_mark_file_curve_inside_outside_segment_counts_follow_arc_length() -> None:
    target_wall_length = 14.0 * 6000.0
    radius = 50.0 * 6000.0
    wall_offset = 5.0 * 6000.0
    theta = 0.5 * 3.141592653589793
    section_length = radius * theta

    sections = [_curve_section(0, start_dlong=0.0, radius=radius, start_angle=0.0, end_angle=theta)]
    fsects_by_section = [
        [
            PreviewFSection(start_dlat=-wall_offset, end_dlat=-wall_offset, surface_type=7, type2=0),
            PreviewFSection(start_dlat=wall_offset, end_dlat=wall_offset, surface_type=7, type2=0),
        ]
    ]

    mark_file = generate_wall_mark_file(
        sections=sections,
        fsects_by_section=fsects_by_section,
        mip_name="wall",
        uv_rect=MarkUvRect(0, 0, 1, 1),
        target_wall_length=target_wall_length,
    )

    inside_length = theta * (radius - wall_offset)
    outside_length = theta * (radius + wall_offset)
    assert outside_length > inside_length

    boundary_counts = {
        boundary_id: sum(1 for entry in mark_file.entries if entry.boundary_id == boundary_id)
        for boundary_id in {entry.boundary_id for entry in mark_file.entries}
    }
    inside_count = min(boundary_counts.values())
    outside_count = max(boundary_counts.values())

    assert outside_count >= inside_count

    inside_spacing = inside_length / inside_count
    outside_spacing = outside_length / outside_count
    tolerance = target_wall_length * 0.06

    assert abs(inside_spacing - target_wall_length) <= tolerance
    assert abs(outside_spacing - target_wall_length) <= tolerance


def test_generate_wall_mark_file_keeps_boundary_ids_stable_when_boundary_sort_order_flips() -> None:
    radius = 1000.0
    angle = math.pi / 4.0
    sections = [
        _curve_section(0, start_dlong=0.0, radius=radius, start_angle=0.0, end_angle=angle),
        _curve_section(1, start_dlong=radius * angle, radius=radius, start_angle=angle, end_angle=2.0 * angle),
    ]
    fsects_by_section = [
        [
            PreviewFSection(start_dlat=3.0, end_dlat=5.0, surface_type=7, type2=0),
            PreviewFSection(start_dlat=4.0, end_dlat=30.0, surface_type=7, type2=0),
        ],
        [
            PreviewFSection(start_dlat=25.0, end_dlat=27.0, surface_type=7, type2=0),
            PreviewFSection(start_dlat=2.0, end_dlat=26.0, surface_type=7, type2=0),
        ],
    ]

    mark_file = generate_wall_mark_file(
        sections=sections,
        fsects_by_section=fsects_by_section,
        mip_name="wall",
        uv_rect=MarkUvRect(0, 0, 1, 1),
        target_wall_length=100.0,
        boundary_match_tolerance=50.0,
    )

    boundary_counts = {
        boundary_id: sum(1 for entry in mark_file.entries if entry.boundary_id == boundary_id)
        for boundary_id in {entry.boundary_id for entry in mark_file.entries}
    }
    assert set(boundary_counts) == {0, 1}
    sections_per_boundary = {
        boundary_id: {
            entry.start.section
            for entry in mark_file.entries
            if entry.boundary_id == boundary_id
        }
        for boundary_id in boundary_counts
    }
    assert sections_per_boundary[0] == {0, 1}
    assert sections_per_boundary[1] == {0, 1}


def test_generate_wall_mark_file_stable_ids_when_boundary_dlat_ranges_cross_sign() -> None:
    sections = [_section(0, 0.0, 1000.0), _section(1, 1000.0, 1000.0)]
    fsects_by_section = [
        [
            PreviewFSection(start_dlat=-100.0, end_dlat=20.0, surface_type=7, type2=0),
            PreviewFSection(start_dlat=-90.0, end_dlat=120.0, surface_type=7, type2=0),
        ],
        [
            PreviewFSection(start_dlat=20.0, end_dlat=100.0, surface_type=7, type2=0),
            PreviewFSection(start_dlat=-120.0, end_dlat=90.0, surface_type=7, type2=0),
        ],
    ]

    mark_file = generate_wall_mark_file(
        sections=sections,
        fsects_by_section=fsects_by_section,
        mip_name="wall",
        uv_rect=MarkUvRect(0, 0, 1, 1),
        target_wall_length=500.0,
        boundary_match_tolerance=100.0,
    )

    boundary_ids = {entry.boundary_id for entry in mark_file.entries}
    assert boundary_ids == {0, 1}
    sections_per_boundary = {
        boundary_id: {entry.start.section for entry in mark_file.entries if entry.boundary_id == boundary_id}
        for boundary_id in boundary_ids
    }
    assert sections_per_boundary[0] == {0, 1}
    assert sections_per_boundary[1] == {0, 1}
