from __future__ import annotations

from dataclasses import dataclass, replace
import math
from pathlib import Path
from typing import List, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets

from icr2_core.trk.sg_classes import SGFile
from icr2_core.trk.trk_classes import TRKFile
from icr2_core.trk.trk_utils import get_alt, getxyz, get_cline_pos
from track_viewer import rendering
from track_viewer.geometry import (
    CenterlineIndex,
    build_centerline_index,
    project_point_to_centerline,
    sample_centerline,
)
from sg_viewer.elevation_profile import ElevationProfileData
from sg_viewer import preview_loader, preview_rendering

Point = Tuple[float, float]
Transform = tuple[float, tuple[float, float]]


@dataclass
class SectionSelection:
    index: int
    type_name: str
    start_dlong: float
    end_dlong: float
    start_heading: tuple[float, float] | None = None
    end_heading: tuple[float, float] | None = None
    center: Point | None = None
    radius: float | None = None


@dataclass
class SectionGeometry:
    index: int
    start_x: float
    start_y: float
    end_x: float
    end_y: float
    gap_to_next: float


@dataclass
class SectionHeadingData:
    index: int
    start_heading: tuple[float, float] | None
    end_heading: tuple[float, float] | None
    delta_to_next: float | None


@dataclass
class MoveCandidate:
    first_index: int
    second_index: int
    start_point: Point
    joint_point: Point
    end_point: Point
    first_length: float
    second_length: float


