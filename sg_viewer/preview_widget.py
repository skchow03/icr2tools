from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets

from icr2_core.trk.trk_classes import TRKFile
from icr2_core.trk.trk_utils import get_cline_pos, getxyz
from track_viewer import rendering
from track_viewer.geometry import (
    CenterlineIndex,
    build_centerline_index,
    project_point_to_centerline,
    sample_centerline,
)

Point = Tuple[float, float]
Transform = tuple[float, tuple[float, float]]


@dataclass
class SectionSelection:
    index: int
    type_name: str
    start_dlong: float
    end_dlong: float


class SGPreviewWidget(QtWidgets.QWidget):
    """Minimal preview widget that draws an SG file centreline."""

    selectedSectionChanged = QtCore.pyqtSignal(object)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(640, 480)
        self.setMouseTracking(True)

        palette = self.palette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor("black"))
        self.setPalette(palette)

        self._trk: TRKFile | None = None
        self._cline: List[Point] | None = None
        self._sampled_centerline: List[Point] = []
        self._sampled_dlongs: List[float] = []
        self._sampled_bounds: tuple[float, float, float, float] | None = None
        self._centerline_index: CenterlineIndex | None = None
        self._status_message = "Select an SG file to begin."

        self._curve_markers: list[tuple[Point, Point, Point]] = []

        self._track_length: float | None = None
        self._selected_section_index: int | None = None
        self._selected_section_points: List[Point] = []

        self._fit_scale: float | None = None
        self._current_scale: float | None = None
        self._view_center: Point | None = None
        self._user_transform_active = False
        self._is_panning = False
        self._last_mouse_pos: QtCore.QPoint | None = None
        self._press_pos: QtCore.QPoint | None = None

    def clear(self, message: str | None = None) -> None:
        self._trk = None
        self._cline = None
        self._sampled_centerline = []
        self._sampled_dlongs = []
        self._sampled_bounds = None
        self._centerline_index = None
        self._track_length = None
        self._selected_section_index = None
        self._selected_section_points = []
        self._curve_markers = []
        self._fit_scale = None
        self._current_scale = None
        self._view_center = None
        self._user_transform_active = False
        self._is_panning = False
        self._last_mouse_pos = None
        self._press_pos = None
        self._status_message = message or "Select an SG file to begin."
        self.selectedSectionChanged.emit(None)
        self.update()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def load_sg_file(self, path: Path) -> None:
        if not path:
            self.clear()
            return

        self._status_message = f"Loading {path.name}…"
        self.update()

        trk = TRKFile.from_sg(str(path))
        cline = get_cline_pos(trk)
        sampled, sampled_dlongs, bounds = sample_centerline(trk, cline)

        if not sampled or bounds is None:
            raise ValueError("Failed to build centreline from SG file")

        self._trk = trk
        self._cline = cline
        self._sampled_centerline = sampled
        self._sampled_dlongs = sampled_dlongs
        self._sampled_bounds = bounds
        self._centerline_index = build_centerline_index(sampled, bounds)
        self._track_length = float(trk.trklength)
        self._selected_section_index = None
        self._selected_section_points = []
        self._curve_markers = self._build_curve_markers(trk)
        self._fit_scale = None
        self._current_scale = None
        self._view_center = None
        self._user_transform_active = False
        self._status_message = f"Loaded {path.name}"
        self._update_fit_scale()
        self.selectedSectionChanged.emit(None)
        self.update()

    # ------------------------------------------------------------------
    # Transform helpers
    # ------------------------------------------------------------------
    def _default_center(self) -> Point | None:
        if not self._sampled_bounds:
            return None
        min_x, max_x, min_y, max_y = self._sampled_bounds
        return ( (min_x + max_x) / 2, (min_y + max_y) / 2 )

    def _calculate_fit_scale(self) -> float | None:
        if not self._sampled_bounds:
            return None
        min_x, max_x, min_y, max_y = self._sampled_bounds
        span_x = max_x - min_x
        span_y = max_y - min_y
        if span_x <= 0 or span_y <= 0:
            return None
        margin = 24
        w, h = self.width(), self.height()
        available_w = max(w - margin * 2, 1)
        available_h = max(h - margin * 2, 1)
        scale_x = available_w / span_x
        scale_y = available_h / span_y
        return min(scale_x, scale_y)

    def _update_fit_scale(self) -> None:
        fit = self._calculate_fit_scale()
        self._fit_scale = fit
        if fit is not None and not self._user_transform_active:
            self._current_scale = fit
            if self._view_center is None:
                self._view_center = self._default_center()

    def _current_transform(self) -> Transform | None:
        if not self._sampled_bounds:
            return None
        if self._current_scale is None:
            self._update_fit_scale()
        if self._current_scale is None:
            return None
        center = self._view_center or self._default_center()
        if center is None:
            return None
        w, h = self.width(), self.height()
        offsets = (w / 2 - center[0] * self._current_scale, h / 2 - center[1] * self._current_scale)
        return self._current_scale, offsets

    def _clamp_scale(self, scale: float) -> float:
        base = self._fit_scale or self._current_scale or 1.0
        min_scale = base * 0.1
        max_scale = base * 25.0
        return max(min_scale, min(max_scale, scale))

    def _map_to_track(self, point: QtCore.QPointF) -> Point | None:
        transform = self._current_transform()
        if not transform:
            return None
        scale, offsets = transform
        x = (point.x() - offsets[0]) / scale
        py = self.height() - point.y()
        y = (py - offsets[1]) / scale
        return x, y

    # ------------------------------------------------------------------
    # Qt events
    # ------------------------------------------------------------------
    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # noqa: D401
        super().resizeEvent(event)
        self._update_fit_scale()
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: D401
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), self.palette().color(QtGui.QPalette.Window))

        if not self._sampled_centerline:
            painter.setPen(QtGui.QPen(QtGui.QColor("lightgray")))
            painter.drawText(self.rect(), QtCore.Qt.AlignCenter, self._status_message)
            painter.end()
            return

        transform = self._current_transform()
        if not transform:
            painter.setPen(QtGui.QPen(QtGui.QColor("lightgray")))
            painter.drawText(self.rect(), QtCore.Qt.AlignCenter, "Unable to fit view")
            painter.end()
            return

        rendering.draw_centerline(
            painter,
            self._sampled_centerline,
            transform,
            self.height(),
            color="white",
            width=3,
        )

        if self._selected_section_points:
            rendering.draw_centerline(
                painter,
                self._selected_section_points,
                transform,
                self.height(),
                color="red",
                width=4,
            )

        self._draw_curve_markers(painter, transform)

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:  # noqa: D401
        if not self._sampled_centerline:
            return
        if self._view_center is None:
            self._view_center = self._default_center()
        if self._view_center is None or self._current_scale is None:
            return
        delta = event.angleDelta().y()
        factor = 1.15 if delta > 0 else 1 / 1.15
        new_scale = self._clamp_scale(self._current_scale * factor)
        cursor_track = self._map_to_track(event.pos())
        if cursor_track is None:
            cursor_track = self._view_center
        w, h = self.width(), self.height()
        px, py = event.pos().x(), event.pos().y()
        cx = cursor_track[0] - (px - w / 2) / new_scale
        cy = cursor_track[1] + (py - h / 2) / new_scale
        self._view_center = (cx, cy)
        self._current_scale = new_scale
        self._user_transform_active = True
        self.update()
        event.accept()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401
        if event.button() == QtCore.Qt.LeftButton and self._sampled_centerline:
            self._is_panning = True
            self._last_mouse_pos = event.pos()
            self._press_pos = event.pos()
            self._user_transform_active = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401
        if self._is_panning and self._last_mouse_pos is not None:
            transform = self._current_transform()
            if transform:
                if self._view_center is None:
                    self._view_center = self._default_center()
                if self._view_center is not None:
                    scale, _ = transform
                    delta = event.pos() - self._last_mouse_pos
                    self._last_mouse_pos = event.pos()
                    cx, cy = self._view_center
                    cx -= delta.x() / scale
                    cy += delta.y() / scale
                    self._view_center = (cx, cy)
                    self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401
        if event.button() == QtCore.Qt.LeftButton:
            self._is_panning = False
            self._last_mouse_pos = None
            if (
                self._press_pos is not None
                and (event.pos() - self._press_pos).manhattanLength() < 6
            ):
                self._handle_click(event.pos())
            self._press_pos = None
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------
    def _handle_click(self, pos: QtCore.QPoint) -> None:
        if not self._centerline_index or not self._sampled_dlongs or not self._trk:
            return

        track_point = self._map_to_track(QtCore.QPointF(pos))
        transform = self._current_transform()
        if track_point is None or transform is None or self._track_length is None:
            return

        _, nearest_dlong, distance_sq = project_point_to_centerline(
            track_point, self._centerline_index, self._sampled_dlongs, self._track_length
        )

        if nearest_dlong is None:
            return

        scale, _ = transform
        tolerance_units = 10 / max(scale, 1e-6)
        if distance_sq > tolerance_units * tolerance_units:
            self._set_selected_section(None)
            return

        selection = self._find_section_by_dlong(nearest_dlong)
        self._set_selected_section(selection)

    def _find_section_by_dlong(self, dlong: float) -> int | None:
        if self._trk is None or not self._trk.sects:
            return None

        track_length = self._track_length or 0
        for idx, sect in enumerate(self._trk.sects):
            start = float(sect.start_dlong)
            end = start + float(sect.length)
            if track_length > 0 and end > track_length:
                if dlong >= start or dlong <= end - track_length:
                    return idx
            elif start <= dlong <= end:
                return idx
        return None

    def _set_selected_section(self, index: int | None) -> None:
        if index is None:
            self._selected_section_index = None
            self._selected_section_points = []
            self.selectedSectionChanged.emit(None)
            self.update()
            return

        if self._trk is None or index < 0 or index >= len(self._trk.sects):
            return

        sect = self._trk.sects[index]
        self._selected_section_index = index
        self._selected_section_points = self._sample_section_polyline(sect)

        end_dlong = float(sect.start_dlong + sect.length)
        if self._track_length:
            end_dlong = end_dlong % self._track_length

        type_name = "Curve" if sect.type == 2 else "Straight"
        selection = SectionSelection(
            index=index,
            type_name=type_name,
            start_dlong=float(sect.start_dlong),
            end_dlong=end_dlong,
        )
        self.selectedSectionChanged.emit(selection)
        self.update()

    def _sample_section_polyline(self, sect) -> List[Point]:
        if self._trk is None or not self._cline or not self._track_length:
            return []

        step = 5000
        remaining = float(sect.length)
        current = float(sect.start_dlong)
        points: List[Point] = []

        while remaining > 0:
            x, y, _ = getxyz(self._trk, current % self._track_length, 0, self._cline)
            points.append((x, y))
            advance = min(step, remaining)
            current += advance
            remaining -= advance

        x, y, _ = getxyz(
            self._trk, (sect.start_dlong + sect.length) % self._track_length, 0, self._cline
        )
        points.append((x, y))
        return points

    def _build_curve_markers(self, trk: TRKFile) -> list[tuple[Point, Point, Point]]:
        markers: list[tuple[Point, Point, Point]] = []
        for sect in trk.sects:
            if getattr(sect, "type", None) != 2:
                continue
            center = (float(sect.center_x), float(sect.center_y))
            start = (float(sect.start_x), float(sect.start_y))
            end = (float(sect.end_x), float(sect.end_y))
            markers.append((center, start, end))
        return markers

    def _draw_curve_markers(self, painter: QtGui.QPainter, transform: Transform) -> None:
        if not self._curve_markers:
            return

        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        color = QtGui.QColor(140, 140, 140)
        pen = QtGui.QPen(color, 1)
        painter.setPen(pen)
        painter.setBrush(QtGui.QBrush(color))

        for center, start, end in self._curve_markers:
            center_point = rendering.map_point(center[0], center[1], transform, self.height())
            start_point = rendering.map_point(start[0], start[1], transform, self.height())
            end_point = rendering.map_point(end[0], end[1], transform, self.height())

            painter.drawLine(QtCore.QLineF(center_point, start_point))
            painter.drawLine(QtCore.QLineF(center_point, end_point))
            painter.drawEllipse(center_point, 4, 4)

        painter.restore()
