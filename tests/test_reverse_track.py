from __future__ import annotations

from dataclasses import replace

from sg_viewer.model.preview_fsection import PreviewFSection
from sg_viewer.model.sg_model import SectionPreview
from sg_viewer.ui.controllers.features.sections_controller import SectionsController


def _section(
    idx: int,
    prev_idx: int,
    next_idx: int,
    start: tuple[float, float],
    end: tuple[float, float],
) -> SectionPreview:
    return SectionPreview(
        section_id=idx,
        source_section_id=idx,
        type_name="straight",
        previous_id=prev_idx,
        next_id=next_idx,
        start=start,
        end=end,
        start_dlong=float(idx * 100),
        length=100.0,
        center=None,
        sang1=1.0,
        sang2=2.0,
        eang1=3.0,
        eang2=4.0,
        radius=None,
        start_heading=(11.0, 12.0),
        end_heading=(13.0, 14.0),
        polyline=[start, end],
    )


class _FakePreview:
    def __init__(self, sections: list[SectionPreview], fsects: list[list[PreviewFSection]]) -> None:
        self.sections = sections
        self.fsects = fsects
        self.received_sections: list[SectionPreview] | None = None
        self.received_fsects: list[list[PreviewFSection]] | None = None

    def get_section_set(self):
        return self.sections, None

    def get_section_fsects(self, section_index: int):
        return list(self.fsects[section_index])

    def set_sections(self, sections: list[SectionPreview]):
        self.received_sections = sections

    def replace_all_fsects(self, fsects_by_section: list[list[PreviewFSection]]):
        self.received_fsects = fsects_by_section
        return True

    def apply_preview_to_sgfile(self):
        return None


class _FakeWindow:
    def __init__(self, preview: _FakePreview) -> None:
        self.preview = preview
        self.status: str | None = None

    def show_status_message(self, message: str) -> None:
        self.status = message


class _Host:
    def __init__(self, preview: _FakePreview) -> None:
        self._window = _FakeWindow(preview)


def test_reverse_track_reverses_sections_fsects_and_orientation() -> None:
    sections = [
        _section(0, 1, 1, (0.0, 0.0), (10.0, 0.0)),
        _section(1, 0, 0, (10.0, 0.0), (0.0, 0.0)),
    ]
    # Make section 1 headings distinguishable
    sections[1] = replace(
        sections[1],
        sang1=21.0,
        sang2=22.0,
        eang1=23.0,
        eang2=24.0,
        start_heading=(31.0, 32.0),
        end_heading=(33.0, 34.0),
    )
    fsects = [
        [PreviewFSection(start_dlat=-5.0, end_dlat=5.0, surface_type=5, type2=0)],
        [PreviewFSection(start_dlat=-20.0, end_dlat=-10.0, surface_type=7, type2=1)],
    ]

    preview = _FakePreview(sections, fsects)
    controller = SectionsController(_Host(preview))

    controller.reverse_track()

    assert preview.received_sections is not None
    assert preview.received_fsects is not None

    reversed_sections = preview.received_sections
    assert [s.section_id for s in reversed_sections] == [0, 1]
    assert [s.source_section_id for s in reversed_sections] == [1, 0]

    first = reversed_sections[0]
    assert first.start == sections[1].end
    assert first.end == sections[1].start
    assert first.previous_id == 1
    assert first.next_id == 1
    assert first.sang1 == sections[1].eang1
    assert first.sang2 == sections[1].eang2
    assert first.eang1 == sections[1].sang1
    assert first.eang2 == sections[1].sang2

    assert preview.received_fsects[0][0] == PreviewFSection(
        start_dlat=10.0,
        end_dlat=20.0,
        surface_type=7,
        type2=1,
    )
    assert preview.received_fsects[1][0] == PreviewFSection(
        start_dlat=-5.0,
        end_dlat=5.0,
        surface_type=5,
        type2=0,
    )
    assert "Reversed section order" in (controller._host._window.status or "")


def test_reverse_track_flips_curve_turn_direction_via_radius_sign() -> None:
    sections = [
        replace(
            _section(0, 0, 0, (0.0, 0.0), (10.0, 10.0)),
            type_name="curve",
            center=(5.0, 5.0),
            radius=250.0,
        )
    ]
    fsects = [[PreviewFSection(start_dlat=-3.0, end_dlat=3.0, surface_type=5, type2=0)]]

    preview = _FakePreview(sections, fsects)
    controller = SectionsController(_Host(preview))

    controller.reverse_track()

    assert preview.received_sections is not None
    assert preview.received_sections[0].type_name == "curve"
    assert preview.received_sections[0].radius == -250.0


def test_reverse_track_reanchors_ground_fsects_to_new_rightmost_boundary() -> None:
    sections = [_section(0, 0, 0, (0.0, 0.0), (10.0, 0.0))]
    # Boundary/right-wall only at +30 before reverse. After mirroring it becomes -30,
    # and we should create a ground segment starting at that new rightmost wall.
    fsects = [
        [
            PreviewFSection(start_dlat=-30.0, end_dlat=-30.0, surface_type=8, type2=0),
            PreviewFSection(start_dlat=-20.0, end_dlat=0.0, surface_type=5, type2=0),
            PreviewFSection(start_dlat=0.0, end_dlat=20.0, surface_type=2, type2=0),
            PreviewFSection(start_dlat=30.0, end_dlat=30.0, surface_type=7, type2=0),
        ]
    ]

    preview = _FakePreview(sections, fsects)
    controller = SectionsController(_Host(preview))

    controller.reverse_track()

    assert preview.received_fsects is not None
    reversed_fsects = preview.received_fsects[0]

    # Rightmost boundary after reverse should be -30 and ground must start there.
    assert reversed_fsects[0] == PreviewFSection(
        start_dlat=-30.0, end_dlat=-30.0, surface_type=7, type2=0
    )
    assert reversed_fsects[1] == PreviewFSection(
        start_dlat=-30.0, end_dlat=-20.0, surface_type=2, type2=0
    )