class SGPreviewWidget(QtWidgets.QWidget):
    """Minimal preview widget that draws an SG file centreline."""

    selectedSectionChanged = QtCore.pyqtSignal(object)
    pointMoveFinished = QtCore.pyqtSignal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(640, 480)
        self.setMouseTracking(True)

        palette = self.palette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor("black"))
        self.setPalette(palette)

        self._sgfile: SGFile | None = None
        self._trk: TRKFile | None = None
        self._cline: List[Point] | None = None
        self._sampled_centerline: List[Point] = []
        self._sampled_dlongs: List[float] = []
        self._sampled_bounds: tuple[float, float, float, float] | None = None
        self._centerline_index: CenterlineIndex | None = None
        self._status_message = "Select an SG file to begin."

        self._curve_markers: dict[int, preview_loader.CurveMarker] = {}
        self._selected_curve_index: int | None = None
        self._section_endpoints: list[tuple[Point, Point]] = []

        self._track_length: float | None = None
        self._selected_section_index: int | None = None
        self._selected_section_points: List[Point] = []

        self._transform_state = preview_loader.TransformState()
        self._is_panning = False
        self._last_mouse_pos: QtCore.QPoint | None = None
        self._press_pos: QtCore.QPoint | None = None

        self._show_curve_markers = True
        self._move_mode_enabled = False
        self._active_move: MoveCandidate | None = None
        self._move_dragging = False
        self._pending_move_length: float | None = None

    def clear(self, message: str | None = None) -> None:
        self._sgfile = None
        self._trk = None
        self._cline = None
        self._sampled_centerline = []
        self._sampled_dlongs = []
        self._sampled_bounds = None
        self._centerline_index = None
        self._track_length = None
        self._selected_section_index = None
        self._selected_section_points = []
        self._section_endpoints = []
        self._curve_markers = {}
        self._selected_curve_index = None
        self._transform_state = preview_loader.TransformState()
        self._is_panning = False
        self._last_mouse_pos = None
        self._press_pos = None
        self._status_message = message or "Select an SG file to begin."
        self._move_mode_enabled = False
        self._active_move = None
        self._move_dragging = False
        self._pending_move_length = None
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

        data = preview_loader.load_preview(path)

        self._sgfile = data.sgfile
        self._trk = data.trk
        self._cline = data.cline
        self._sampled_centerline = data.sampled_centerline
        self._sampled_dlongs = data.sampled_dlongs
        self._sampled_bounds = data.sampled_bounds
        self._centerline_index = data.centerline_index
        self._track_length = data.track_length
        self._selected_section_index = None
        self._selected_section_points = []
        self._curve_markers = data.curve_markers
        self._section_endpoints = data.section_endpoints
        self._selected_curve_index = None
        self._transform_state = preview_loader.TransformState()
        self._status_message = data.status_message
        self._move_mode_enabled = False
        self._active_move = None
        self._move_dragging = False
        self._pending_move_length = None
        self._update_fit_scale()
        self.selectedSectionChanged.emit(None)
        self.update()

    # ------------------------------------------------------------------
    # Transform helpers
    # ------------------------------------------------------------------
    def _default_center(self) -> Point | None:
        return preview_loader.default_center(self._sampled_bounds)

    def _update_fit_scale(self) -> None:
        self._transform_state = preview_loader.update_fit_scale(
            self._transform_state,
            self._sampled_bounds,
            (self.width(), self.height()),
            self._default_center(),
        )

    def _current_transform(self) -> Transform | None:
        transform, updated_state = preview_loader.current_transform(
            self._transform_state,
            self._sampled_bounds,
            (self.width(), self.height()),
            self._default_center(),
        )
        if updated_state is not self._transform_state:
            self._transform_state = updated_state
        return transform

    def _clamp_scale(self, scale: float) -> float:
        return preview_loader.clamp_scale(scale, self._transform_state)

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
    # Section endpoint helpers
    # ------------------------------------------------------------------
    def _section_heading_vector(self, index: int) -> tuple[float, float] | None:
        if index < 0 or index >= len(self._section_endpoints):
            return None
        start, end = self._section_endpoints[index]
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = (dx * dx + dy * dy) ** 0.5
        if length <= 0:
            return None
        return dx / length, dy / length

    def _refresh_section_endpoints(self) -> None:
        if self._trk is None or self._cline is None or self._track_length is None:
            self._section_endpoints = []
            return

        self._section_endpoints = preview_loader._build_section_endpoints(  # type: ignore[attr-defined]
            self._trk, self._cline, self._track_length
        )

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
            preview_rendering.draw_placeholder(painter, self.rect(), self._status_message)
            painter.end()
            return

        transform = self._current_transform()
        if not transform:
            preview_rendering.draw_placeholder(painter, self.rect(), "Unable to fit view")
            painter.end()
            return

        preview_rendering.draw_centerlines(
            painter,
            self._sampled_centerline,
            self._selected_section_points,
            transform,
            self.height(),
        )

        preview_rendering.draw_section_endpoints(
            painter,
            self._section_endpoints,
            self._selected_section_index,
            transform,
            self.height(),
        )

        if self._show_curve_markers:
            preview_rendering.draw_curve_markers(
                painter,
                self._curve_markers,
                self._selected_curve_index,
                transform,
                self.height(),
            )

        preview_rendering.draw_start_finish_line(
            painter,
            self._centerline_point_normal_and_tangent(0.0),
            transform,
            self.height(),
        )

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:  # noqa: D401
        if not self._sampled_centerline:
            return
        transform = self._current_transform()
        if transform is None:
            return
        state = self._transform_state
        if state.view_center is None:
            center = self._default_center()
            if center is None:
                return
            state = replace(state, view_center=center)
            self._transform_state = state
        if state.current_scale is None or state.view_center is None:
            return

        delta = event.angleDelta().y()
        factor = 1.15 if delta > 0 else 1 / 1.15
        new_scale = self._clamp_scale(state.current_scale * factor)
        cursor_track = self._map_to_track(event.pos())
        if cursor_track is None:
            cursor_track = state.view_center
        w, h = self.width(), self.height()
        px, py = event.pos().x(), event.pos().y()
        cx = cursor_track[0] - (px - w / 2) / new_scale
        cy = cursor_track[1] + (py - h / 2) / new_scale
        self._transform_state = replace(
            state,
            current_scale=new_scale,
            view_center=(cx, cy),
            user_transform_active=True,
        )
        self.update()
        event.accept()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401
        if event.button() == QtCore.Qt.LeftButton:
            if self._move_mode_enabled:
                self._press_pos = event.pos()
                if self._attempt_begin_move(event.pos()):
                    event.accept()
                    return
            elif self._sampled_centerline:
                self._is_panning = True
                self._last_mouse_pos = event.pos()
                self._press_pos = event.pos()
                self._transform_state = replace(
                    self._transform_state, user_transform_active=True
                )
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401
        if self._move_dragging and self._active_move is not None:
            self._update_move_during_drag(event.pos())
            event.accept()
            return
        if self._is_panning and self._last_mouse_pos is not None:
            transform = self._current_transform()
            if transform:
                state = self._transform_state
                center = state.view_center or self._default_center()
                if center is not None:
                    scale, _ = transform
                    delta = event.pos() - self._last_mouse_pos
                    self._last_mouse_pos = event.pos()
                    cx, cy = center
                    cx -= delta.x() / scale
                    cy += delta.y() / scale
                    self._transform_state = replace(state, view_center=(cx, cy))
                    self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401
        if event.button() == QtCore.Qt.LeftButton:
            if self._move_dragging and self._active_move is not None:
                self._finalize_move(event.pos())
                event.accept()
                return
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
        if self._move_mode_enabled:
            return
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
            self._selected_curve_index = None
            self.selectedSectionChanged.emit(None)
            self.update()
            return

        if self._trk is None or index < 0 or index >= len(self._trk.sects):
            return

        sect = self._trk.sects[index]
        self._selected_section_index = index
        self._selected_section_points = self._sample_section_polyline(sect)
        self._selected_curve_index = index if sect.type == 2 else None

        end_dlong = float(sect.start_dlong + sect.length)
        if self._track_length:
            end_dlong = end_dlong % self._track_length

        start_heading, end_heading = self._get_heading_vectors(index)
        type_name = "Curve" if sect.type == 2 else "Straight"
        marker = self._curve_markers.get(index)
        selection = SectionSelection(
            index=index,
            type_name=type_name,
            start_dlong=self._round_sg_value(sect.start_dlong),
            end_dlong=self._round_sg_value(end_dlong),
            start_heading=start_heading,
            end_heading=end_heading,
            center=marker.center if marker else None,
            radius=marker.radius if marker else None,
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

    def get_section_geometries(self) -> list[SectionGeometry]:
        if self._trk is None or not self._cline or self._track_length is None:
            return []

        track_length = float(self._track_length)
        if track_length <= 0:
            return []

        sections: list[SectionGeometry] = []
        total_sections = len(self._trk.sects)
        for idx, sect in enumerate(self._trk.sects):
            start_dlong = self._round_sg_value(sect.start_dlong)
            end_dlong = self._round_sg_value((start_dlong + float(sect.length)) % track_length)

            start_x, start_y, _ = getxyz(
                self._trk, float(sect.start_dlong) % track_length, 0, self._cline
            )
            start_x = self._round_sg_value(start_x)
            start_y = self._round_sg_value(start_y)

            end_x, end_y, _ = getxyz(
                self._trk, float(sect.start_dlong + sect.length) % track_length, 0, self._cline
            )
            end_x = self._round_sg_value(end_x)
            end_y = self._round_sg_value(end_y)

            next_sect = self._trk.sects[(idx + 1) % total_sections]
            next_start = self._round_sg_value(float(next_sect.start_dlong) % track_length)
            gap = (next_start - end_dlong) % track_length

            sections.append(
                SectionGeometry(
                    index=idx,
                    start_x=start_x,
                    start_y=start_y,
                    end_x=end_x,
                    end_y=end_y,
                    gap_to_next=gap,
                )
            )

        return sections

    def get_section_headings(self) -> list[SectionHeadingData]:
        if self._sgfile is None or self._trk is None:
            return []

        start_vectors: list[tuple[float, float] | None] = []
        end_vectors: list[tuple[float, float] | None] = []
        for sect in self._sgfile.sects:
            start = (float(sect.sang1), float(sect.sang2))
            end = (float(sect.eang1), float(sect.eang2))
            start_vectors.append(self._round_heading_vector(start))
            end_vectors.append(self._round_heading_vector(end))

        headings: list[SectionHeadingData] = []
        total = len(start_vectors)
        for idx, (start, end) in enumerate(zip(start_vectors, end_vectors)):
            next_start = start_vectors[(idx + 1) % total] if total else None
            delta = self._heading_delta(end, next_start)
            headings.append(
                SectionHeadingData(
                    index=idx,
                    start_heading=start,
                    end_heading=end,
                    delta_to_next=delta,
                )
            )

        return headings

    def get_xsect_metadata(self) -> list[tuple[int, float]]:
        if self._sgfile is None:
            return []
        return [(idx, float(dlat)) for idx, dlat in enumerate(self._sgfile.xsect_dlats)]

    def get_section_range(self, index: int) -> tuple[float, float] | None:
        if self._trk is None or index < 0 or index >= len(self._trk.sects):
            return None
        start = float(self._trk.sects[index].start_dlong)
        end = start + float(self._trk.sects[index].length)
        return start, end

    def _get_heading_vectors(
        self, index: int
    ) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
        if (
            self._sgfile is None
            or self._trk is None
            or self._cline is None
            or index < 0
            or index >= len(self._sgfile.sects)
            or index >= len(self._trk.sects)
        ):
            return None, None

        trk_sect = self._trk.sects[index]
        if getattr(trk_sect, "type", None) == 2:
            sg_sect = self._sgfile.sects[index]
            start = (
                float(sg_sect.sang1),
                float(sg_sect.sang2),
            )
            end = (
                float(sg_sect.eang1),
                float(sg_sect.eang2),
            )
            return self._round_heading_vector(start), self._round_heading_vector(end)

        track_length = float(self._track_length or 0)
        if track_length <= 0:
            return None, None

        start_x, start_y, _ = getxyz(
            self._trk, float(trk_sect.start_dlong) % track_length, 0, self._cline
        )
        end_x, end_y, _ = getxyz(
            self._trk, float(trk_sect.start_dlong + trk_sect.length) % track_length, 0, self._cline
        )
        dx = end_x - start_x
        dy = end_y - start_y
        length = (dx * dx + dy * dy) ** 0.5
        if length <= 0:
            return None, None

        heading = (dx / length, dy / length)
        rounded_heading = self._round_heading_vector(heading)
        return rounded_heading, rounded_heading

    def build_elevation_profile(self, xsect_index: int, samples_per_section: int = 24) -> ElevationProfileData | None:
        if (
            self._sgfile is None
            or self._trk is None
            or self._track_length is None
            or xsect_index < 0
            or xsect_index >= self._sgfile.num_xsects
        ):
            return None

        dlongs: list[float] = []
        sg_altitudes: list[float] = []
        trk_altitudes: list[float] = []
        section_ranges: list[tuple[float, float]] = []

        dlat_value = float(self._trk.xsect_dlats[xsect_index])
        for sect_idx, (sg_sect, trk_sect) in enumerate(zip(self._sgfile.sects, self._trk.sects)):
            prev_idx = (sect_idx - 1) % self._sgfile.num_sects
            begin_alt = float(self._sgfile.sects[prev_idx].alt[xsect_index])
            end_alt = float(sg_sect.alt[xsect_index])

            sg_length = float(sg_sect.length)
            if sg_length <= 0:
                continue
            cur_slope = float(self._sgfile.sects[prev_idx].grade[xsect_index]) / 8192.0
            next_slope = float(sg_sect.grade[xsect_index]) / 8192.0
            grade1 = (2 * begin_alt / sg_length + cur_slope + next_slope - 2 * end_alt / sg_length) * sg_length
            grade2 = (3 * end_alt / sg_length - 3 * begin_alt / sg_length - 2 * cur_slope - next_slope) * sg_length
            grade3 = cur_slope * sg_length

            start_dlong = float(trk_sect.start_dlong)
            trk_length = float(trk_sect.length)
            if trk_length <= 0:
                continue
            section_ranges.append((start_dlong, start_dlong + trk_length))

            for step in range(samples_per_section + 1):
                fraction = step / samples_per_section
                dlong = start_dlong + fraction * trk_length

                sg_alt = grade1 * fraction ** 3 + grade2 * fraction ** 2 + grade3 * fraction + begin_alt
                trk_alt = get_alt(self._trk, sect_idx, fraction, dlat_value)

                dlongs.append(dlong)
                sg_altitudes.append(sg_alt)
                trk_altitudes.append(trk_alt)

        label = f"X-Section {xsect_index} (DLAT {dlat_value:.0f})"
        return ElevationProfileData(
            dlongs=dlongs,
            sg_altitudes=sg_altitudes,
            trk_altitudes=trk_altitudes,
            section_ranges=section_ranges,
            track_length=float(self._track_length),
            xsect_label=label,
        )

    @staticmethod
    def _round_sg_value(value: float) -> float:
        """Round SG-derived values to match the raw file precision."""

        return float(round(value))

    @staticmethod
    def _normalize_heading_vector(
        vector: tuple[float, float] | None,
    ) -> tuple[float, float] | None:
        if vector is None:
            return None

        length = (vector[0] * vector[0] + vector[1] * vector[1]) ** 0.5
        if length <= 0:
            return None

        return (vector[0] / length, vector[1] / length)

    def _round_heading_vector(
        self, vector: tuple[float, float] | None
    ) -> tuple[float, float] | None:
        normalized = self._normalize_heading_vector(vector)
        if normalized is None:
            return None

        return (round(normalized[0], 5), round(normalized[1], 5))

    def _heading_delta(
        self, end: tuple[float, float] | None, next_start: tuple[float, float] | None
    ) -> float | None:
        end_norm = self._normalize_heading_vector(end)
        next_norm = self._normalize_heading_vector(next_start)
        if end_norm is None or next_norm is None:
            return None

        dot = max(-1.0, min(1.0, end_norm[0] * next_norm[0] + end_norm[1] * next_norm[1]))
        cross = end_norm[0] * next_norm[1] - end_norm[1] * next_norm[0]
        angle_deg = math.degrees(math.atan2(cross, dot))
        return round(angle_deg, 4)

    def _centerline_point_normal_and_tangent(
        self, dlong: float
    ) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]] | None:
        if not self._trk or not self._cline or not self._track_length:
            return None

        track_length = self._track_length
        if track_length <= 0:
            return None

        def _wrap(value: float) -> float:
            while value < 0:
                value += track_length
            while value >= track_length:
                value -= track_length
            return value

        base = _wrap(float(dlong))
        delta = max(50.0, track_length * 0.002)
        prev_dlong = _wrap(base - delta)
        next_dlong = _wrap(base + delta)

        px, py, _ = getxyz(self._trk, prev_dlong, 0, self._cline)
        nx, ny, _ = getxyz(self._trk, next_dlong, 0, self._cline)
        cx, cy, _ = getxyz(self._trk, base, 0, self._cline)

        vx = nx - px
        vy = ny - py
        length = (vx * vx + vy * vy) ** 0.5
        if length == 0:
            return None

        tangent = (vx / length, vy / length)
        normal = (-vy / length, vx / length)
        return (cx, cy), normal, tangent

    # ------------------------------------------------------------------
    # Point moving
    # ------------------------------------------------------------------
    def begin_point_move_mode(self) -> None:
        if not self._section_endpoints:
            return

        self._move_mode_enabled = True
        self._active_move = None
        self._move_dragging = False
        self._pending_move_length = None

    def cancel_point_move_mode(self) -> None:
        self._move_mode_enabled = False
        self._active_move = None
        self._move_dragging = False
        self._pending_move_length = None
        self._refresh_section_endpoints()
        self.update()

    def _attempt_begin_move(self, pos: QtCore.QPoint) -> bool:
        if not self._trk or not self._section_endpoints or self._track_length is None:
            return False

        track_point = self._map_to_track(QtCore.QPointF(pos))
        transform = self._current_transform()
        if track_point is None or transform is None:
            return False

        scale, _ = transform
        tolerance_units = 12 / max(scale, 1e-6)
        candidate = self._find_movable_endpoint(track_point, tolerance_units)
        if candidate is None:
            return False

        self._active_move = candidate
        self._move_dragging = True
        self._pending_move_length = candidate.first_length
        self._update_move_preview(candidate.joint_point, candidate.first_length)
        return True

    def _find_movable_endpoint(
        self, track_point: Point, tolerance: float
    ) -> MoveCandidate | None:
        if self._trk is None or not self._section_endpoints:
            return None

        best_candidate: MoveCandidate | None = None
        best_distance_sq = tolerance * tolerance
        total_sections = len(self._trk.sects)

        for idx, sect in enumerate(self._trk.sects):
            if getattr(sect, "type", None) != 1:
                continue
            next_idx = (idx + 1) % total_sections
            next_sect = self._trk.sects[next_idx]
            if getattr(next_sect, "type", None) != 1:
                continue

            heading_a = self._section_heading_vector(idx)
            heading_b = self._section_heading_vector(next_idx)
            if heading_a is None or heading_b is None:
                continue

            dot = heading_a[0] * heading_b[0] + heading_a[1] * heading_b[1]
            cross = heading_a[0] * heading_b[1] - heading_a[1] * heading_b[0]
            if dot < 0.999 or abs(cross) > 1e-3:
                continue

            start_point, joint_point = self._section_endpoints[idx]
            _, end_point = self._section_endpoints[next_idx]
            dx = track_point[0] - joint_point[0]
            dy = track_point[1] - joint_point[1]
            distance_sq = dx * dx + dy * dy
            if distance_sq <= best_distance_sq:
                first_length = float(sect.length)
                second_length = float(next_sect.length)
                best_distance_sq = distance_sq
                best_candidate = MoveCandidate(
                    first_index=idx,
                    second_index=next_idx,
                    start_point=start_point,
                    joint_point=joint_point,
                    end_point=end_point,
                    first_length=first_length,
                    second_length=second_length,
                )

        return best_candidate

    def _project_move(self, target: Point, candidate: MoveCandidate) -> tuple[Point, float]:
        start = candidate.start_point
        end = candidate.end_point
        total_length = candidate.first_length + candidate.second_length
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        distance = (dx * dx + dy * dy) ** 0.5
        if distance <= 0 or total_length <= 0:
            return candidate.joint_point, candidate.first_length

        direction = (dx / distance, dy / distance)
        projection = (target[0] - start[0]) * direction[0] + (target[1] - start[1]) * direction[1]
        projection = max(0.0, min(distance, projection))

        min_length = 1.0
        new_first_length = (projection / distance) * total_length
        new_first_length = max(min_length, min(total_length - min_length, new_first_length))
        ratio = new_first_length / total_length

        new_joint = (
            start[0] + direction[0] * distance * ratio,
            start[1] + direction[1] * distance * ratio,
        )
        return new_joint, new_first_length

    def _update_move_preview(self, joint_point: Point, first_length: float) -> None:
        if self._active_move is None:
            return

        self._pending_move_length = first_length
        self._section_endpoints[self._active_move.first_index] = (
            self._active_move.start_point,
            joint_point,
        )
        self._section_endpoints[self._active_move.second_index] = (
            joint_point,
            self._active_move.end_point,
        )
        self.update()

    def _update_move_during_drag(self, pos: QtCore.QPoint) -> None:
        if self._active_move is None:
            return

        track_point = self._map_to_track(QtCore.QPointF(pos))
        if track_point is None:
            return

        joint_point, new_length = self._project_move(track_point, self._active_move)
        self._update_move_preview(joint_point, new_length)

    def _finalize_move(self, pos: QtCore.QPoint) -> None:
        if self._active_move is None:
            self.cancel_point_move_mode()
            return

        track_point = self._map_to_track(QtCore.QPointF(pos))
        if track_point is None:
            joint_point = self._section_endpoints[self._active_move.first_index][1]
            first_length = self._pending_move_length or self._active_move.first_length
        else:
            joint_point, first_length = self._project_move(track_point, self._active_move)

        self._apply_move(first_length, joint_point)

    def _resequence_start_dlongs(self) -> None:
        if self._trk is None:
            return

        if not self._trk.sects:
            return

        base_start = float(self._trk.sects[0].start_dlong)
        self._trk.sects[0].start_dlong = base_start
        if self._sgfile is not None and self._sgfile.sects:
            self._sgfile.sects[0].start_dlong = base_start
            self._sgfile.sects[0].end_dlong = base_start + float(self._trk.sects[0].length)

        for idx in range(1, len(self._trk.sects)):
            prev = self._trk.sects[idx - 1]
            current_start = float(prev.start_dlong + prev.length)
            self._trk.sects[idx].start_dlong = current_start
            if self._sgfile is not None and idx < len(self._sgfile.sects):
                self._sgfile.sects[idx].start_dlong = current_start
                self._sgfile.sects[idx].end_dlong = current_start + float(
                    self._trk.sects[idx].length
                )

        self._trk.trklength = float(sum(float(sect.length) for sect in self._trk.sects))
        if hasattr(self._trk, "header") and len(self._trk.header) > 2:
            self._trk.header[2] = int(self._trk.trklength)

    def _apply_move(self, first_length: float, joint_point: Point) -> None:
        if self._active_move is None or self._trk is None or self._cline is None:
            self.cancel_point_move_mode()
            return

        total_length = self._active_move.first_length + self._active_move.second_length
        min_length = 1.0
        clamped_first = max(min_length, min(total_length - min_length, first_length))
        clamped_second = total_length - clamped_first

        first_idx = self._active_move.first_index
        second_idx = self._active_move.second_index

        first_sect = self._trk.sects[first_idx]
        second_sect = self._trk.sects[second_idx]
        first_sect.length = clamped_first
        second_sect.length = clamped_second

        if self._sgfile is not None and first_idx < len(self._sgfile.sects):
            sg_first = self._sgfile.sects[first_idx]
            sg_first.length = clamped_first
            sg_first.end_x, sg_first.end_y = joint_point
            sg_first.end_dlong = sg_first.start_dlong + sg_first.length

        if self._sgfile is not None and second_idx < len(self._sgfile.sects):
            sg_second = self._sgfile.sects[second_idx]
            sg_second.start_x, sg_second.start_y = joint_point
            sg_second.length = clamped_second

        self._resequence_start_dlongs()

        if second_idx < len(self._cline):
            self._cline[second_idx] = joint_point

        self._section_endpoints[first_idx] = (
            self._active_move.start_point,
            joint_point,
        )
        self._section_endpoints[second_idx] = (
            joint_point,
            self._active_move.end_point,
        )

        self._pending_move_length = None
        self._refresh_preview_after_edit()
        self._move_mode_enabled = False
        self._active_move = None
        self._move_dragging = False
        self.pointMoveFinished.emit()

    def _refresh_preview_after_edit(self) -> None:
        if self._trk is None:
            return

        self._cline = get_cline_pos(self._trk)
        self._sampled_centerline, self._sampled_dlongs, self._sampled_bounds = (
            sample_centerline(self._trk, self._cline)
        )
        self._centerline_index = build_centerline_index(
            self._sampled_centerline, self._sampled_bounds
        )
        self._track_length = float(self._trk.trklength)
        self._refresh_section_endpoints()

        if self._selected_section_index is not None:
            current = self._selected_section_index
            self._set_selected_section(current)
        else:
            self.update()

    # ------------------------------------------------------------------
    # Public controls
    # ------------------------------------------------------------------
    def set_show_curve_markers(self, visible: bool) -> None:
        self._show_curve_markers = visible
        self.update()

    def select_next_section(self) -> None:
        if self._trk is None or not self._trk.sects:
            return

        if self._selected_section_index is None:
            self._set_selected_section(0)
            return

        next_index = (self._selected_section_index + 1) % len(self._trk.sects)
        self._set_selected_section(next_index)

    def select_previous_section(self) -> None:
        if self._trk is None or not self._trk.sects:
            return

        if self._selected_section_index is None:
            self._set_selected_section(len(self._trk.sects) - 1)
            return

        prev_index = (self._selected_section_index - 1) % len(self._trk.sects)
        self._set_selected_section(prev_index)
