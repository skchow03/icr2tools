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
from sg_viewer import preview_loader_service, preview_state
from sg_viewer import rendering_service, selection
from sg_viewer.sg_geometry import rebuild_centerline_from_sections, update_section_geometry
from sg_viewer.sg_model import SectionPreview

Point = Tuple[float, float]
Transform = tuple[float, tuple[float, float]]


class SGPreviewWidget(QtWidgets.QWidget):
    """Minimal preview widget that draws an SG file centreline."""

    selectedSectionChanged = QtCore.pyqtSignal(object)
    sectionsChanged = QtCore.pyqtSignal()  # NEW

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

        self._sections: list[SectionPreview] = []
        self._section_endpoints: list[tuple[Point, Point]] = []
        self._start_finish_mapping: tuple[Point, Point, Point] | None = None

        self._track_length: float | None = None

        self._section_signatures: list[tuple] = []

        self._transform_state = preview_state.TransformState()
        self._is_panning = False
        self._last_mouse_pos: QtCore.QPoint | None = None
        self._press_pos: QtCore.QPoint | None = None
        self._is_dragging_node = False
        self._active_node: tuple[int, str] | None = None

        self._selection = selection.SelectionManager()
        self._selection.selectionChanged.connect(self._on_selection_changed)

        self._show_curve_markers = True

        self._node_status = {}   # (index, "start"|"end") -> "green" or "orange"
        self._disconnected_nodes: set[tuple[int, str]] = set()
        self._node_radius_px = 6


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
        self._section_endpoints = []
        self._sections = []
        self._section_signatures = []
        self._start_finish_mapping = None
        self._disconnected_nodes.clear()
        self._transform_state = preview_state.TransformState()
        self._is_panning = False
        self._last_mouse_pos = None
        self._press_pos = None
        self._status_message = message or "Select an SG file to begin."
        self._selection.reset([], None, None, [])
        self._update_node_status()
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

        data = preview_loader_service.load_preview(path)

        self._sgfile = data.sgfile
        self._trk = data.trk
        self._cline = data.cline
        self._sampled_centerline = data.sampled_centerline
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
        self._transform_state = preview_state.TransformState()
        self._status_message = data.status_message
        self._selection.reset(
            self._sections,
            self._track_length,
            self._centerline_index,
            self._sampled_dlongs,
        )
        self._update_node_status()
        self._update_fit_scale()
        self.update()

    # ------------------------------------------------------------------
    # Transform helpers
    # ------------------------------------------------------------------
    def _default_center(self) -> Point | None:
        return preview_state.default_center(self._sampled_bounds)

    def _update_fit_scale(self) -> None:
        self._transform_state = preview_state.update_fit_scale(
            self._transform_state,
            self._sampled_bounds,
            (self.width(), self.height()),
            self._default_center(),
        )

    def _current_transform(self) -> Transform | None:
        transform, updated_state = preview_state.current_transform(
            self._transform_state,
            self._sampled_bounds,
            (self.width(), self.height()),
            self._default_center(),
        )
        if updated_state is not self._transform_state:
            self._transform_state = updated_state
        return transform

    def _clamp_scale(self, scale: float) -> float:
        return preview_state.clamp_scale(scale, self._transform_state)

    def _map_to_track(self, point: QtCore.QPointF) -> Point | None:
        transform = self._current_transform()
        return preview_state.map_to_track(transform, (point.x(), point.y()), self.height())

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

    def _can_drag_section_node(self, section: SectionPreview) -> bool:
        return (
            section.type_name == "straight"
            and self._is_invalid_id(section.previous_id)
            and self._is_invalid_id(section.next_id)
        )



    # ------------------------------------------------------------------
    # Qt events
    # ------------------------------------------------------------------
    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # noqa: D401
        super().resizeEvent(event)
        self._update_fit_scale()
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: D401
        """Paint the preview + our node overlay that uses _node_status directly."""
        painter = QtGui.QPainter(self)

        # Get the current transform once, reuse it
        transform = self._current_transform()

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
# ---------------------------------------------------------
# NEW: Node disconnect only if that section is selected
# ---------------------------------------------------------
        if event.button() == QtCore.Qt.LeftButton:
            selected_section = self._selection.selected_section_index
            hit = self._hit_test_node(event.pos(), selected_section)
            print("DEBUG hit =", hit)
            if hit is not None:

                sect_index, endtype = hit

                # Must select section first
                if selected_section is None or selected_section != sect_index:
                    return

                sect = self._sections[sect_index]

                # ---------------------------------------------------------
                # Node dragging for isolated straight sections
                # ---------------------------------------------------------
                if self._can_drag_section_node(sect):
                    self._start_node_drag(hit, event.pos())
                    event.accept()
                    return

                # -----------------------------------------
                # Break logical prev/next connectivity only
                # -----------------------------------------

                if endtype == "start":
                    # Break backward link
                    prev_id = sect.previous_id

                    # Update this section
                    sect = replace(sect, previous_id=-1)
                    self._sections[sect_index] = sect

                    # Update the previous section (break its forward link)
                    if 0 <= prev_id < len(self._sections):
                        prev_sect = self._sections[prev_id]
                        prev_sect = replace(prev_sect, next_id=-1)
                        self._sections[prev_id] = prev_sect

                else:  # end node clicked
                    # Break forward link
                    next_id = sect.next_id

                    # Update this section
                    sect = replace(sect, next_id=-1)
                    self._sections[sect_index] = sect

                    # Update the next section (break its backward link)
                    if 0 <= next_id < len(self._sections):
                        next_sect = self._sections[next_id]
                        next_sect = replace(next_sect, previous_id=-1)
                        self._sections[next_id] = next_sect

                                # -----------------------------------------
                # Geometry rebuild WITHOUT nudging
                # -----------------------------------------
                points, dlongs, bounds, index = rebuild_centerline_from_sections(self._sections)
                self._centerline_polylines = [s.polyline for s in self._sections]
                self._sampled_centerline = points
                self._sampled_dlongs = dlongs
                self._sampled_bounds = bounds
                self._centerline_index = index

                self._update_node_status()

                # Update selection context only
                self._selection.update_context(
                    self._sections,
                    self._track_length,
                    self._centerline_index,
                    self._sampled_dlongs,
                )

                print("DEBUG node_status (after click):", self._node_status.get((sect_index, endtype)))

                # optional: you can drop this if you don't need table refresh
                # self.sectionsChanged.emit()

                self.update()
                event.accept()
                return



        # ---------------------------------------------------------
        # END NEW BLOCK
        # ---------------------------------------------------------

        # ---------------------------------------------------------
        # 2. EXISTING: Begin panning behavior
        # ---------------------------------------------------------
        if (
            event.button() == QtCore.Qt.LeftButton
            and self._sampled_centerline
            and not self._is_dragging_node
        ):
            self._is_panning = True
            self._last_mouse_pos = event.pos()
            self._press_pos = event.pos()
            self._transform_state = replace(self._transform_state, user_transform_active=True)
            event.accept()
            return

        super().mousePressEvent(event)


    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401
        if self._is_dragging_node and self._active_node is not None:
            self._update_drag_position(event.pos())
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
            if self._is_dragging_node:
                self._end_node_drag()
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
        self._selection.handle_click(pos, self._map_to_track, self._current_transform())

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
            self._update_fit_scale()

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

    def _hit_test_node(
        self, pos: QtCore.QPoint, preferred_index: int | None
    ) -> tuple[int, str] | None:
        transform = self._current_transform()
        if transform is None:
            return None

        scale, offsets = transform
        ox, oy = offsets
        widget_height = self.height()
        radius = self._node_radius_px
        r2 = radius * radius

        px = pos.x()
        py = pos.y()

        nodes = list(self._build_node_positions().items())
        if preferred_index is not None:
            preferred_nodes = [n for n in nodes if n[0][0] == preferred_index]
            other_nodes = [n for n in nodes if n[0][0] != preferred_index]
            nodes = preferred_nodes + other_nodes

        for (i, endtype), (x, y) in nodes:
            # match renderer behavior exactly
            node_px = ox + x * scale
            node_py = widget_height - (oy + y * scale)

            dx = px - node_px
            dy = py - node_py
            if dx*dx + dy*dy <= r2:
                return (i, endtype)

        return None

    def _start_node_drag(self, node: tuple[int, str], pos: QtCore.QPoint) -> None:
        track_point = self._map_to_track(QtCore.QPointF(pos))
        if track_point is None:
            return
        self._active_node = node
        self._is_dragging_node = True
        self._is_panning = False
        self._press_pos = None
        self._last_mouse_pos = None
        self._update_dragged_section(track_point)

    def _end_node_drag(self) -> None:
        self._is_dragging_node = False
        self._active_node = None

    def _update_drag_position(self, pos: QtCore.QPoint) -> None:
        track_point = self._map_to_track(QtCore.QPointF(pos))
        if track_point is None or self._active_node is None:
            return
        self._update_dragged_section(track_point)

    def _update_dragged_section(self, track_point: Point) -> None:
        if self._active_node is None or not self._sections:
            return

        sect_index, endtype = self._active_node
        if sect_index < 0 or sect_index >= len(self._sections):
            return

        sect = self._sections[sect_index]
        if not self._can_drag_section_node(sect):
            return

        start = sect.start
        end = sect.end
        if endtype == "start":
            start = track_point
        else:
            end = track_point

        length = math.hypot(end[0] - start[0], end[1] - start[1])
        updated_section = replace(sect, start=start, end=end, length=length)

        sections = list(self._sections)
        sections[sect_index] = updated_section

        # Rebuild geometry for the modified section and refresh centreline data
        sections[sect_index] = update_section_geometry(sections[sect_index])
        self._sections = sections
        self._section_signatures = [self._section_signature(s) for s in sections]
        self._section_endpoints = [(s.start, s.end) for s in sections]

        points, dlongs, bounds, index = rebuild_centerline_from_sections(self._sections)
        self._centerline_polylines = [s.polyline for s in self._sections]
        self._sampled_centerline = points
        self._sampled_dlongs = dlongs
        self._sampled_bounds = bounds
        self._centerline_index = index

        self._selection.update_context(
            self._sections,
            self._track_length,
            self._centerline_index,
            self._sampled_dlongs,
        )
        self.update()


