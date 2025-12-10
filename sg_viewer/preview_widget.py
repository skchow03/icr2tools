from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path
from typing import List, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets

from icr2_core.trk.sg_classes import SGFile
from icr2_core.trk.trk_classes import TRKFile
from icr2_core.trk.trk_utils import get_alt
from track_viewer.geometry import CenterlineIndex, project_point_to_centerline
from sg_viewer.elevation_profile import ElevationProfileData
from sg_viewer import preview_state
from sg_viewer import rendering_service, selection
from sg_viewer.preview_state_controller import PreviewStateController
from sg_viewer.preview_interaction import PreviewInteraction
from sg_viewer.sg_geometry import rebuild_centerline_from_sections, update_section_geometry
from sg_viewer.sg_model import SectionPreview

Point = Tuple[float, float]
Transform = tuple[float, tuple[float, float]]


class SGPreviewWidget(QtWidgets.QWidget):
    """Minimal preview widget that draws an SG file centreline."""

    selectedSectionChanged = QtCore.pyqtSignal(object)
    sectionsChanged = QtCore.pyqtSignal()  # NEW

    CURVE_SOLVE_TOLERANCE = 1.0  # inches

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(640, 480)
        self.setMouseTracking(True)

        palette = self.palette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor("black"))
        self.setPalette(palette)

        self._controller = PreviewStateController()

        self._cline: List[Point] | None = None
        self._centerline_polylines: list[list[Point]] = []
        self._sampled_dlongs: List[float] = []
        self._centerline_index: CenterlineIndex | None = None

        self._sections: list[SectionPreview] = []
        self._section_endpoints: list[tuple[Point, Point]] = []
        self._start_finish_mapping: tuple[Point, Point, Point] | None = None

        self._section_signatures: list[tuple] = []

        self._is_panning = False
        self._last_mouse_pos: QtCore.QPoint | None = None
        self._press_pos: QtCore.QPoint | None = None
        self._selection = selection.SelectionManager()
        self._selection.selectionChanged.connect(self._on_selection_changed)

        self._interaction = PreviewInteraction(self, self._controller, self._selection)

        self._show_curve_markers = True

        self._node_status = {}   # (index, "start"|"end") -> "green" or "orange"
        self._disconnected_nodes: set[tuple[int, str]] = set()
        self._node_radius_px = 6

    # ------------------------------------------------------------------
    # State delegation
    # ------------------------------------------------------------------
    @property
    def _sgfile(self) -> SGFile | None:
        return self._controller.sgfile

    @_sgfile.setter
    def _sgfile(self, value: SGFile | None) -> None:
        self._controller.sgfile = value

    @property
    def _trk(self) -> TRKFile | None:
        return self._controller.trk

    @_trk.setter
    def _trk(self, value: TRKFile | None) -> None:
        self._controller.trk = value

    @property
    def _sampled_centerline(self) -> list[Point]:
        return self._controller.sampled_centerline

    @_sampled_centerline.setter
    def _sampled_centerline(self, value: list[Point]) -> None:
        self._controller.sampled_centerline = value

    @property
    def _sampled_bounds(self) -> tuple[float, float, float, float] | None:
        return self._controller.sampled_bounds

    @_sampled_bounds.setter
    def _sampled_bounds(self, value: tuple[float, float, float, float] | None) -> None:
        self._controller.sampled_bounds = value

    @property
    def _track_length(self) -> float | None:
        return self._controller.track_length

    @_track_length.setter
    def _track_length(self, value: float | None) -> None:
        self._controller.track_length = value

    @property
    def _status_message(self) -> str:
        return self._controller.status_message

    @_status_message.setter
    def _status_message(self, value: str) -> None:
        self._controller.status_message = value

    @property
    def _transform_state(self) -> preview_state.TransformState:
        return self._controller.transform_state

    @_transform_state.setter
    def _transform_state(self, value: preview_state.TransformState) -> None:
        self._controller.transform_state = value


    def clear(self, message: str | None = None) -> None:
        self._controller.clear(message)
        self._cline = None
        self._centerline_polylines = []
        self._sampled_dlongs = []
        self._centerline_index = None
        self._section_endpoints = []
        self._sections = []
        self._section_signatures = []
        self._start_finish_mapping = None
        self._disconnected_nodes.clear()
        self._is_panning = False
        self._last_mouse_pos = None
        self._press_pos = None
        self._interaction.reset()
        self._status_message = message or "Select an SG file to begin."
        self._selection.reset([], None, None, [])
        self._update_node_status()
        self.update()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def load_sg_file(self, path: Path) -> None:
        data = self._controller.load_sg_file(path)
        if data is None:
            self.clear()
            return

        self._cline = data.cline
        self._centerline_polylines = [list(data.sampled_centerline)] if data.sampled_centerline else []
        self._sampled_dlongs = data.sampled_dlongs
        self._sampled_bounds = data.sampled_bounds
        self._centerline_index = data.centerline_index
        self._track_length = data.track_length
        self._sections = data.sections
        self._section_signatures = [self._section_signature(sect) for sect in data.sections]
        self._section_endpoints = data.section_endpoints
        self._start_finish_mapping = data.start_finish_mapping
        self._disconnected_nodes = set()
        self._status_message = data.status_message
        self._selection.reset(
            self._sections,
            self._track_length,
            self._centerline_index,
            self._sampled_dlongs,
        )
        self._update_node_status()
        self._controller.update_fit_scale((self.width(), self.height()))
        self.update()

    def _update_node_status(self) -> None:
        """
        Determine node colors directly from section connectivity.
        A node is green if it has a valid neighbor via prev_id or next_id.
        A node is orange if that endpoint is not connected to another section.
        """
        self._node_status.clear()

        sections = self._sections
        if not sections:
            return

        total = len(sections)

        for i, sect in enumerate(sections):
            # Start node color
            if sect.previous_id is None or sect.previous_id < 0 or sect.previous_id >= total:
                self._node_status[(i, "start")] = "orange"
            else:
                self._node_status[(i, "start")] = "green"

            # End node color
            if sect.next_id is None or sect.next_id < 0 or sect.next_id >= total:
                self._node_status[(i, "end")] = "orange"
            else:
                self._node_status[(i, "end")] = "green"

    def _build_node_positions(self):
        pos = {}
        for i, sect in enumerate(self._sections):
            pos[(i, "start")] = sect.start
            pos[(i, "end")] = sect.end
        return pos

    def _is_invalid_id(self, value: int | None) -> bool:
        return value is None or value < 0 or value >= len(self._sections)

    def _is_disconnected_endpoint(self, section: SectionPreview, endtype: str) -> bool:
        if endtype == "start":
            return self._is_invalid_id(section.previous_id)
        return self._is_invalid_id(section.next_id)

    def _can_drag_section_node(self, section: SectionPreview) -> bool:
        return (
            section.type_name == "straight"
            and self._is_invalid_id(section.previous_id)
            and self._is_invalid_id(section.next_id)
        )

    def _can_drag_section_polyline(self, section: SectionPreview) -> bool:
        if section.type_name == "curve":
            return True
        return self._can_drag_section_node(section)

    def _can_drag_node(self, section: SectionPreview, endtype: str) -> bool:
        if section.type_name == "straight":
            return self._can_drag_section_node(section) or self._is_disconnected_endpoint(
                section, endtype
            )
        if section.type_name == "curve":
            return self._is_disconnected_endpoint(section, endtype)
        return False



    # ------------------------------------------------------------------
    # Qt events
    # ------------------------------------------------------------------
    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # noqa: D401
        super().resizeEvent(event)
        self._controller.update_fit_scale((self.width(), self.height()))
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: D401
        """Paint the preview + our node overlay that uses _node_status directly."""
        painter = QtGui.QPainter(self)

        # Get the current transform once, reuse it
        transform = self._controller.current_transform((self.width(), self.height()))

        # Let the rendering service draw everything (track, endpoints, etc.)
        rendering_service.paint_preview(
            painter,
            self.rect(),
            self.palette().color(QtGui.QPalette.Window),
            self._sampled_centerline,
            self._centerline_polylines,
            self._selection.selected_section_points,
            None,
            self._selection.selected_section_index,
            self._show_curve_markers,
            self._sections,
            self._selection.selected_curve_index,
            self._start_finish_mapping,
            transform,
            self.height(),
            self._status_message,
        )

        # If we have no transform yet (no track), we’re done
        if transform is None or not self._sections:
            return

        # ---------------------------------------------------------
        # NEW NODE DRAWING BLOCK
        # ---------------------------------------------------------

        scale, offsets = transform
        ox, oy = offsets
        widget_height = self.height()

        # First draw all green nodes
        for (i, endtype), (x, y) in self._build_node_positions().items():
            status = self._node_status.get((i, endtype), "green")
            if status == "orange":
                continue  # skip oranges, draw them later on top

            # compute screen coords
            px = ox + x * scale
            py_world = oy + y * scale
            py = widget_height - py_world

            painter.setBrush(QtGui.QColor("limegreen"))   # green
            painter.setPen(QtCore.Qt.NoPen)
            painter.drawEllipse(QtCore.QPointF(px, py), 6, 6)


        # Then draw all ORANGE nodes on top (larger + outline)
        for (i, endtype), (x, y) in self._build_node_positions().items():
            status = self._node_status.get((i, endtype), "green")
            if status != "orange":
                continue

            # compute screen coords
            px = ox + x * scale
            py_world = oy + y * scale
            py = widget_height - py_world

            painter.setBrush(QtGui.QColor("orange"))   # orange
            painter.setPen(QtCore.Qt.NoPen)
            painter.drawEllipse(QtCore.QPointF(px, py), 6, 6)



    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:  # noqa: D401
        if not self._sampled_centerline:
            return
        widget_size = (self.width(), self.height())
        transform = self._controller.current_transform(widget_size)
        if transform is None:
            return
        state = self._transform_state
        if state.view_center is None:
            center = self._controller.default_center()
            if center is None:
                return
            state = replace(state, view_center=center)
            self._transform_state = state
        if state.current_scale is None or state.view_center is None:
            return

        delta = event.angleDelta().y()
        factor = 1.15 if delta > 0 else 1 / 1.15
        new_scale = self._controller.clamp_scale(state.current_scale * factor)
        cursor_track = self._controller.map_to_track(event.pos(), widget_size, self.height())
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
# ---------------------------------------------------------
# NEW: Node disconnect only if that section is selected
# ---------------------------------------------------------
        if self._interaction.handle_mouse_press(event):
            return

        # ---------------------------------------------------------
        # 2. EXISTING: Begin panning behavior
        # ---------------------------------------------------------
        if (
            event.button() == QtCore.Qt.LeftButton
            and self._sampled_centerline
            and not self._interaction.is_dragging_node
            and not self._interaction.is_dragging_section
        ):
            self._is_panning = True
            self._last_mouse_pos = event.pos()
            self._press_pos = event.pos()
            self._transform_state = replace(self._transform_state, user_transform_active=True)
            event.accept()
            return

        super().mousePressEvent(event)


    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401
        if self._interaction.handle_mouse_move(event):
            return

        if self._is_panning and self._last_mouse_pos is not None:
            widget_size = (self.width(), self.height())
            transform = self._controller.current_transform(widget_size)
            if transform:
                state = self._transform_state
                center = state.view_center or self._controller.default_center()
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
            if self._interaction.handle_mouse_release(event):
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
        widget_size = (self.width(), self.height())
        transform = self._controller.current_transform(widget_size)
        self._selection.handle_click(
            pos,
            lambda p: self._controller.map_to_track(p, widget_size, self.height(), transform),
            transform,
        )

    def _on_selection_changed(self, selection_value: object) -> None:
        self.selectedSectionChanged.emit(selection_value)
        self.update()

    def get_section_set(self) -> tuple[list[SectionPreview], float | None]:
        track_length = float(self._track_length) if self._track_length is not None else None
        return list(self._sections), track_length

    @staticmethod
    def _section_signature(section: SectionPreview) -> tuple:
        return (
            section.section_id,
            section.type_name,
            section.previous_id,
            section.next_id,
            section.start,
            section.end,
            section.start_dlong,
            section.length,
            section.center,
            section.sang1,
            section.sang2,
            section.eang1,
            section.eang2,
            section.radius,
        )

    def set_sections(self, sections: list[SectionPreview]) -> None:
        previous_signatures = self._section_signatures

        new_sections: list[SectionPreview] = []
        new_signatures: list[tuple] = []
        changed_indices: list[int] = []

        for idx, sect in enumerate(sections):
            signature = self._section_signature(sect)
            new_signatures.append(signature)
            prev_signature = previous_signatures[idx] if idx < len(previous_signatures) else None

            if (
                prev_signature is not None
                and prev_signature == signature
                and idx < len(self._sections)
            ):
                new_sections.append(self._sections[idx])
            else:
                new_sections.append(update_section_geometry(sect))
                changed_indices.append(idx)

        length_changed = len(sections) != len(self._sections)
        needs_rebuild = length_changed or bool(changed_indices)

        self._sections = new_sections
        self._section_signatures = new_signatures
        self._section_endpoints = [(sect.start, sect.end) for sect in self._sections]

        if needs_rebuild:
            points, dlongs, bounds, index = rebuild_centerline_from_sections(self._sections)
            self._centerline_polylines = [sect.polyline for sect in self._sections]
            self._sampled_centerline = points
            self._sampled_dlongs = dlongs
            self._sampled_bounds = bounds
            self._centerline_index = index
            self._controller.update_fit_scale((self.width(), self.height()))

        self._update_node_status()


        self._selection.update_context(
            self._sections,
            self._track_length,
            self._centerline_index,
            self._sampled_dlongs,
        )
        self.sectionsChanged.emit()  # NEW
        self.update()

    def get_section_headings(self) -> list[selection.SectionHeadingData]:
        return self._selection.get_section_headings()

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

    # ------------------------------------------------------------------
    # Public controls
    # ------------------------------------------------------------------
    def set_show_curve_markers(self, visible: bool) -> None:
        self._show_curve_markers = visible
        self.update()

    def select_next_section(self) -> None:
        if not self._selection.sections:
            return

        if self._selection.selected_section_index is None:
            self._selection.set_selected_section(0)
            return

        next_index = (self._selection.selected_section_index + 1) % len(self._selection.sections)
        self._selection.set_selected_section(next_index)

    def select_previous_section(self) -> None:
        if not self._selection.sections:
            return

        if self._selection.selected_section_index is None:
            self._selection.set_selected_section(len(self._selection.sections) - 1)
            return

        prev_index = (self._selection.selected_section_index - 1) % len(self._selection.sections)
        self._selection.set_selected_section(prev_index)

    def _solve_curve_drag(
        self, sect: SectionPreview, start: Point, end: Point
    ) -> SectionPreview | None:
        if start == end:
            return None

        cx_hint, cy_hint = sect.center if sect.center is not None else (start[0], start[1])
        orientation_hint = self._curve_orientation_hint(sect)

        best_section: SectionPreview | None = None
        best_score = float("inf")

        heading_preserving_candidates: list[SectionPreview] = []

        moved_start = start != sect.start
        moved_end = end != sect.end
        if moved_start and not moved_end and sect.end_heading is not None:
            heading_preserving_candidates = self._solve_curve_with_fixed_heading(
                sect,
                start,
                end,
                fixed_point=end,
                fixed_heading=sect.end_heading,
                fixed_point_is_start=False,
                orientation_hint=orientation_hint,
            )
        elif moved_end and not moved_start and sect.start_heading is not None:
            heading_preserving_candidates = self._solve_curve_with_fixed_heading(
                sect,
                start,
                end,
                fixed_point=start,
                fixed_heading=sect.start_heading,
                fixed_point_is_start=True,
                orientation_hint=orientation_hint,
            )

        for candidate in heading_preserving_candidates:
            score = self._compute_curve_solution_metric(
                candidate.center if candidate.center is not None else (cx_hint, cy_hint),
                candidate.radius if candidate.radius is not None else 0.0,
                candidate.start_heading,
                candidate.end_heading,
                sect,
            )
            if score < best_score:
                best_score = score
                best_section = candidate

        if best_section is not None:
            return best_section

        vx = end[0] - start[0]
        vy = end[1] - start[1]
        chord_length = math.hypot(vx, vy)
        if chord_length <= 1e-6:
            return None

        half_chord = chord_length / 2.0
        mid = (start[0] + vx * 0.5, start[1] + vy * 0.5)
        normal = (-vy / chord_length, vx / chord_length)

        offset_from_center = (cx_hint - mid[0]) * normal[0] + (cy_hint - mid[1]) * normal[1]
        offset_sign = 1.0 if offset_from_center >= 0 else -1.0
        if offset_sign == 0.0:
            offset_sign = orientation_hint

        radius_target = sect.radius if sect.radius and sect.radius > 0 else None
        offset_for_radius = None
        if radius_target is not None and radius_target > half_chord:
            offset_for_radius = math.sqrt(max(radius_target * radius_target - half_chord * half_chord, 0.0))
            offset_for_radius *= offset_sign

        preferred_offset = offset_sign * max(abs(offset_from_center), self.CURVE_SOLVE_TOLERANCE)

        offset_candidates = []
        if offset_for_radius is not None:
            offset_candidates.append(offset_for_radius)
        offset_candidates.append(preferred_offset)
        if offset_for_radius is not None:
            blended = (offset_for_radius + preferred_offset) / 2.0
            offset_candidates.append(blended)

        for offset in offset_candidates:
            if offset == 0:
                continue

            center = (mid[0] + normal[0] * offset, mid[1] + normal[1] * offset)
            radius = math.hypot(start[0] - center[0], start[1] - center[1])
            if radius <= half_chord:
                continue

            orientation = 1.0 if offset > 0 else -1.0
            start_heading = self._curve_tangent_heading(center, start, orientation)
            end_heading = self._curve_tangent_heading(center, end, orientation)

            arc_length = self._curve_arc_length(center, start, end, radius)
            if arc_length is None:
                continue

            score = self._compute_curve_solution_metric(
                center,
                radius,
                start_heading,
                end_heading,
                sect,
            )

            if score < best_score:
                best_score = score
                best_section = replace(
                    sect,
                    start=start,
                    end=end,
                    center=center,
                    radius=radius,
                    sang1=start_heading[0] if start_heading else None,
                    sang2=start_heading[1] if start_heading else None,
                    eang1=end_heading[0] if end_heading else None,
                    eang2=end_heading[1] if end_heading else None,
                    start_heading=start_heading,
                    end_heading=end_heading,
                    length=arc_length,
                )

        return best_section

    def _solve_curve_with_fixed_heading(
        self,
        sect: SectionPreview,
        start: Point,
        end: Point,
        fixed_point: Point,
        fixed_heading: tuple[float, float],
        fixed_point_is_start: bool,
        orientation_hint: float,
    ) -> list[SectionPreview]:
        hx, hy = fixed_heading
        heading_length = math.hypot(hx, hy)
        if heading_length <= 1e-9:
            return []

        hx /= heading_length
        hy /= heading_length

        moving_point = end if fixed_point_is_start else start
        fx, fy = fixed_point
        dx = moving_point[0] - fx
        dy = moving_point[1] - fy

        candidates: list[SectionPreview] = []

        for orientation in {orientation_hint, -orientation_hint}:
            normal = (-orientation * hy, orientation * hx)
            dot = dx * normal[0] + dy * normal[1]
            if abs(dot) <= 1e-9:
                continue

            radius = (dx * dx + dy * dy) / (2.0 * dot)
            if radius <= 0:
                continue

            center = (fx + normal[0] * radius, fy + normal[1] * radius)
            start_heading = self._curve_tangent_heading(center, start, orientation)
            end_heading = self._curve_tangent_heading(center, end, orientation)

            if start_heading is None or end_heading is None:
                continue

            arc_length = self._curve_arc_length(center, start, end, radius)
            if arc_length is None:
                continue

            candidates.append(
                replace(
                    sect,
                    start=start,
                    end=end,
                    center=center,
                    radius=radius,
                    sang1=start_heading[0],
                    sang2=start_heading[1],
                    eang1=end_heading[0],
                    eang2=end_heading[1],
                    start_heading=start_heading,
                    end_heading=end_heading,
                    length=arc_length,
                )
            )

        return candidates

    @staticmethod
    def _curve_orientation_hint(section: SectionPreview) -> float:
        if section.center is not None:
            sx, sy = section.start
            ex, ey = section.end
            cx, cy = section.center
            start_vec = (sx - cx, sy - cy)
            end_vec = (ex - cx, ey - cy)
            cross = start_vec[0] * end_vec[1] - start_vec[1] * end_vec[0]
            if abs(cross) > 1e-9:
                return 1.0 if cross > 0 else -1.0

        if section.start_heading is not None and section.end_heading is not None:
            sx, sy = section.start_heading
            ex, ey = section.end_heading
            cross = sx * ey - sy * ex
            if abs(cross) > 1e-9:
                return 1.0 if cross > 0 else -1.0

        return 1.0

    def _compute_curve_solution_metric(
        self,
        center: Point,
        radius: float,
        start_heading: tuple[float, float] | None,
        end_heading: tuple[float, float] | None,
        sect: SectionPreview,
    ) -> float:
        center_penalty = 0.0
        if sect.center is not None:
            cx, cy = sect.center
            center_penalty = math.hypot(center[0] - cx, center[1] - cy) * 0.01

        radius_penalty = 0.0
        if sect.radius is not None and sect.radius > 0:
            radius_delta = abs(radius - sect.radius)
            radius_penalty = max(0.0, radius_delta - self.CURVE_SOLVE_TOLERANCE) * 0.05

        heading_penalty = 0.0
        heading_penalty += self._curve_heading_penalty(sect.start_heading, start_heading)
        heading_penalty += self._curve_heading_penalty(sect.end_heading, end_heading)

        return heading_penalty * 2.0 + radius_penalty + center_penalty

    @staticmethod
    def _curve_heading_penalty(
        original: tuple[float, float] | None, candidate: tuple[float, float] | None
    ) -> float:
        if original is None or candidate is None:
            return 0.0
        dot = SGPreviewWidget._clamp_unit(original[0] * candidate[0] + original[1] * candidate[1])
        return math.acos(dot)

    @staticmethod
    def _curve_tangent_heading(
        center: Point, point: Point, orientation: float
    ) -> tuple[float, float] | None:
        vx = point[0] - center[0]
        vy = point[1] - center[1]
        radius = math.hypot(vx, vy)
        if radius <= 0:
            return None
        tx = orientation * (-vy / radius)
        ty = orientation * (vx / radius)
        return (tx, ty)

    @staticmethod
    def _clamp_unit(value: float) -> float:
        return max(-1.0, min(1.0, value))

    @staticmethod
    def _curve_arc_length(
        center: Point, start: Point, end: Point, radius: float
    ) -> float | None:
        sx = start[0] - center[0]
        sy = start[1] - center[1]
        ex = end[0] - center[0]
        ey = end[1] - center[1]

        dot = SGPreviewWidget._clamp_unit((sx * ex + sy * ey) / max(radius * radius, 1e-9))
        cross = sx * ey - sy * ex
        angle = abs(math.atan2(cross, dot))
        if angle <= 0:
            return None
        return radius * angle

    @staticmethod
    def _distance_to_polyline(point: Point, polyline: list[Point]) -> float:
        if len(polyline) < 2:
            return float("inf")

        px, py = point
        min_dist_sq = float("inf")

        for (x1, y1), (x2, y2) in zip(polyline, polyline[1:]):
            dx = x2 - x1
            dy = y2 - y1
            if dx == dy == 0:
                continue
            t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
            t = max(0.0, min(1.0, t))
            proj_x = x1 + t * dx
            proj_y = y1 + t * dy
            dist_sq = (px - proj_x) ** 2 + (py - proj_y) ** 2
            if dist_sq < min_dist_sq:
                min_dist_sq = dist_sq

        return math.sqrt(min_dist_sq)


