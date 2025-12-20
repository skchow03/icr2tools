import math
import sys
import types
from typing import List, Sequence

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

from PyQt5 import QtCore

from sg_viewer.geometry.connect_curve_to_straight import (
    solve_straight_end_to_curve_endpoint,
)
from sg_viewer.geometry.sg_geometry import update_section_geometry
from sg_viewer.models.sg_model import SectionPreview
from sg_viewer.ui.preview_interaction import PreviewInteraction


def _make_curve_section(
    *,
    section_id: int,
    start: tuple[float, float],
    end: tuple[float, float],
    center: tuple[float, float],
    radius: float,
    start_heading: tuple[float, float] | None,
    end_heading: tuple[float, float] | None,
    length: float | None = None,
) -> SectionPreview:
    section = SectionPreview(
        section_id=section_id,
        type_name="curve",
        previous_id=None,
        next_id=None,
        start=start,
        end=end,
        start_dlong=0.0,
        length=length if length is not None else abs(radius) * math.pi / 2,
        center=center,
        sang1=start_heading[0] if start_heading else None,
        sang2=start_heading[1] if start_heading else None,
        eang1=end_heading[0] if end_heading else None,
        eang2=end_heading[1] if end_heading else None,
        radius=radius,
        start_heading=start_heading,
        end_heading=end_heading,
        polyline=[start, end],
    )
    return update_section_geometry(section)


