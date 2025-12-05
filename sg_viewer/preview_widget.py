from __future__ import annotations

from dataclasses import dataclass, replace
import math
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Set

from PyQt5 import QtCore, QtGui, QtWidgets

from icr2_core.trk.sg_classes import SGFile
from icr2_core.trk.trk_classes import TRKFile
from icr2_core.trk.trk_utils import get_alt, getxyz
from track_viewer.geometry import CenterlineIndex, project_point_to_centerline

from sg_viewer.elevation_profile import ElevationProfileData
from sg_viewer import preview_loader, preview_rendering
from sg_viewer.editor_state import EditorState


Point = Tuple[float, float]
Transform = tuple[float, Tuple[float, float]]


@dataclass
class SectionSelection:
    index: int
    type_name: str
    start_dlong: float
    end_dlong: float
    start_heading: Tuple[float, float] | None = None
    end_heading: Tuple[float, float] | None = None
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
    start_heading: Tuple[float, float] | None
    end_heading: Tuple[float, float] | None
    delta_to_next: float | None


class SGPreviewWidget(QtWidgets.QWidget):
    """
    Preview widget that draws an SG/TRK centreline and exposes per-section metadata.

    It is wired to an EditorState which owns the SG/TRK/PreviewData, and supports:
      - section selection
      - move-point mode (Phase 1): detach endpoints and drag them visually
    """

    selectedSectionChanged = QtCore.pyqtSignal(object)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(640, 480)
        self.setMouseTracking(True)

        palette = self.palette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor("black"))
        self.setPalette(palette)

        # Editor model
        self._state: EditorState | None = None

        # Cached references for convenience (derived from EditorState.preview)
        self._sgfile: SGFile | None = None
        self._trk: TRKFile | None = None
        self._cline: List[Point] | None = None
        self._sampled_centerline: List[Point] = []
        self._sampled_dlongs: List[float] = []
        self._sampled_bounds: Tuple[float, float, float, float] | None = None
        self._centerline_index: CenterlineIndex | None = None
        self._track_length: float | None = None
        self._curve_markers: Dict[int, preview_loader.CurveMarker] = {}

        # Section endpoints as built from TRK + cline
        self._base_section_endpoints: List[Tuple[Point, Point]] = []
        self._section_endpoints: List[Tuple[Point, Point]] = []

        # Endpoint overrides for move-point mode: {(index, "start"/"end"): (x, y)}
        self._endpoint_overrides: Dict[Tuple[int, str], Point] = {}

        # Selection state
        self._selected_section_index: int | None = None
        self._selected_section_points: List[Point] = []
        self._selected_curve_index: int | None = None

        # View transform state
        self._transform_state = preview_loader.TransformState()
        self._is_panning = False
        self._last_mouse_pos: QtCore.QPoint | None = None
        self._press_pos: QtCore.QPoint | None = None

        # Move-point mode (Phase 1)
        self._move_mode: bool = False
        self._detached_endpoints: Set[Tuple[int, str]] = set()
        self._dragging_section_index: Optional[int] = None
        self._dragging_endpoint_type: Optional[str] = None  # "start" or "end"
        self._dragging_initial_pos: Optional[Point] = None
        self._dragging_initial_mouse_pos: Optional[QtCore.QPoint] = None

        # Options
        self._show_curve_markers = True
        self._status_message = "Select an SG file to begin."

    # ------------------------------------------------------------------
    # State binding
    # ------------------------------------------------------------------
    def set_state(self, state: EditorState | None) -> None:
        """
        Bind an EditorState to this widget and refresh the preview.
        """
        self._state = state
        if state is None:
            self.clear()
            return
        self._apply_preview(state.preview)
        self.selectedSectionChanged.emit(None)
        self.update()

    def refresh_from_state(self) -> None:
        """
        Re-bind all cached preview fields from the current EditorState.
        Call this after you mutate the state (e.g., after an edit).
        """
        if self._state is None:
            self.clear()
            return
        self._apply_preview(self._state.preview)
        # Try to restore selected section
        if self._selected_section_index is not None:
            idx = self._selected_section_index
            if self._trk and 0 <= idx < len(self._trk.sects):
                self._set_selected_section(idx)
            else:
                self._set_selected_section(None)
        self.update()

    def _apply_preview(self, data: preview_loader.PreviewData) -> None:
        """
        Copy preview data into local caches. Keeps widget as a "dumb view"
        over PreviewData while allowing fast access to fields.
        """
        self._sgfile = data.sgfile
        self._trk = data.trk
        self._cline = data.cline
        self._sampled_centerline = list(data.sampled_centerline)
        self._sampled_dlongs = list(data.sampled_dlongs)
        self._sampled_bounds = data.sampled_bounds
        self._centerline_index = data.centerline_index
        self._track_length = data.track_length
        self._curve_markers = dict(data.curve_markers)

        self._base_section_endpoints = list(data.section_endpoints)
        self._section_endpoints = list(data.section_endpoints)
        self._endpoint_overrides.clear()

        self._status_message = data.status_message

        # Reset view transform so it refits around new bounds
        self._transform_state = preview_loader.TransformState()
        self._update_fit_scale()

        # Clear selection and move mode state on new preview
        self._selected_section_index = None
        self._selected_section_points = []
        self._selected_curve_index = None
        self._detached_endpoints.clear()
        self._dragging_section_index = None
        self._dragging_endpoint_type = None
        self._dragging_initial_pos = None
        self._dragging_initial_mouse_pos = None

    # ------------------------------------------------------------------
    # Public control API
    # ------------------------------------------------------------------
    def clear(self, message: str | None = None) -> None:
        self._sgfile = None
        self._trk = None
        self._cline = None
        self._sampled_centerline = []
        self._sampled_dlongs = []
        self._sampled_bounds = None
        self._centerline_index = None
        self._track_length = None
        self._curve_markers = {}
        self._base_section_endpoints = []
        self._section_endpoints = []
        self._endpoint_overrides.clear()
        self._selected_section_index = None
        self._selected_section_points = []
        self._selected_curve_index = None
        self._transform_state = preview_loader.TransformState()
        self._is_panning = False
        self._last_mouse_pos = None
        self._press_pos = None
        self._state = None
        self._move_mode = False
        self._detached_endpoints.clear()
        self._dragging_section_index = None
        self._dragging_endpoint_type = None
        self._dragging_initial_pos = None
        self._dragging_initial_mouse_pos = None
        self._status_message = message or "Select an SG file to begin."
        self.selectedSectionChanged.emit(None)
        self.update()

    def load_sg_file(self, path: Path) -> None:
        """
        Convenience wrapper used by the app: create an EditorState from a path
        and bind it to this widget.
        """
        if not path:
            self.clear()
            return

        self._status_message = f"Loading {path.name}…"
        self.update()

        state = EditorState.from_path(path)
        self.set_state(state)

        # Expose the state for the main window (SGViewerWindow)
        self._state = state

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

    # ------------------------------------------------------------------
    # Move-point mode (Phase 1 only: detach & drag endpoints visually)
    # ------------------------------------------------------------------
    def set_move_mode(self, enabled: bool) -> None:
        """
        Enable/disable Move Point mode.

        When enabled:
          - Right-click on an endpoint toggles it as "detached".
          - Left-click+drag on a detached endpoint moves it visually.
        No geometry fitting is done yet (Phase 1 only).
        """
        self._move_mode = bool(enabled)
        self._dragging_section_index = None
        self._dragging_endpoint_type = None
        self._dragging_initial_pos = None
        self._dragging_initial_mouse_pos = None
        # Clear overrides when turning off move mode
        if not self._move_mode:
            self._endpoint_overrides.clear()
            self._update_section_endpoints_from_overrides()
        self.update()

    def _update_section_endpoints_from_overrides(self) -> None:
        """
        Rebuild self._section_endpoints from base endpoints plus overrides.
        """
        self._section_endpoints = []
        for idx, (start, end) in enumerate(self._base_section_endpoints):
            s = self._endpoint_overrides.get((idx, "start"), start)
            e = self._endpoint_overrides.get((idx, "end"), end)
            self._section_endpoints.append((s, e))

    def _pick_endpoint(
        self, track_point: Point, pixel_tolerance: float = 8.0
    ) -> Optional[Tuple[int, str, Point]]:
        """
        Find the nearest endpoint to the given track-space point.

        Returns (section_index, "start"/"end", endpoint_point) or None.
        """
        if not self._section_endpoints:
            return None

        transform = self._current_transform()
        if not transform:
            return None
        scale, _ = transform
        if scale <= 0:
            return None

        # convert pixel tolerance to track units
        tol_units = pixel_tolerance / scale
        tol_sq = tol_units * tol_units

        best: Optional[Tuple[int, str, Point]] = None
        best_dist_sq = float("inf")

        tx, ty = track_point
        for idx, (start, end) in enumerate(self._section_endpoints):
            for etype, pt in (("start", start), ("end", end)):
                dx = pt[0] - tx
                dy = pt[1] - ty
                d2 = dx * dx + dy * dy
                if d2 < best_dist_sq:
                    best_dist_sq = d2
                    best = (idx, etype, pt)

        if best is None:
            return None

        if best_dist_sq > tol_sq:
            return None
        return best

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
    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_fit_scale()
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
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

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
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

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._move_mode:
            # Move-point mode: right-click toggles detach; left-click may start dragging
            if event.button() == QtCore.Qt.RightButton:
                self._handle_move_mode_right_click(event.pos())
                event.accept()
                return
            if event.button() == QtCore.Qt.LeftButton:
                self._handle_move_mode_left_press(event.pos())
                # handled if dragging started; if not, no panning in move mode
                event.accept()
                return

        # Normal mode: pan + selection
        if event.button() == QtCore.Qt.LeftButton and self._sampled_centerline:
            self._is_panning = True
            self._last_mouse_pos = event.pos()
            self._press_pos = event.pos()
            self._transform_state = replace(self._transform_state, user_transform_active=True)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._move_mode and self._dragging_section_index is not None:
            self._handle_move_mode_drag(event.pos())
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

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._move_mode and event.button() == QtCore.Qt.LeftButton:
            # End dragging in move mode (Phase 1: no fit logic yet)
            if (
                self._dragging_section_index is not None
                and self._dragging_endpoint_type is not None
                and self._state is not None
            ):
                key = (self._dragging_section_index, self._dragging_endpoint_type)
                override = self._endpoint_overrides.get(key)
                if override is not None:
                    x, y = override
                    self._state.commit_endpoint_move(
                        self._dragging_section_index,
                        self._dragging_endpoint_type,
                        x,
                        y,
                    )
                    self._endpoint_overrides.pop(key, None)
                    self.refresh_from_state()
            self._dragging_section_index = None
            self._dragging_endpoint_type = None
            self._dragging_initial_pos = None
            self._dragging_initial_mouse_pos = None
            event.accept()
            return

        if event.button() == QtCore.Qt.LeftButton:
            self._is_panning = False
            self._last_mouse_pos = None
            if (
                self._press_pos is not None
                and (event.pos() - self._press_pos).manhattanLength() < 6
            ):
                # Small movement → treat as click (selection)
                self._handle_click(event.pos())
            self._press_pos = None
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------------
    # Move-point mode helpers
    # ------------------------------------------------------------------
    def _handle_move_mode_right_click(self, pos: QtCore.QPoint) -> None:
        """Right-click: toggle detached state on nearest endpoint."""
        track_point = self._map_to_track(QtCore.QPointF(pos))
        if track_point is None:
            return
        picked = self._pick_endpoint(track_point)
        if picked is None:
            return
        idx, etype, _ = picked
        key = (idx, etype)
        if key in self._detached_endpoints:
            self._detached_endpoints.remove(key)
        else:
            self._detached_endpoints.add(key)
        self.update()

    def _handle_move_mode_left_press(self, pos: QtCore.QPoint) -> None:
        """Left press in move mode: if on a detached endpoint, start dragging."""
        track_point = self._map_to_track(QtCore.QPointF(pos))
        if track_point is None:
            return
        picked = self._pick_endpoint(track_point)
        if picked is None:
            return
        idx, etype, pt = picked
        key = (idx, etype)
        if key not in self._detached_endpoints:
            # Only allow dragging detached endpoints (SGE behavior)
            return

        self._dragging_section_index = idx
        self._dragging_endpoint_type = etype
        self._dragging_initial_pos = pt
        self._dragging_initial_mouse_pos = pos

    def _handle_move_mode_drag(self, pos: QtCore.QPoint) -> None:
        """While dragging a detached endpoint, update its override position."""
        if self._dragging_section_index is None or self._dragging_endpoint_type is None:
            return
        track_point = self._map_to_track(QtCore.QPointF(pos))
        if track_point is None:
            return

        key = (self._dragging_section_index, self._dragging_endpoint_type)
        self._endpoint_overrides[key] = track_point
        self._update_section_endpoints_from_overrides()
        self.update()

    # ------------------------------------------------------------------
    # Selection (normal mode)
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

        selection_index = self._find_section_by_dlong(nearest_dlong)
        self._set_selected_section(selection_index)

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
        self._selected_curve_index = index if getattr(sect, "type", 1) == 2 else None

        end_dlong = float(sect.start_dlong + sect.length)
        if self._track_length:
            end_dlong = end_dlong % self._track_length

        start_heading, end_heading = self._get_heading_vectors(index)
        type_name = "Curve" if getattr(sect, "type", 1) == 2 else "Straight"
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

    # ------------------------------------------------------------------
    # Metadata / analysis helpers
    # ------------------------------------------------------------------
    def get_section_geometries(self) -> List[SectionGeometry]:
        if self._trk is None or not self._cline or self._track_length is None:
            return []

        track_length = float(self._track_length)
        if track_length <= 0:
            return []

        sections: List[SectionGeometry] = []
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

    def get_section_headings(self) -> List[SectionHeadingData]:
        if self._sgfile is None or self._trk is None:
            return []

        start_vectors: List[Tuple[float, float] | None] = []
        end_vectors: List[Tuple[float, float] | None] = []
        for sect in self._sgfile.sects:
            start = (float(sect.sang1), float(sect.sang2))
            end = (float(sect.eang1), float(sect.eang2))
            start_vectors.append(self._round_heading_vector(start))
            end_vectors.append(self._round_heading_vector(end))

        headings: List[SectionHeadingData] = []
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

    def get_xsect_metadata(self) -> List[Tuple[int, float]]:
        if self._sgfile is None:
            return []
        return [(idx, float(dlat)) for idx, dlat in enumerate(self._sgfile.xsect_dlats)]

    def get_section_range(self, index: int) -> Tuple[float, float] | None:
        if self._trk is None or index < 0 or index >= len(self._trk.sects):
            return None
        start = float(self._trk.sects[index].start_dlong)
        end = start + float(self._trk.sects[index].length)
        return start, end

    def _get_heading_vectors(
        self, index: int
    ) -> Tuple[Tuple[float, float] | None, Tuple[float, float] | None]:
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
            start = (float(sg_sect.sang1), float(sg_sect.sang2))
            end = (float(sg_sect.eang1), float(sg_sect.eang2))
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

    def build_elevation_profile(
        self, xsect_index: int, samples_per_section: int = 24
    ) -> ElevationProfileData | None:
        if (
            self._sgfile is None
            or self._trk is None
            or self._track_length is None
            or xsect_index < 0
            or xsect_index >= self._sgfile.num_xsects
        ):
            return None

        dlongs: List[float] = []
        sg_altitudes: List[float] = []
        trk_altitudes: List[float] = []
        section_ranges: List[Tuple[float, float]] = []

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

    # ------------------------------------------------------------------
    # Small helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _round_sg_value(value: float) -> float:
        """Round SG-derived values to match the raw file precision."""
        return float(round(value))

    @staticmethod
    def _normalize_heading_vector(
        vector: Tuple[float, float] | None,
    ) -> Tuple[float, float] | None:
        if vector is None:
            return None

        length = (vector[0] * vector[0] + vector[1] * vector[1]) ** 0.5
        if length <= 0:
            return None

        return (vector[0] / length, vector[1] / length)

    def _round_heading_vector(
        self, vector: Tuple[float, float] | None
    ) -> Tuple[float, float] | None:
        normalized = self._normalize_heading_vector(vector)
        if normalized is None:
            return None

        return (round(normalized[0], 5), round(normalized[1], 5))

    def _heading_delta(
        self, end: Tuple[float, float] | None, next_start: Tuple[float, float] | None
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
    ) -> Tuple[Tuple[float, float], Tuple[float, float], Tuple[float, float]] | None:
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
