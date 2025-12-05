from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import List, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets

from icr2_core.trk.sg_classes import SGFile
from icr2_core.trk.trk_classes import TRKFile
from icr2_core.trk.trk_exporter import write_trk
from icr2_core.trk.trk_utils import get_alt, get_cline_pos, getxyz, heading2rad
from track_viewer import rendering
from track_viewer.geometry import (
    CenterlineIndex,
    build_centerline_index,
    project_point_to_centerline,
    sample_centerline,
)
from sg_viewer.elevation_profile import ElevationProfileData

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
    connected_to_next: bool | None = None


@dataclass
class CurveMarker:
    center: Point
    start: Point
    end: Point
    radius: float


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

        self._sgfile: SGFile | None = None
        self._trk: TRKFile | None = None
        self._cline: List[Point] | None = None
        self._section_polylines: list[list[Point]] = []
        self._sampled_centerline: List[Point] = []
        self._sampled_dlongs: List[float] = []
        self._sampled_bounds: tuple[float, float, float, float] | None = None
        self._centerline_index: CenterlineIndex | None = None
        self._status_message = "Select an SG file to begin."

        self._curve_markers: dict[int, CurveMarker] = {}
        self._selected_curve_index: int | None = None
        self._track_length: float | None = None
        self._selected_section_index: int | None = None
        self._selected_section_points: List[Point] = []
        self._section_connections: list[bool] = []

        self._fit_scale: float | None = None
        self._current_scale: float | None = None
        self._view_center: Point | None = None
        self._user_transform_active = False
        self._is_panning = False
        self._last_mouse_pos: QtCore.QPoint | None = None
        self._press_pos: QtCore.QPoint | None = None

        self._show_curve_markers = True
        self._dirty = False
        self._current_path: Path | None = None

    def clear(self, message: str | None = None) -> None:
        self._sgfile = None
        self._trk = None
        self._cline = None
        self._section_polylines = []
        self._sampled_centerline = []
        self._sampled_dlongs = []
        self._sampled_bounds = None
        self._centerline_index = None
        self._track_length = None
        self._selected_section_index = None
        self._selected_section_points = []
        self._section_connections = []
        self._curve_markers = {}
        self._selected_curve_index = None
        self._fit_scale = None
        self._current_scale = None
        self._view_center = None
        self._user_transform_active = False
        self._is_panning = False
        self._last_mouse_pos = None
        self._press_pos = None
        self._dirty = False
        self._current_path = None
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

        sgfile = SGFile.from_sg(str(path))
        trk = TRKFile.from_sg(str(path))
        cline = get_cline_pos(trk)
        sampled, sampled_dlongs, bounds = sample_centerline(trk, cline)

        if not sampled or bounds is None:
            raise ValueError("Failed to build centreline from SG file")

        self._sgfile = sgfile
        self._trk = trk
        self._cline = cline
        self._track_length = float(trk.trklength)
        self._section_polylines = self._build_section_polylines(trk)
        self._section_connections = self._calculate_section_connections()
        self._sampled_centerline = sampled
        self._sampled_dlongs = sampled_dlongs
        self._sampled_bounds = bounds
        self._centerline_index = build_centerline_index(sampled, bounds)
        self._selected_section_index = None
        self._selected_section_points = []
        self._curve_markers = self._build_curve_markers(trk)
        self._selected_curve_index = None
        self._fit_scale = None
        self._current_scale = None
        self._view_center = None
        self._user_transform_active = False
        self._status_message = f"Loaded {path.name}"
        self._current_path = path
        self._dirty = False
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

        polylines = self._section_polylines or [self._sampled_centerline]
        for section_polyline in polylines:
            rendering.draw_centerline(
                painter,
                section_polyline,
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
        self._draw_start_finish_line(painter, transform)

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
            connected_to_next=self._is_section_connected_to_next(index),
        )
        self.selectedSectionChanged.emit(selection)
        self.update()

    def _get_selected_section_endpoints(self) -> tuple[Point, Point] | None:
        if (
            self._trk is None
            or self._cline is None
            or self._track_length is None
            or self._selected_section_index is None
        ):
            return None

        sect = self._trk.sects[self._selected_section_index]
        track_length = float(self._track_length)
        start_x, start_y, _ = getxyz(
            self._trk, float(sect.start_dlong) % track_length, 0, self._cline
        )
        end_x, end_y, _ = getxyz(
            self._trk, float(sect.start_dlong + sect.length) % track_length, 0, self._cline
        )
        return (start_x, start_y), (end_x, end_y)

    def _build_section_polylines(self, trk: TRKFile) -> list[list[Point]]:
        if self._track_length is None or self._cline is None:
            return []

        polylines: list[list[Point]] = []
        for sect in trk.sects:
            polyline = self._sample_section_polyline(sect)
            if polyline:
                polylines.append(polyline)
        return polylines

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

    def _calculate_section_connections(self) -> list[bool]:
        if self._sgfile is None:
            return []

        connections: list[bool] = []
        total_sections = len(self._sgfile.sects)
        if total_sections == 0:
            return connections

        for idx, sect in enumerate(self._sgfile.sects):
            next_sect = self._sgfile.sects[(idx + 1) % total_sections]
            connected = math.isclose(
                float(sect.end_x), float(next_sect.start_x), abs_tol=0.5
            ) and math.isclose(float(sect.end_y), float(next_sect.start_y), abs_tol=0.5)
            connections.append(connected)

        return connections

    def _is_section_connected_to_next(self, index: int) -> bool:
        if not self._section_connections:
            return False

        total_sections = len(self._section_connections)
        if total_sections == 0:
            return False

        return self._section_connections[index % total_sections]

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

    def _build_curve_markers(self, trk: TRKFile) -> dict[int, CurveMarker]:
        markers: dict[int, CurveMarker] = {}
        track_length = float(getattr(trk, "trklength", 0) or 0)
        cline = self._cline

        for idx, sect in enumerate(trk.sects):
            if getattr(sect, "type", None) != 2:
                continue
            if hasattr(sect, "center_x") and hasattr(sect, "center_y"):
                center = (float(sect.center_x), float(sect.center_y))
            elif hasattr(sect, "ang1") and hasattr(sect, "ang2"):
                # TRK section parsing stores curve centers in ang1/ang2
                center = (float(sect.ang1), float(sect.ang2))
            else:
                continue

            if cline and track_length > 0:
                start_x, start_y, _ = getxyz(
                    trk, float(sect.start_dlong) % track_length, 0, cline
                )
                end_dlong = float(sect.start_dlong + sect.length)
                end_dlong = end_dlong % track_length if track_length else end_dlong
                end_x, end_y, _ = getxyz(trk, end_dlong, 0, cline)
                start = (start_x, start_y)
                end = (end_x, end_y)
            else:
                start = (
                    float(getattr(sect, "start_x", 0.0)),
                    float(getattr(sect, "start_y", 0.0)),
                )
                end = (
                    float(getattr(sect, "end_x", 0.0)),
                    float(getattr(sect, "end_y", 0.0)),
                )
            radius = ((start[0] - center[0]) ** 2 + (start[1] - center[1]) ** 2) ** 0.5
            markers[idx] = CurveMarker(center=center, start=start, end=end, radius=radius)
        return markers

    def _draw_curve_markers(self, painter: QtGui.QPainter, transform: Transform) -> None:
        if not self._curve_markers or not self._show_curve_markers:
            return

        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        default_color = QtGui.QColor(140, 140, 140)
        highlight_color = QtGui.QColor("red")

        for idx, marker in self._curve_markers.items():
            is_selected = idx == self._selected_curve_index
            color = highlight_color if is_selected else default_color
            width = 2 if is_selected else 1

            painter.setPen(QtGui.QPen(color, width))
            painter.setBrush(QtGui.QBrush(color))

            center_point = rendering.map_point(
                marker.center[0], marker.center[1], transform, self.height()
            )
            start_point = rendering.map_point(
                marker.start[0], marker.start[1], transform, self.height()
            )
            end_point = rendering.map_point(
                marker.end[0], marker.end[1], transform, self.height()
            )

            painter.drawLine(QtCore.QLineF(center_point, start_point))
            painter.drawLine(QtCore.QLineF(center_point, end_point))
            painter.drawEllipse(center_point, 4, 4)
            painter.drawEllipse(start_point, 4, 4)
            painter.drawEllipse(end_point, 4, 4)

        painter.restore()

    def _draw_start_finish_line(self, painter: QtGui.QPainter, transform: Transform) -> None:
        if self._track_length is None:
            return

        mapping = self._centerline_point_normal_and_tangent(0.0)
        if mapping is None:
            return

        (cx, cy), normal, tangent = mapping
        scale, _ = transform
        if scale == 0:
            return

        half_length_track = 12.0 / scale
        direction_length_track = 10.0 / scale

        start = rendering.map_point(
            cx - normal[0] * half_length_track,
            cy - normal[1] * half_length_track,
            transform,
            self.height(),
        )
        end = rendering.map_point(
            cx + normal[0] * half_length_track,
            cy + normal[1] * half_length_track,
            transform,
            self.height(),
        )

        direction_start = end
        direction_end = rendering.map_point(
            cx + normal[0] * half_length_track + tangent[0] * direction_length_track,
            cy + normal[1] * half_length_track + tangent[1] * direction_length_track,
            transform,
            self.height(),
        )

        pen = QtGui.QPen(QtGui.QColor("white"), 3.0)
        pen.setCapStyle(QtCore.Qt.RoundCap)

        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setPen(pen)
        painter.drawLine(QtCore.QLineF(start, end))
        painter.drawLine(QtCore.QLineF(direction_start, direction_end))
        painter.restore()

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
    # Public controls
    # ------------------------------------------------------------------
    def set_show_curve_markers(self, visible: bool) -> None:
        self._show_curve_markers = visible
        self.update()

    def is_dirty(self) -> bool:
        return self._dirty

    def current_path(self) -> Path | None:
        return self._current_path

    def save(self, path: Path) -> None:
        if self._sgfile is None or self._trk is None:
            raise ValueError("No SG file loaded")

        self._sgfile.output_sg(str(path))
        write_trk(self._trk, str(path.with_suffix(".trk")))
        self._dirty = False
        self._current_path = path

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

    def _curve_orientation_sign(
        self, center: Point, start_point: Point, heading_value: int
    ) -> int:
        heading_rad = heading2rad(heading_value)
        radial_angle = math.atan2(start_point[1] - center[1], start_point[0] - center[0])

        def _normalize(angle: float) -> float:
            while angle <= -math.pi:
                angle += 2 * math.pi
            while angle > math.pi:
                angle -= 2 * math.pi
            return angle

        cw_delta = abs(_normalize(heading_rad - (radial_angle - math.pi / 2)))
        ccw_delta = abs(_normalize(heading_rad - (radial_angle + math.pi / 2)))
        return -1 if cw_delta < ccw_delta else 1
