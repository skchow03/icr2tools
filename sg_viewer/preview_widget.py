from __future__ import annotations

from dataclasses import dataclass, replace
import math
from pathlib import Path
from typing import List, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets

from icr2_core.trk.sg_classes import SGFile
from icr2_core.trk.trk_classes import TRKFile
from icr2_core.trk.trk_utils import get_alt
from track_viewer.geometry import CenterlineIndex, project_point_to_centerline
from sg_viewer.elevation_profile import ElevationProfileData
from sg_viewer import preview_loader, sg_rendering

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
        self._sampled_centerline: List[Point] = []
        self._centerline_polylines: list[list[Point]] = []
        self._sampled_dlongs: List[float] = []
        self._sampled_bounds: tuple[float, float, float, float] | None = None
        self._centerline_index: CenterlineIndex | None = None
        self._status_message = "Select an SG file to begin."

        self._sections: list[preview_loader.SectionPreview] = []
        self._selected_curve_index: int | None = None
        self._section_endpoints: list[tuple[Point, Point]] = []
        self._start_finish_mapping: tuple[Point, Point, Point] | None = None

        self._track_length: float | None = None
        self._selected_section_index: int | None = None
        self._selected_section_points: List[Point] = []

        self._transform_state = preview_loader.TransformState()
        self._is_panning = False
        self._last_mouse_pos: QtCore.QPoint | None = None
        self._press_pos: QtCore.QPoint | None = None

        self._show_curve_markers = True

    def clear(self, message: str | None = None) -> None:
        self._sgfile = None
        self._trk = None
        self._cline = None
        self._sampled_centerline = []
        self._centerline_polylines = []
        self._sampled_dlongs = []
        self._sampled_bounds = None
        self._centerline_index = None
        self._track_length = None
        self._selected_section_index = None
        self._selected_section_points = []
        self._section_endpoints = []
        self._sections = []
        self._selected_curve_index = None
        self._start_finish_mapping = None
        self._transform_state = preview_loader.TransformState()
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

        data = preview_loader.load_preview(path)

        self._sgfile = data.sgfile
        self._trk = data.trk
        self._cline = data.cline
        self._sampled_centerline = data.sampled_centerline
        self._centerline_polylines = [list(data.sampled_centerline)] if data.sampled_centerline else []
        self._sampled_dlongs = data.sampled_dlongs
        self._sampled_bounds = data.sampled_bounds
        self._centerline_index = data.centerline_index
        self._track_length = data.track_length
        self._selected_section_index = None
        self._selected_section_points = []
        self._sections = data.sections
        self._section_endpoints = data.section_endpoints
        self._start_finish_mapping = data.start_finish_mapping
        self._selected_curve_index = None
        self._transform_state = preview_loader.TransformState()
        self._status_message = data.status_message
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
            sg_rendering.draw_placeholder(painter, self.rect(), self._status_message)
            painter.end()
            return

        transform = self._current_transform()
        if not transform:
            sg_rendering.draw_placeholder(painter, self.rect(), "Unable to fit view")
            painter.end()
            return

        sg_rendering.draw_centerlines(
            painter,
            self._centerline_polylines,
            self._selected_section_points,
            transform,
            self.height(),
        )

        sg_rendering.draw_section_endpoints(
            painter,
            self._section_endpoints,
            self._selected_section_index,
            transform,
            self.height(),
        )

        if self._show_curve_markers:
            sg_rendering.draw_curve_markers(
                painter,
                [sect for sect in self._sections if sect.center is not None],
                self._selected_curve_index,
                transform,
                self.height(),
            )

        sg_rendering.draw_start_finish_line(
            painter,
            self._start_finish_mapping,
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
        if event.button() == QtCore.Qt.LeftButton and self._sampled_centerline:
            self._is_panning = True
            self._last_mouse_pos = event.pos()
            self._press_pos = event.pos()
            self._transform_state = replace(self._transform_state, user_transform_active=True)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401
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
        if not self._sections or self._track_length is None:
            return None

        track_length = self._track_length or 0
        for idx, sect in enumerate(self._sections):
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

        if not self._sections or index < 0 or index >= len(self._sections):
            return

        sect = self._sections[index]
        self._selected_section_index = index
        self._selected_section_points = sect.polyline
        self._selected_curve_index = sect.section_id if sect.center is not None else None

        end_dlong = float(sect.start_dlong + sect.length)
        if self._track_length:
            end_dlong = end_dlong % self._track_length

        start_heading, end_heading = self._get_heading_vectors(index)
        type_name = "Curve" if sect.type_name == "curve" else "Straight"
        selection = SectionSelection(
            index=sect.section_id,
            type_name=type_name,
            start_dlong=self._round_sg_value(sect.start_dlong),
            end_dlong=self._round_sg_value(end_dlong),
            start_heading=start_heading,
            end_heading=end_heading,
            center=sect.center,
            radius=sect.radius,
        )
        self.selectedSectionChanged.emit(selection)
        self.update()

    def get_section_set(self) -> tuple[list[preview_loader.SectionPreview], float | None]:
        track_length = float(self._track_length) if self._track_length is not None else None
        return list(self._sections), track_length

    def set_sections(self, sections: list[preview_loader.SectionPreview]) -> None:
        self._sections = [preview_loader.update_section_geometry(sect) for sect in sections]
        self._section_endpoints = [(sect.start, sect.end) for sect in self._sections]

        self._rebuild_centerline_from_sections()

        if (
            self._selected_section_index is not None
            and 0 <= self._selected_section_index < len(self._sections)
        ):
            self._set_selected_section(self._selected_section_index)
        else:
            self._selected_section_index = None
            self.selectedSectionChanged.emit(None)
        self.update()

    def get_section_headings(self) -> list[SectionHeadingData]:
        if not self._sections:
            return []

        headings: list[SectionHeadingData] = []
        total = len(self._sections)
        for idx, sect in enumerate(self._sections):
            start = sect.start_heading
            end = sect.end_heading
            next_start = self._sections[(idx + 1) % total].start_heading if total else None
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
        if not self._sections or index < 0 or index >= len(self._sections):
            return None
        start = float(self._sections[index].start_dlong)
        end = start + float(self._sections[index].length)
        return start, end

    def _rebuild_centerline_from_sections(self) -> None:
        """Flatten section polylines into the active centreline representation."""

        self._centerline_polylines = []
        polylines = [sect.polyline for sect in self._sections if sect.polyline]
        if not polylines:
            return

        points: list[Point] = []
        for polyline in polylines:
            if not polyline:
                continue
            if points and points[-1] == polyline[0]:
                points.extend(polyline[1:])
            else:
                points.extend(polyline)

        if len(points) < 2:
            return

        self._centerline_polylines = polylines

        bounds = (
            min(p[0] for p in points),
            max(p[0] for p in points),
            min(p[1] for p in points),
            max(p[1] for p in points),
        )

        dlongs: list[float] = [0.0]
        distance = 0.0
        for prev, cur in zip(points, points[1:]):
            distance += math.hypot(cur[0] - prev[0], cur[1] - prev[1])
            dlongs.append(distance)

        self._sampled_centerline = points
        self._sampled_dlongs = dlongs
        self._sampled_bounds = bounds
        self._centerline_index = preview_loader.build_centerline_index(points, bounds)
        self._update_fit_scale()

    def _get_heading_vectors(
        self, index: int
    ) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
        if not self._sections or index < 0 or index >= len(self._sections):
            return None, None

        sect = self._sections[index]
        return sect.start_heading, sect.end_heading

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

    # ------------------------------------------------------------------
    # Public controls
    # ------------------------------------------------------------------
    def set_show_curve_markers(self, visible: bool) -> None:
        self._show_curve_markers = visible
        self.update()

    def select_next_section(self) -> None:
        if not self._sections:
            return

        if self._selected_section_index is None:
            self._set_selected_section(0)
            return

        next_index = (self._selected_section_index + 1) % len(self._sections)
        self._set_selected_section(next_index)

    def select_previous_section(self) -> None:
        if not self._sections:
            return

        if self._selected_section_index is None:
            self._set_selected_section(len(self._sections) - 1)
            return

        prev_index = (self._selected_section_index - 1) % len(self._sections)
        self._set_selected_section(prev_index)
