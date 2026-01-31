import sys
import types
from dataclasses import replace

if "PyQt5" not in sys.modules:
    qtcore = types.ModuleType("PyQt5.QtCore")
    qtgui = types.ModuleType("PyQt5.QtGui")

    class _Qt:
        LeftButton = 1
        RightButton = 2

    class _QPoint:
        def __init__(self, x: int = 0, y: int = 0) -> None:
            self._x = x
            self._y = y

        def x(self) -> int:
            return self._x

        def y(self) -> int:
            return self._y

    qtcore.Qt = _Qt
    qtcore.QPoint = _QPoint
    qtgui.QMouseEvent = object

    pyqt5 = types.ModuleType("PyQt5")
    pyqt5.QtCore = qtcore
    pyqt5.QtGui = qtgui

    sys.modules["PyQt5"] = pyqt5
    sys.modules["PyQt5.QtCore"] = qtcore
    sys.modules["PyQt5.QtGui"] = qtgui

if "numpy" not in sys.modules:
    numpy = types.ModuleType("numpy")
    numpy.int32 = int

    def _array(data, dtype=None):
        _ = dtype
        return list(data)

    def _fromfile(*_args, **_kwargs):
        raise ImportError("numpy is required to load SG files")

    numpy.array = _array
    numpy.fromfile = _fromfile
    sys.modules["numpy"] = numpy

from sg_viewer.models.sg_model import SectionPreview
from sg_viewer.models.preview_fsection import PreviewFSection
from sg_viewer.ui.preview_interaction import PreviewInteraction


class _FakeContext:
    def widget_size(self) -> tuple[int, int]:
        return (0, 0)

    def current_transform(self, _size: tuple[int, int]) -> tuple[float, tuple[float, float]]:
        return (1.0, (0.0, 0.0))

    def widget_height(self) -> int:
        return 0

    def map_to_track(
        self,
        _pos: tuple[float, float],
        _size: tuple[int, int],
        _height: int,
        _transform: tuple[float, tuple[float, float]],
    ) -> tuple[float, float] | None:
        return (0.0, 0.0)

    def request_repaint(self) -> None:
        pass


class _FakeSelection:
    selected_section_index: int | None = None


class _FakeSectionManager:
    def __init__(self, sections: list[SectionPreview]) -> None:
        self.sections = sections

    def set_sections(
        self,
        sections: list[SectionPreview],
        _focus: float | None = None,
        **_kwargs: object,
    ) -> None:
        self.sections = sections


class _FakeEditor:
    def can_drag_node(
        self, _sections: list[SectionPreview], _sect: SectionPreview, _endtype: str
    ) -> bool:
        return True

    def can_drag_section_polyline(
        self, _sections: list[SectionPreview], _sect: SectionPreview, _index: int
    ) -> bool:
        return False

    def disconnect_neighboring_section(
        self, sections: list[SectionPreview], _sect_index: int, _endtype: str
    ) -> list[SectionPreview]:
        return sections

    def get_drag_chain(self, _sections: list[SectionPreview], _index: int) -> list[int] | None:
        return None


def _make_section(
    section_id: int,
    *,
    start: tuple[float, float],
    end: tuple[float, float],
    previous_id: int,
    next_id: int,
) -> SectionPreview:
    return SectionPreview(
        section_id=section_id,
        source_section_id=section_id,
        type_name="straight",
        previous_id=previous_id,
        next_id=next_id,
        start=start,
        end=end,
        start_dlong=0.0,
        length=1.0,
        center=None,
        sang1=None,
        sang2=None,
        eang1=None,
        eang2=None,
        radius=None,
        start_heading=None,
        end_heading=None,
        polyline=[start, end],
    )


def test_loop_closure_locks_section_order_when_fsections_exist() -> None:
    sections = [
        _make_section(0, start=(0.0, 0.0), end=(1.0, 0.0), previous_id=-1, next_id=1),
        _make_section(1, start=(2.0, 0.0), end=(0.0, 0.0), previous_id=0, next_id=2),
        _make_section(2, start=(1.0, 0.0), end=(2.0, 0.0), previous_id=1, next_id=-1),
    ]
    fsects_by_section = [
        [PreviewFSection(start_dlat=0.0, end_dlat=5.0, surface_type=1, type2=0)],
        [PreviewFSection(start_dlat=5.0, end_dlat=10.0, surface_type=2, type2=0)],
        [],
    ]
    fsects_snapshot = list(fsects_by_section)
    old_sections = list(sections)
    updated_sections = list(old_sections)
    updated_sections[0] = replace(updated_sections[0], previous_id=2)
    updated_sections[2] = replace(updated_sections[2], next_id=0)

    before_section_ids = [sect.section_id for sect in old_sections]
    before_source_ids = [sect.source_section_id for sect in old_sections]

    section_manager = _FakeSectionManager(old_sections)
    status: list[str] = []
    interaction = PreviewInteraction(
        context=_FakeContext(),
        selection=_FakeSelection(),
        section_manager=section_manager,
        editor=_FakeEditor(),
        set_sections=section_manager.set_sections,
        update_drag_preview=lambda _sections: None,
        rebuild_after_start_finish=lambda _sections: None,
        node_radius_px=4,
        stop_panning=lambda: None,
        show_status=status.append,
        lock_section_order=lambda: True,
        has_fsections=lambda: True,
    )

    interaction._finalize_connection_updates(
        old_sections,
        updated_sections,
        start_idx=0,
        changed_indices=[0, 2],
    )

    assert [sect.start for sect in section_manager.sections] == [
        sect.start for sect in updated_sections
    ]
    assert section_manager.sections[0].previous_id == 2
    assert section_manager.sections[2].next_id == 0
    assert [sect.section_id for sect in section_manager.sections] == before_section_ids
    assert [sect.source_section_id for sect in section_manager.sections] == before_source_ids
    assert fsects_by_section == fsects_snapshot


def test_loop_closure_canonicalization_guard_when_fsections_exist() -> None:
    sections = [
        _make_section(0, start=(0.0, 0.0), end=(1.0, 0.0), previous_id=-1, next_id=1),
        _make_section(1, start=(2.0, 0.0), end=(0.0, 0.0), previous_id=0, next_id=2),
        _make_section(2, start=(1.0, 0.0), end=(2.0, 0.0), previous_id=1, next_id=-1),
    ]
    old_sections = list(sections)
    updated_sections = list(old_sections)
    updated_sections[0] = replace(updated_sections[0], previous_id=2)
    updated_sections[2] = replace(updated_sections[2], next_id=0)

    section_manager = _FakeSectionManager(old_sections)
    interaction = PreviewInteraction(
        context=_FakeContext(),
        selection=_FakeSelection(),
        section_manager=section_manager,
        editor=_FakeEditor(),
        set_sections=section_manager.set_sections,
        update_drag_preview=lambda _sections: None,
        rebuild_after_start_finish=lambda _sections: None,
        node_radius_px=4,
        stop_panning=lambda: None,
        show_status=lambda _message: None,
        lock_section_order=lambda: False,
        has_fsections=lambda: True,
    )

    try:
        interaction._finalize_connection_updates(
            old_sections,
            updated_sections,
            start_idx=0,
            changed_indices=[0, 2],
        )
    except RuntimeError as exc:
        assert "Canonicalization forbidden when F-sections exist" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError when F-sections exist")
