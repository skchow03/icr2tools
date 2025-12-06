from __future__ import annotations

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

        self._selection = selection.SelectionManager()
        self._selection.selectionChanged.connect(self._on_selection_changed)

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
        self._section_endpoints = []
        self._sections = []
        self._section_signatures = []
        self._start_finish_mapping = None
        self._transform_state = preview_state.TransformState()
        self._is_panning = False
        self._last_mouse_pos = None
        self._press_pos = None
        self._status_message = message or "Select an SG file to begin."
        self._selection.reset([], None, None, [])
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
        self._transform_state = preview_state.TransformState()
        self._status_message = data.status_message
        self._selection.reset(
            self._sections,
            self._track_length,
            self._centerline_index,
            self._sampled_dlongs,
        )
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

    # ------------------------------------------------------------------
    # Qt events
    # ------------------------------------------------------------------
    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # noqa: D401
        super().resizeEvent(event)
        self._update_fit_scale()
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: D401
        painter = QtGui.QPainter(self)
        rendering_service.paint_preview(
            painter,
            self.rect(),
            self.palette().color(QtGui.QPalette.Window),
            self._sampled_centerline,
            self._centerline_polylines,
            self._selection.selected_section_points,
            self._section_endpoints,
            self._selection.selected_section_index,
            self._show_curve_markers,
            self._sections,
            self._selection.selected_curve_index,
            self._start_finish_mapping,
            self._current_transform(),
            self.height(),
            self._status_message,
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

        self._selection.update_context(
            self._sections,
            self._track_length,
            self._centerline_index,
            self._sampled_dlongs,
        )
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
