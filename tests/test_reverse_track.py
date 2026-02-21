from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

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
    def __init__(
        self,
        sections: list[SectionPreview],
        fsects: list[list[PreviewFSection]],
        *,
        replace_all_fsects_result: bool = True,
        xsect_metadata: list[tuple[int, float]] | None = None,
        set_xsect_definitions_result: bool = True,
    ) -> None:
        self.sections = sections
        self.fsects = fsects
        self.received_sections: list[SectionPreview] | None = None
        self.received_fsects: list[list[PreviewFSection]] | None = None
        self._replace_all_fsects_result = replace_all_fsects_result
        self._xsect_metadata = (
            list(xsect_metadata)
            if xsect_metadata is not None
            else [(0, -5.0), (1, 0.0), (2, 5.0)]
        )
        self._set_xsect_definitions_result = set_xsect_definitions_result
        self.received_xsect_entries: list[tuple[int | None, float]] | None = None
        self.transform_state = object()
        self.controller = SimpleNamespace(transform_state=None)
        self.repaint_requested = False

    def get_section_set(self):
        return self.sections, None

    def get_section_fsects(self, section_index: int):
        return list(self.fsects[section_index])

    def set_sections(self, sections: list[SectionPreview]):
        self.received_sections = sections

    def replace_all_fsects(self, fsects_by_section: list[list[PreviewFSection]]):
        self.received_fsects = fsects_by_section
        return self._replace_all_fsects_result

    def get_xsect_metadata(self):
        return list(self._xsect_metadata)

    def set_xsect_definitions(self, entries: list[tuple[int | None, float]]):
        self.received_xsect_entries = list(entries)
        if self._set_xsect_definitions_result:
            self._xsect_metadata = [(idx, float(dlat)) for idx, (_, dlat) in enumerate(entries)]
        return self._set_xsect_definitions_result

    def apply_preview_to_sgfile(self):
        return None

    def request_repaint(self):
        self.repaint_requested = True


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
    assert preview.received_xsect_entries == [(2, 5.0), (1, 0.0), (0, -5.0)]
    assert "Reversed section order" in (controller._host._window.status or "")
    assert preview.controller.transform_state is preview.transform_state
    assert preview.repaint_requested


def test_reverse_track_restores_zoom_even_when_fsect_replace_fails() -> None:
    preview = _FakePreview(
        [_section(0, 0, 0, (0.0, 0.0), (10.0, 0.0))],
        [[PreviewFSection(start_dlat=-3.0, end_dlat=3.0, surface_type=5, type2=0)]],
        replace_all_fsects_result=False,
    )
    original_transform_state = preview.transform_state
    controller = SectionsController(_Host(preview))

    controller.reverse_track()

    assert preview.controller.transform_state is original_transform_state
    assert preview.repaint_requested


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


def test_reverse_track_recomputes_ground_fsects_from_new_right_side() -> None:
    sections = [_section(0, 0, 0, (0.0, 0.0), (10.0, 0.0))]
    # Ground strips are encoded by their right-side DLAT. In reverse mode we
    # rebuild right edges from the new right wall and preserve strip widths.
    fsects = [
        [
            PreviewFSection(start_dlat=-20.0, end_dlat=-18.0, surface_type=0, type2=0),
            PreviewFSection(start_dlat=-12.0, end_dlat=-10.0, surface_type=1, type2=0),
            PreviewFSection(start_dlat=-4.0, end_dlat=-2.0, surface_type=2, type2=0),
            PreviewFSection(start_dlat=0.0, end_dlat=0.0, surface_type=7, type2=0),
            PreviewFSection(start_dlat=6.0, end_dlat=8.0, surface_type=9, type2=1),
        ]
    ]

    preview = _FakePreview(sections, fsects)
    controller = SectionsController(_Host(preview))

    controller.reverse_track()

    assert preview.received_fsects is not None
    ground = [f for f in preview.received_fsects[0] if f.surface_type in {0, 1, 2, 3, 4, 5, 6}]
    assert ground == [
        PreviewFSection(start_dlat=-8.0, end_dlat=-6.0, surface_type=2, type2=0),
        PreviewFSection(start_dlat=0.0, end_dlat=2.0, surface_type=1, type2=0),
        PreviewFSection(start_dlat=8.0, end_dlat=10.0, surface_type=0, type2=0),
    ]
