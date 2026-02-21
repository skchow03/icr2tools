from __future__ import annotations

from sg_viewer.model.preview_fsection import PreviewFSection
from sg_viewer.model.sg_model import SectionPreview
from sg_viewer.services.mrk_io import MarkUvRect, generate_wall_mark_file


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