def _make_straight_section(
    *,
    section_id: int,
    start: tuple[float, float],
    end: tuple[float, float],
) -> SectionPreview:
    length = math.hypot(end[0] - start[0], end[1] - start[1])
    section = SectionPreview(
        section_id=section_id,
        type_name="straight",
        previous_id=None,
        next_id=None,
        start=start,
        end=end,
        start_dlong=0.0,
        length=length,
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
    return update_section_geometry(section)


def test_solve_straight_to_curve_endpoint_aligns_headings():
    curve = _make_curve_section(
        section_id=1,
        start=(0.0, 0.0),
        end=(50.0, 50.0),
        center=(0.0, 50.0),
        radius=50.0,
        start_heading=(1.0, 0.0),
        end_heading=(0.0, 1.0),
    )
    straight = _make_straight_section(
        section_id=0,
        start=(50.0, 30.0),
        end=(50.0, 130.0),
    )

    solved = solve_straight_end_to_curve_endpoint(straight, "start", curve, "end")

    assert solved is not None
    new_straight, new_curve = solved
    assert math.isclose(new_straight.start[0], new_curve.end[0], abs_tol=1e-6)
    assert math.isclose(new_straight.start[1], new_curve.end[1], abs_tol=1e-6)
    assert new_curve.start == curve.start

    assert new_curve.end_heading is not None
    assert new_straight.start_heading is not None
    dot = (
        new_curve.end_heading[0] * new_straight.start_heading[0]
        + new_curve.end_heading[1] * new_straight.start_heading[1]
    )
    assert math.isclose(dot, 1.0, rel_tol=1e-6)


def test_solve_straight_to_curve_endpoint_preserves_length_and_curve():
    curve = _make_curve_section(
        section_id=1,
        start=(0.0, 0.0),
        end=(100.0, 100.0),
        center=(0.0, 100.0),
        radius=100.0,
        start_heading=(1.0, 0.0),
        end_heading=(0.0, 1.0),
    )
    straight = _make_straight_section(
        section_id=0,
        start=(100.0, -50.0),
        end=(100.0, 50.0),
    )

    solved = solve_straight_end_to_curve_endpoint(
        straight,
        "start",
        curve,
        "end",
    )

    assert solved is not None
    new_straight, new_curve = solved

    assert math.isclose(new_straight.length, straight.length, rel_tol=1e-9)
    assert new_straight.start == curve.end

    assert new_curve.start == curve.start
    assert new_curve.end == curve.end
    assert math.isclose(new_curve.length, curve.length, rel_tol=1e-9)
    assert math.isclose(new_curve.radius, curve.radius, rel_tol=1e-9)


def test_solve_straight_to_curve_endpoint_rejects_short_solutions():
    curve = _make_curve_section(
        section_id=1,
        start=(0.0, 0.0),
        end=(10.0, 10.0),
        center=(0.0, 10.0),
        radius=10.0,
        start_heading=(1.0, 0.0),
        end_heading=(0.0, 1.0),
    )
    straight = _make_straight_section(
        section_id=0,
        start=(10.0, 5.0),
        end=(10.0, 15.0),
    )

    solved = solve_straight_end_to_curve_endpoint(
        straight,
        "start",
        curve,
        "end",
        min_straight_length=500.0,
    )

    assert solved is None


def test_solve_straight_to_curve_endpoint_requires_curve_heading():
    curve = SectionPreview(
        section_id=1,
        type_name="curve",
        previous_id=None,
        next_id=None,
        start=(0.0, 0.0),
        end=(50.0, 50.0),
        start_dlong=0.0,
        length=0.0,
        center=(0.0, 50.0),
        sang1=None,
        sang2=None,
        eang1=None,
        eang2=None,
        radius=50.0,
        start_heading=None,
        end_heading=None,
        polyline=[],
    )
    straight = _make_straight_section(
        section_id=0,
        start=(50.0, 30.0),
        end=(50.0, 130.0),
    )

    solved = solve_straight_end_to_curve_endpoint(straight, "start", curve, "end")

    assert solved is None


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
    def __init__(self, sections: List[SectionPreview]) -> None:
        self.sections = sections

    def set_sections(self, sections: List[SectionPreview]) -> None:
        self.sections = sections


class _FakeEditor:
    def can_drag_node(
        self, _sections: Sequence[SectionPreview], _sect: SectionPreview, _endtype: str
    ) -> bool:
        return True

    def can_drag_section_polyline(
        self, _sections: Sequence[SectionPreview], _sect: SectionPreview, _index: int
    ) -> bool:
        return False

    def disconnect_neighboring_section(
        self, sections: List[SectionPreview], _sect_index: int, _endtype: str
    ) -> List[SectionPreview]:
        return sections

    def get_drag_chain(self, _sections: Sequence[SectionPreview], _index: int) -> list[int] | None:
        return None


class _FakeEvent:
    def __init__(self) -> None:
        self.accepted = False

    def button(self) -> int:
        return QtCore.Qt.LeftButton

    def pos(self) -> QtCore.QPoint:
        return QtCore.QPoint(0, 0)

    def accept(self) -> None:
        self.accepted = True


def _make_interaction(
    sections: List[SectionPreview], status_sink: list[str]
) -> PreviewInteraction:
    section_manager = _FakeSectionManager(sections)

    def _set_sections(updated: List[SectionPreview], _focus: float | None = None) -> None:
        section_manager.set_sections(updated)

    return PreviewInteraction(
        context=_FakeContext(),
        selection=_FakeSelection(),
        section_manager=section_manager,
        editor=_FakeEditor(),
        set_sections=_set_sections,
        rebuild_after_start_finish=lambda _sections: None,
        node_radius_px=4,
        stop_panning=lambda: None,
        show_status=status_sink.append,
    )


def test_handle_mouse_release_reports_successful_straight_to_curve_connection():
    status: list[str] = []
    straight = _make_straight_section(
        section_id=0,
        start=(50.0, 30.0),
        end=(50.0, 130.0),
    )
    curve = _make_curve_section(
        section_id=1,
        start=(0.0, 0.0),
        end=(50.0, 50.0),
        center=(0.0, 50.0),
        radius=50.0,
        start_heading=(1.0, 0.0),
        end_heading=(0.0, 1.0),
    )
    interaction = _make_interaction([straight, curve], status)
    interaction._is_dragging_node = True
    interaction._active_node = (0, "start")
    interaction._connection_target = (1, "end")

    handled = interaction.handle_mouse_release(_FakeEvent())

    assert handled is True
    assert status[-1] == "Straight → curve connected"
    assert interaction._section_manager.sections[1].next_id == 0
    assert interaction._section_manager.sections[0].previous_id == 1


def test_handle_mouse_release_reports_failed_straight_to_curve_connection():
    status: list[str] = []
    straight = _make_straight_section(
        section_id=0,
        start=(50.0, 30.0),
        end=(50.0, 130.0),
    )
    curve = SectionPreview(
        section_id=1,
        type_name="curve",
        previous_id=None,
        next_id=None,
        start=(0.0, 0.0),
        end=(50.0, 50.0),
        start_dlong=0.0,
        length=0.0,
        center=(0.0, 50.0),
        sang1=None,
        sang2=None,
        eang1=None,
        eang2=None,
        radius=50.0,
        start_heading=None,
        end_heading=None,
        polyline=[],
    )
    interaction = _make_interaction([straight, curve], status)
    interaction._is_dragging_node = True
    interaction._active_node = (0, "start")
    interaction._connection_target = (1, "end")

    handled = interaction.handle_mouse_release(_FakeEvent())

    assert handled is True
    assert status[-1] == "Straight → curve connection failed"
    assert interaction._section_manager.sections[1].previous_id is None
    assert interaction._section_manager.sections[0].previous_id is None
