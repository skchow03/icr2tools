from __future__ import annotations

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
    sections = [
        SectionPreview(
            section_id=0,
            source_section_id=0,
            type_name="curve",
            previous_id=-1,
            next_id=-1,
            start=(100.0, 0.0),
            end=(0.0, 100.0),
            start_dlong=0.0,
            length=157.079632679,
            center=(0.0, 0.0),
            sang1=None,
            sang2=None,
            eang1=None,
            eang2=None,
            radius=100.0,
            start_heading=None,
            end_heading=None,
            polyline=[(100.0, 0.0), (0.0, 100.0)],
        )
    ]
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
    assert boundary_counts == {0: 6, 1: 8}
