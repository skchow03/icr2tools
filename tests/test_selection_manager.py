from __future__ import annotations

import sys
import types

if "PyQt5" not in sys.modules:
    qtcore = types.ModuleType("PyQt5.QtCore")

    class _Signal:
        def __init__(self, *_, **__):
            self._subscribers: list = []

        def connect(self, func):  # pragma: no cover - helper for completeness
            self._subscribers.append(func)

        def emit(self, *args, **kwargs):
            for func in list(self._subscribers):
                func(*args, **kwargs)

    class QObject:
        def __init__(self, *_, **__):
            pass

    class QPoint:
        def __init__(self, x: float = 0.0, y: float = 0.0):
            self._x = int(x)
            self._y = int(y)

        def x(self) -> int:
            return self._x

        def y(self) -> int:
            return self._y

    class QPointF(QPoint):
        def __init__(self, point: QPoint):
            super().__init__(point.x(), point.y())

    qtcore.QPoint = QPoint
    qtcore.QPointF = QPointF
    qtcore.QObject = QObject
    qtcore.pyqtSignal = lambda *args, **kwargs: _Signal()

    qt_module = types.ModuleType("PyQt5")
    qt_module.QtCore = qtcore
    sys.modules["PyQt5"] = qt_module
    sys.modules["PyQt5.QtCore"] = qtcore

from PyQt5 import QtCore

from sg_viewer import preview_state
from sg_viewer.selection import SelectionManager
from sg_viewer.sg_model import SectionPreview


def _make_section(section_id: int, polyline: list[tuple[float, float]], start_dlong: float) -> SectionPreview:
    return SectionPreview(
        section_id=section_id,
        type_name="test",
        previous_id=section_id - 1,
        next_id=section_id + 1,
        start=polyline[0],
        end=polyline[-1],
        start_dlong=start_dlong,
        length=50.0,
        center=None,
        sang1=None,
        sang2=None,
        eang1=None,
        eang2=None,
        radius=None,
        start_heading=None,
        end_heading=None,
        polyline=list(polyline),
    )


def _map_to_track(transform, widget_height: int):
    return lambda point: preview_state.map_to_track(transform, (point.x(), point.y()), widget_height)


def _to_click_point(track_point: tuple[float, float], transform, widget_height: int) -> QtCore.QPoint:
    scale, offsets = transform
    x = offsets[0] + track_point[0] * scale
    y = widget_height - (offsets[1] + track_point[1] * scale)
    return QtCore.QPoint(int(round(x)), int(round(y)))


def test_selects_nearest_disconnected_polyline():
    transform = (1.0, (0.0, 0.0))
    widget_height = 300
    sections = [
        _make_section(0, [(0.0, 0.0), (10.0, 0.0)], 0.0),
        _make_section(1, [(100.0, 100.0), (110.0, 100.0)], 50.0),
    ]

    manager = SelectionManager()
    manager.update_context(sections, track_length=200.0, centerline_index=None, sampled_dlongs=[])

    click_point = _to_click_point((105.0, 100.0), transform, widget_height)
    manager.handle_click(click_point, _map_to_track(transform, widget_height), transform)

    assert manager.selected_section_index == 1


def test_prefers_moved_segment_over_dlong_order():
    transform = (2.0, (0.0, 0.0))
    widget_height = 400
    sections = [
        _make_section(0, [(0.0, 0.0), (50.0, 0.0)], 0.0),
        _make_section(1, [(0.0, 50.0), (50.0, 50.0)], 150.0),
    ]

    manager = SelectionManager()
    manager.update_context(sections, track_length=300.0, centerline_index=None, sampled_dlongs=[])

    click_point = _to_click_point((25.0, 50.0), transform, widget_height)
    manager.handle_click(click_point, _map_to_track(transform, widget_height), transform)

    assert manager.selected_section_index == 1
