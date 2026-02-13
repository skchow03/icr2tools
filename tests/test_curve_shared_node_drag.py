import math
import sys
import types
from typing import List

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

from sg_viewer.model.sg_model import SectionPreview
from sg_viewer.geometry.sg_geometry import update_section_geometry
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
    def __init__(self, sections: List[SectionPreview]) -> None:
        self.sections = sections

    def set_sections(self, sections: List[SectionPreview], _focus: float | None = None) -> None:
        self.sections = sections


class _FakeEditor:
    def can_drag_node(
        self, _sections: List[SectionPreview], _sect: SectionPreview, _endtype: str
    ) -> bool:
        return True

    def can_drag_section_polyline(
        self, _sections: List[SectionPreview], _sect: SectionPreview, _index: int
    ) -> bool:
        return False

    def disconnect_neighboring_section(
        self, sections: List[SectionPreview], _sect_index: int, _endtype: str
    ) -> List[SectionPreview]:
        return sections

    def get_drag_chain(self, _sections: List[SectionPreview], _index: int) -> list[int] | None:
        return None


def _make_curve_section(
    *,
    section_id: int,
    start_angle: float,
    end_angle: float,
    center: tuple[float, float],
    radius: float,
    previous_id: int,
    next_id: int,
) -> SectionPreview:
    cx, cy = center
    start = (cx + math.cos(start_angle) * radius, cy + math.sin(start_angle) * radius)
    end = (cx + math.cos(end_angle) * radius, cy + math.sin(end_angle) * radius)

    def _tangent(angle: float) -> tuple[float, float]:
        return (-math.sin(angle), math.cos(angle))

    start_heading = _tangent(start_angle)
    end_heading = _tangent(end_angle)
    length = abs(end_angle - start_angle) * abs(radius)

    section = SectionPreview(
        section_id=section_id,
        type_name="curve",
        previous_id=previous_id,
        next_id=next_id,
        start=start,
        end=end,
        start_dlong=0.0,
        length=length,
        center=center,
        sang1=start_heading[0],
        sang2=start_heading[1],
        eang1=end_heading[0],
        eang2=end_heading[1],
        radius=radius,
        start_heading=start_heading,
        end_heading=end_heading,
        polyline=[start, end],
    )
    return update_section_geometry(section)


def test_shared_curve_node_drag_constrains_to_arc():
    center = (0.0, 0.0)
    radius = 100.0
    s1 = _make_curve_section(
        section_id=0,
        start_angle=0.0,
        end_angle=math.pi / 2,
        center=center,
        radius=radius,
        previous_id=-1,
        next_id=1,
    )
    s2 = _make_curve_section(
        section_id=1,
        start_angle=math.pi / 2,
        end_angle=math.pi,
        center=center,
        radius=radius,
        previous_id=0,
        next_id=-1,
    )

    sections = [s1, s2]
    section_manager = _FakeSectionManager(sections)

    status: list[str] = []
    interaction = PreviewInteraction(
        context=_FakeContext(),
        selection=_FakeSelection(),
        section_manager=section_manager,
        editor=_FakeEditor(),
        set_sections=section_manager.set_sections,
        rebuild_after_start_finish=lambda _sections: None,
        node_radius_px=4,
        stop_panning=lambda: None,
        show_status=status.append,
    )

    dragged_key = (0, "end")
    target_angle = math.radians(135.0)
    track_point = (
        center[0] + math.cos(target_angle) * radius,
        center[1] + math.sin(target_angle) * radius,
    )

    applied = interaction._apply_constrained_shared_curve_drag(dragged_key, track_point)
    assert applied is True

    updated = section_manager.sections
    shared_point = updated[0].end

    expected_shared = (
        center[0] + math.cos(target_angle) * radius,
        center[1] + math.sin(target_angle) * radius,
    )

    assert math.isclose(shared_point[0], expected_shared[0], abs_tol=1e-6)
    assert math.isclose(shared_point[1], expected_shared[1], abs_tol=1e-6)
    assert shared_point == updated[1].start

    assert math.isclose(updated[0].length, radius * target_angle, rel_tol=1e-6)
    assert math.isclose(updated[1].length, radius * (math.pi - target_angle), rel_tol=1e-6)
