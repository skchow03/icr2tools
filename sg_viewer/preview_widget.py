from __future__ import annotations

import math
from dataclasses import replace
import logging
from pathlib import Path
from typing import List, Tuple

import numpy as np
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
from sg_viewer.sg_geometry import (
    rebuild_centerline_from_sections,
    signed_radius_from_heading,
    update_section_geometry,
)
from sg_viewer.curve_solver import (
    _solve_curve_drag as _solve_curve_drag_util,
    _solve_curve_with_fixed_heading,
)
from sg_viewer.sg_model import SectionPreview

logger = logging.getLogger(__name__)

Point = Tuple[float, float]
Transform = tuple[float, tuple[float, float]]

MILE_IN_500THS = 63_360 * 500
DEFAULT_VIEW_HALF_SPAN_500THS = MILE_IN_500THS  # 1 mile to either side = 2 miles wide


def _curve_angles(
    start: tuple[float, float],
    end: tuple[float, float],
    center: tuple[float, float],
    radius: float,
) -> tuple[float, float, float, float]:
    """Compute SG curve angles based on geometry.

    The values match the SG format expectations:
    Sang1 = Center_Y - Start_Y
    Sang2 = Start_X - Center_X
    Eang1 = Center_Y - End_Y
    Eang2 = End_X - Center_X

    Each component is multiplied by the sign of ``radius`` (positive when the
    curve bends left, negative when it bends right).
    """

    cx, cy = center
    sx, sy = start
    ex, ey = end
    sign = 1 if radius >= 0 else -1

    sang1 = (cy - sy) * sign
    sang2 = (sx - cx) * sign
    eang1 = (cy - ey) * sign
    eang2 = (ex - cx) * sign

    return sang1, sang2, eang1, eang2


class SGPreviewWidget(QtWidgets.QWidget):
    """Minimal preview widget that draws an SG file centreline."""

    selectedSectionChanged = QtCore.pyqtSignal(object)
    sectionsChanged = QtCore.pyqtSignal()  # NEW
    newStraightModeChanged = QtCore.pyqtSignal(bool)
    newCurveModeChanged = QtCore.pyqtSignal(bool)
    deleteModeChanged = QtCore.pyqtSignal(bool)
    scaleChanged = QtCore.pyqtSignal(float)

    CURVE_SOLVE_TOLERANCE = 1.0  # inches

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(640, 480)
        self.setMouseTracking(True)

        palette = self.palette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor("black"))
        self.setPalette(palette)

        self._controller = PreviewStateController()

        self._background_image: QtGui.QImage | None = None
        self._background_image_path: Path | None = None
        self._background_scale_500ths_per_px: float = 1.0
        self._background_origin: Point = (0.0, 0.0)

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
        self._new_straight_active = False
        self._new_straight_start: Point | None = None
        self._new_straight_end: Point | None = None
        self._new_straight_heading: tuple[float, float] | None = None
        self._new_straight_connection: tuple[int, str] | None = None
        self._new_curve_active = False
        self._new_curve_start: Point | None = None
        self._new_curve_end: Point | None = None
        self._new_curve_heading: tuple[float, float] | None = None
        self._new_curve_preview: SectionPreview | None = None
        self._new_curve_connection: tuple[int, str] | None = None
        self._delete_section_active = False
        self._has_unsaved_changes = False

        self._set_default_view_bounds()

    @staticmethod
    def _create_empty_sgfile() -> SGFile:
        header = np.zeros(6, dtype=np.int32)
        xsect_dlats = np.array([-300_000, 300_000], dtype=np.int32)
        num_xsects = len(xsect_dlats)
        header[5] = num_xsects
        return SGFile(header, 0, num_xsects, xsect_dlats, [])

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
    def sgfile(self) -> SGFile | None:
        return self._controller.sgfile

    @property
    def has_unsaved_changes(self) -> bool:
        return self._has_unsaved_changes

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
        previous = self._controller.transform_state
        self._controller.transform_state = value
        if (
            value.current_scale is not None
            and value.current_scale != previous.current_scale
        ):
            self.scaleChanged.emit(value.current_scale)

    def _update_fit_scale(self) -> None:
        previous = self._transform_state
        new_state = self._controller.update_fit_scale((self.width(), self.height()))
        if (
            new_state.current_scale is not None
            and new_state.current_scale != previous.current_scale
        ):
            self.scaleChanged.emit(new_state.current_scale)


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
        self._new_straight_active = False
        self._new_straight_start = None
        self._new_straight_end = None
        self._new_curve_active = False
        self._new_curve_start = None
        self._new_curve_end = None
        self._new_curve_preview = None
        self._delete_section_active = False
        self._is_panning = False
        self._last_mouse_pos = None
        self._press_pos = None
        self._interaction.reset()
        self._status_message = message or "Select an SG file to begin."
        self._selection.reset([], None, None, [])
        self._set_default_view_bounds()
        self._update_node_status()
        self._has_unsaved_changes = False
        self._update_fit_scale()
        self.update()

    def _set_default_view_bounds(self) -> None:
        half_span = DEFAULT_VIEW_HALF_SPAN_500THS
        default_bounds = (
            -float(half_span),
            float(half_span),
            -float(half_span),
            float(half_span),
        )
        self._sampled_bounds = default_bounds

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def load_sg_file(self, path: Path) -> None:
        data = self._controller.load_sg_file(path)
        if data is None:
            self.clear()
            return

        self._cline = data.cline
        self._centerline_polylines = [sect.polyline for sect in data.sections]
        self._sampled_dlongs = data.sampled_dlongs
        self._sampled_bounds = data.sampled_bounds
        self._centerline_index = data.centerline_index
        self._track_length = data.track_length
        self._sections = data.sections
        self._section_signatures = [self._section_signature(sect) for sect in data.sections]
        self._section_endpoints = data.section_endpoints
        self._start_finish_mapping = data.start_finish_mapping
        self._disconnected_nodes = set()
        self._set_new_straight_active(False)
        self._new_straight_start = None
        self._new_straight_end = None
        self._new_straight_heading = None
        self._set_new_curve_active(False)
        self._new_curve_start = None
        self._new_curve_end = None
        self._new_curve_heading = None
        self._new_curve_preview = None
        self._status_message = data.status_message
        self._selection.reset(
            self._sections,
            self._track_length,
            self._centerline_index,
            self._sampled_dlongs,
        )
        self._update_node_status()
        self._update_fit_scale()
        self._has_unsaved_changes = False
        self.update()

    def start_new_track(self) -> None:
        self.clear("New track ready. Click New Straight to start drawing.")
        self._sgfile = self._create_empty_sgfile()
        self._set_default_view_bounds()
        self._sampled_centerline = []
        self._track_length = 0.0
        self._has_unsaved_changes = False
        self._update_fit_scale()
        self.update()

    def load_background_image(self, path: Path) -> None:
        image = QtGui.QImage(str(path))
        if image.isNull():
            raise ValueError(f"Unable to load image from {path}")

        self._background_image = image
        self._background_image_path = path
        self._fit_view_to_background()
        self.update()

    def clear_background_image(self) -> None:
        self._background_image = None
        self._background_image_path = None
        self._background_scale_500ths_per_px = 1.0
        self._background_origin = (0.0, 0.0)
        self.update()

    # ------------------------------------------------------------------
    # New straight creation
    # ------------------------------------------------------------------
    def begin_new_straight(self) -> bool:
        if not self._sampled_bounds:
            return False

        self._set_new_straight_active(True)
        self._new_straight_start = None
        self._new_straight_end = None
        self._new_straight_heading = None
        self._new_straight_connection = None
        self._status_message = "Click to place the start of the new straight."
        self.update()
        return True

    def begin_new_curve(self) -> bool:
        if not self._sampled_bounds:
            return False

        self._set_new_curve_active(True)
        self._new_curve_start = None
        self._new_curve_end = None
        self._new_curve_heading = None
        self._new_curve_preview = None
        self._new_curve_connection = None
        self._status_message = "Click an unconnected node to start the new curve."
        self.update()
        return True

    def _finalize_new_straight(self, end_point: Point) -> None:
        if not self._new_straight_active or self._new_straight_start is None:
            return

        start_point = self._new_straight_start
        end_point = self._apply_heading_constraint(start_point, end_point)
        length = math.hypot(end_point[0] - start_point[0], end_point[1] - start_point[1])
        next_start_dlong = self._next_section_start_dlong()
        new_index = len(self._sections)

        new_section = SectionPreview(
            section_id=new_index,
            type_name="straight",
            previous_id=-1,
            next_id=-1,
            start=start_point,
            end=end_point,
            start_dlong=next_start_dlong,
            length=length,
            center=None,
            sang1=None,
            sang2=None,
            eang1=None,
            eang2=None,
            radius=None,
            start_heading=self._new_straight_heading,
            end_heading=self._new_straight_heading,
            polyline=[start_point, end_point],
        )

        updated_sections = list(self._sections)
        updated_sections, new_section = self._connect_new_section(
            updated_sections, new_section, self._new_straight_connection
        )
        updated_sections.append(update_section_geometry(new_section))
        new_track_length = next_start_dlong + length
        if self._track_length is not None:
            self._track_length = max(self._track_length, new_track_length)
        else:
            self._track_length = new_track_length

        self.set_sections(updated_sections)
        self._selection.set_selected_section(new_index)
        self._set_new_straight_active(False)
        self._new_straight_start = None
        self._new_straight_end = None
        self._new_straight_heading = None
        self._new_straight_connection = None
        self._status_message = f"Added new straight #{new_index}."

    def _finalize_new_curve(self) -> None:
        if (
            not self._new_curve_active
            or self._new_curve_start is None
            or self._new_curve_preview is None
        ):
            return

        new_section = self._new_curve_preview
        new_index = len(self._sections)
        next_start_dlong = self._next_section_start_dlong()
        new_section = replace(new_section, section_id=new_index, start_dlong=next_start_dlong)

        updated_sections = list(self._sections)
        updated_sections, new_section = self._connect_new_section(
            updated_sections, new_section, self._new_curve_connection
        )
        updated_sections.append(update_section_geometry(new_section))
        new_track_length = next_start_dlong + new_section.length
        if self._track_length is not None:
            self._track_length = max(self._track_length, new_track_length)
        else:
            self._track_length = new_track_length

        self.set_sections(updated_sections)
        self._selection.set_selected_section(new_index)
        self._set_new_curve_active(False)
        self._new_curve_start = None
        self._new_curve_end = None
        self._new_curve_heading = None
        self._new_curve_preview = None
        self._new_curve_connection = None
        self._status_message = f"Added new curve #{new_index}."

    def _next_section_start_dlong(self) -> float:
        if not self._sections:
            return 0.0

        last = self._sections[-1]
        return float(last.start_dlong + last.length)

    # ------------------------------------------------------------------
    # Delete section
    # ------------------------------------------------------------------
    def begin_delete_section(self) -> bool:
        if not self._sections:
            return False

        self._set_delete_section_active(True)
        self._status_message = "Click a section to delete it."
        self.update()
        return True

    def cancel_delete_section(self) -> None:
        self._set_delete_section_active(False)

    def _set_delete_section_active(self, active: bool) -> None:
        if self._delete_section_active == active:
            return

        self._delete_section_active = active
        if active:
            self._set_new_straight_active(False)
            self._set_new_curve_active(False)
        self.deleteModeChanged.emit(active)

    def set_background_settings(
        self, scale_500ths_per_px: float, origin: Point
    ) -> None:
        self._background_scale_500ths_per_px = scale_500ths_per_px
        self._background_origin = origin
        self._fit_view_to_background()
        self.update()

    def get_background_settings(self) -> tuple[float, Point]:
        return self._background_scale_500ths_per_px, self._background_origin

    def _background_bounds(self) -> tuple[float, float, float, float] | None:
        if self._background_image is None:
            return None

        scale = self._background_scale_500ths_per_px
        if scale <= 0:
            return None

        origin_x, origin_y = self._background_origin
        return (
            origin_x,
            origin_x + self._background_image.width() * scale,
            origin_y,
            origin_y + self._background_image.height() * scale,
        )

    def _combine_bounds_with_background(
        self, bounds: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        background_bounds = self._background_bounds()
        if background_bounds is None:
            return bounds

        min_x = min(bounds[0], background_bounds[0])
        max_x = max(bounds[1], background_bounds[1])
        min_y = min(bounds[2], background_bounds[2])
        max_y = max(bounds[3], background_bounds[3])
        return (min_x, max_x, min_y, max_y)

    def _fit_view_to_background(self) -> None:
        background_bounds = self._background_bounds()
        if background_bounds is None:
            return

        active_bounds = background_bounds
        if self._sampled_bounds:
            active_bounds = self._combine_bounds_with_background(self._sampled_bounds)

        self._sampled_bounds = active_bounds

        fit_scale = preview_state.calculate_fit_scale(
            active_bounds, (self.width(), self.height())
        )
        if fit_scale is None:
            return

        center = (
            (active_bounds[0] + active_bounds[1]) / 2,
            (active_bounds[2] + active_bounds[3]) / 2,
        )
        self._transform_state = replace(
            self._transform_state,
            fit_scale=fit_scale,
            current_scale=fit_scale,
            view_center=center,
            user_transform_active=False,
        )

    def get_background_image_path(self) -> Path | None:
        return self._background_image_path

    def has_background_image(self) -> bool:
        return self._background_image is not None

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

    def _can_drag_section_polyline(self, section: SectionPreview, index: int | None = None) -> bool:
        chain = self._get_drag_chain(index) if index is not None else None
        if chain is not None:
            return True

        if section.type_name == "curve":
            return self._is_invalid_id(section.previous_id) and self._is_invalid_id(
                section.next_id
            )
        return self._can_drag_section_node(section)

    def _connected_neighbor_index(self, index: int, direction: str) -> int | None:
        if index < 0 or index >= len(self._sections):
            return None

        section = self._sections[index]
        neighbor_index = section.previous_id if direction == "previous" else section.next_id
        if self._is_invalid_id(neighbor_index):
            return None

        neighbor = self._sections[neighbor_index]
        if direction == "previous" and neighbor.next_id != index:
            return None
        if direction == "next" and neighbor.previous_id != index:
            return None

        return neighbor_index

    def _get_drag_chain(self, index: int | None) -> list[int] | None:
        if index is None or index < 0 or index >= len(self._sections):
            return None

        chain: list[int] = [index]
        visited = {index}

        prev_idx = self._connected_neighbor_index(index, "previous")
        while prev_idx is not None and prev_idx not in visited:
            chain.insert(0, prev_idx)
            visited.add(prev_idx)
            prev_idx = self._connected_neighbor_index(prev_idx, "previous")
        head_closed_loop = prev_idx == index

        next_idx = self._connected_neighbor_index(index, "next")
        while next_idx is not None and next_idx not in visited:
            chain.append(next_idx)
            visited.add(next_idx)
            next_idx = self._connected_neighbor_index(next_idx, "next")
        tail_closed_loop = next_idx == chain[0] or next_idx == index

        if not chain:
            return None

        head = self._sections[chain[0]]
        tail = self._sections[chain[-1]]
        head_open = self._is_invalid_id(head.previous_id)
        tail_open = self._is_invalid_id(tail.next_id)

        closed_loop = (
            not head_open
            and not tail_open
            and self._connected_neighbor_index(chain[0], "previous") == chain[-1]
            and self._connected_neighbor_index(chain[-1], "next") == chain[0]
            and (head_closed_loop or tail_closed_loop)
        )

        if not closed_loop and not (head_open and tail_open):
            return None

        return chain

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
        self._update_fit_scale()
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
            self._background_image,
            self._background_scale_500ths_per_px,
            self._background_origin,
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
        if transform is None:
            return

        if self._new_straight_active and self._new_straight_start is not None:
            start = self._new_straight_start
            end = self._new_straight_end or self._new_straight_start
            scale, offsets = transform
            ox, oy = offsets
            widget_height = self.height()

            start_point = QtCore.QPointF(
                ox + start[0] * scale, widget_height - (oy + start[1] * scale)
            )
            end_point = QtCore.QPointF(
                ox + end[0] * scale, widget_height - (oy + end[1] * scale)
            )

            painter.save()
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
            painter.setPen(QtGui.QPen(QtGui.QColor("cyan"), 2))
            painter.drawLine(start_point, end_point)
            painter.setBrush(QtGui.QColor("cyan"))
            painter.setPen(QtCore.Qt.NoPen)
            painter.drawEllipse(start_point, 5, 5)
            painter.drawEllipse(end_point, 5, 5)
            painter.restore()

        if self._new_curve_active and self._new_curve_start is not None:
            preview_section = self._new_curve_preview
            scale, offsets = transform
            ox, oy = offsets
            widget_height = self.height()

            if preview_section and preview_section.polyline:
                polyline_points = preview_section.polyline
            else:
                end_point = self._new_curve_end or self._new_curve_start
                polyline_points = [self._new_curve_start, end_point]

            painter.save()
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
            painter.setPen(QtGui.QPen(QtGui.QColor("magenta"), 2))
            qp_points = [
                QtCore.QPointF(ox + x * scale, widget_height - (oy + y * scale))
                for x, y in polyline_points
            ]
            if len(qp_points) >= 2:
                painter.drawPolyline(QtGui.QPolygonF(qp_points))
            for point in qp_points:
                painter.setBrush(QtGui.QColor("magenta"))
                painter.setPen(QtCore.Qt.NoPen)
                painter.drawEllipse(point, 5, 5)
            painter.restore()

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
        if self._handle_new_curve_press(event):
            return
        if self._handle_new_straight_press(event):
            return

        if self._delete_section_active and event.button() == QtCore.Qt.LeftButton:
            self._is_panning = False
            self._last_mouse_pos = None
            self._press_pos = event.pos()
            event.accept()
            return

# ---------------------------------------------------------
# NEW: Node disconnect only if that section is selected
# ---------------------------------------------------------
        if self._new_straight_active or self._new_curve_active:
            event.accept()
            return

        if self._interaction.handle_mouse_press(event):
            logger.debug("mousePressEvent handled by interaction at %s", event.pos())
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
            logger.debug("mousePressEvent starting pan at %s", event.pos())
            event.accept()
            return

        super().mousePressEvent(event)


    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401
        if self._update_new_curve_position(event.pos()):
            event.accept()
            return
        if self._update_new_straight_position(event.pos()):
            event.accept()
            return

        if self._new_straight_active or self._new_curve_active:
            event.accept()
            return

        if self._delete_section_active:
            event.accept()
            return

        if self._interaction.handle_mouse_move(event):
            logger.debug("mouseMoveEvent handled by interaction at %s", event.pos())
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
            if self._delete_section_active:
                if (
                    self._press_pos is not None
                    and (event.pos() - self._press_pos).manhattanLength() < 6
                ):
                    self._handle_delete_click(event.pos())
                self._press_pos = None
                event.accept()
                return
            if self._new_straight_active or self._new_curve_active:
                event.accept()
                return
            if self._interaction.handle_mouse_release(event):
                logger.debug("mouseReleaseEvent handled by interaction at %s", event.pos())
                return
            self._is_panning = False
            self._last_mouse_pos = None
            if (
                self._press_pos is not None
                and (event.pos() - self._press_pos).manhattanLength() < 6
            ):
                logger.debug(
                    "mouseReleaseEvent treating as click (press=%s, release=%s, delta=%s)",
                    self._press_pos,
                    event.pos(),
                    (event.pos() - self._press_pos).manhattanLength(),
                )
                self._handle_click(event.pos())
            else:
                logger.debug(
                    "mouseReleaseEvent ending pan without click (press=%s, release=%s, delta=%s)",
                    self._press_pos,
                    event.pos(),
                    0 if self._press_pos is None else (event.pos() - self._press_pos).manhattanLength(),
                )
            self._press_pos = None
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------
    def _handle_new_straight_press(self, event: QtGui.QMouseEvent) -> bool:
        if not self._new_straight_active or event.button() != QtCore.Qt.LeftButton:
            return False

        widget_size = (self.width(), self.height())
        transform = self._controller.current_transform(widget_size)
        if transform is None:
            return False

        track_point = self._controller.map_to_track(
            QtCore.QPointF(event.pos()), widget_size, self.height(), transform
        )
        if track_point is None:
            return False

        if self._new_straight_start is None:
            constrained_start = self._unconnected_node_hit(event.pos())
            if constrained_start is not None:
                section_index, endtype, start_point, heading = constrained_start
                self._new_straight_start = start_point
                self._new_straight_end = start_point
                self._new_straight_heading = heading
                self._new_straight_connection = (section_index, endtype)
                self._status_message = (
                    "Extending from unconnected node; move to set the length."
                )
            else:
                self._new_straight_start = track_point
                self._new_straight_end = track_point
                self._new_straight_heading = None
                self._new_straight_connection = None
                self._status_message = (
                    "Move the mouse to position the new straight, then click to finish."
                )
            self._is_panning = False
            self._last_mouse_pos = None
            self._press_pos = None
            self.update()
        else:
            constrained_end = self._apply_heading_constraint(
                self._new_straight_start, track_point
            )
            self._finalize_new_straight(constrained_end)

        event.accept()
        return True

    def _handle_new_curve_press(self, event: QtGui.QMouseEvent) -> bool:
        if not self._new_curve_active or event.button() != QtCore.Qt.LeftButton:
            return False

        widget_size = (self.width(), self.height())
        transform = self._controller.current_transform(widget_size)
        if transform is None:
            return False

        track_point = self._controller.map_to_track(
            QtCore.QPointF(event.pos()), widget_size, self.height(), transform
        )
        if track_point is None:
            return False

        if self._new_curve_start is None:
            constrained_start = self._unconnected_node_hit(event.pos())
            if constrained_start is None:
                self._status_message = (
                    "New curve must start from an unconnected node."
                )
                self.update()
                event.accept()
                return True

            section_index, endtype, start_point, heading = constrained_start
            if heading is None:
                self._status_message = "Selected node does not have a usable heading."
                self.update()
                event.accept()
                return True

            self._new_curve_start = start_point
            self._new_curve_end = start_point
            self._new_curve_heading = heading
            self._new_curve_preview = None
            self._new_curve_connection = (section_index, endtype)
            self._status_message = (
                "Extending curve from unconnected node; move to set the arc."
            )
            self._is_panning = False
            self._last_mouse_pos = None
            self._press_pos = None
            self.update()
        else:
            preview = self._build_new_curve_candidate(track_point)
            if preview is None:
                self._status_message = "Unable to solve a curve for that end point."
                self.update()
            else:
                self._new_curve_preview = preview
                self._new_curve_end = preview.end
                self._finalize_new_curve()

        event.accept()
        return True

    def _update_new_straight_position(self, pos: QtCore.QPoint) -> bool:
        if not self._new_straight_active or self._new_straight_start is None:
            return False

        widget_size = (self.width(), self.height())
        transform = self._controller.current_transform(widget_size)
        if transform is None:
            return False

        track_point = self._controller.map_to_track(
            QtCore.QPointF(pos), widget_size, self.height(), transform
        )
        if track_point is None:
            return False

        constrained_end = self._apply_heading_constraint(
            self._new_straight_start, track_point
        )
        self._new_straight_end = constrained_end
        length = math.hypot(
            constrained_end[0] - self._new_straight_start[0],
            constrained_end[1] - self._new_straight_start[1],
        )
        self._status_message = f"New straight length: {length:.1f} (click to set end)."
        self.update()
        return True

    def _update_new_curve_position(self, pos: QtCore.QPoint) -> bool:
        if not self._new_curve_active or self._new_curve_start is None:
            return False

        widget_size = (self.width(), self.height())
        transform = self._controller.current_transform(widget_size)
        if transform is None:
            return False

        track_point = self._controller.map_to_track(
            QtCore.QPointF(pos), widget_size, self.height(), transform
        )
        if track_point is None:
            return False

        preview = self._build_new_curve_candidate(track_point)
        if preview is None:
            self._status_message = "Unable to solve a curve for that position."
            self.update()
            return True

        self._new_curve_preview = preview
        self._new_curve_end = preview.end
        self._status_message = f"New curve length: {preview.length:.1f} (click to set end)."
        self.update()
        return True

    def _apply_heading_constraint(self, start_point: Point, candidate: Point) -> Point:
        if self._new_straight_heading is None:
            return candidate

        hx, hy = self._new_straight_heading
        vx = candidate[0] - start_point[0]
        vy = candidate[1] - start_point[1]
        projected_length = max(0.0, vx * hx + vy * hy)
        return (start_point[0] + hx * projected_length, start_point[1] + hy * projected_length)

    def _build_new_curve_candidate(self, end_point: Point) -> SectionPreview | None:
        if self._new_curve_start is None or self._new_curve_heading is None:
            return None

        start_point = self._new_curve_start
        heading = self._new_curve_heading
        template = SectionPreview(
            section_id=len(self._sections),
            type_name="curve",
            previous_id=-1,
            next_id=-1,
            start=start_point,
            end=end_point,
            start_dlong=0.0,
            length=0.0,
            center=None,
            sang1=None,
            sang2=None,
            eang1=None,
            eang2=None,
            radius=None,
            start_heading=heading,
            end_heading=None,
            polyline=[start_point, end_point],
        )

        candidates = _solve_curve_with_fixed_heading(
            template,
            start_point,
            end_point,
            fixed_point=start_point,
            fixed_heading=heading,
            fixed_point_is_start=True,
            orientation_hint=1.0,
        )
        if not candidates:
            return None

        best_candidate = min(candidates, key=lambda sect: sect.length)
        signed_radius = signed_radius_from_heading(
            heading, start_point, best_candidate.center, best_candidate.radius
        )
        if signed_radius != best_candidate.radius:
            best_candidate = replace(best_candidate, radius=signed_radius)

        return update_section_geometry(best_candidate)

    def _heading_for_endpoint(
        self, section: SectionPreview, endtype: str
    ) -> tuple[float, float] | None:
        heading = section.start_heading if endtype == "start" else section.end_heading
        if heading is not None:
            hx, hy = heading
        else:
            dx = section.end[0] - section.start[0]
            dy = section.end[1] - section.start[1]
            length = math.hypot(dx, dy)
            if length <= 0:
                return None
            hx, hy = dx / length, dy / length

        if endtype == "start":
            return (-hx, -hy)
        return (hx, hy)

    def _unconnected_node_hit(
        self, pos: QtCore.QPoint
    ) -> tuple[int, str, Point, tuple[float, float] | None] | None:
        widget_size = (self.width(), self.height())
        transform = self._controller.current_transform(widget_size)
        if transform is None:
            return None

        scale, offsets = transform
        ox, oy = offsets
        widget_height = self.height()
        radius = self._node_radius_px
        r2 = radius * radius

        for i, section in enumerate(self._sections):
            for endtype in ("start", "end"):
                if not self._is_disconnected_endpoint(section, endtype):
                    continue

                world_point = section.start if endtype == "start" else section.end
                px = ox + world_point[0] * scale
                py_world = oy + world_point[1] * scale
                py = widget_height - py_world

                dx = px - pos.x()
                dy = py - pos.y()
                if dx * dx + dy * dy <= r2:
                    return i, endtype, world_point, self._heading_for_endpoint(
                        section, endtype
                    )

        return None

    def _connect_new_section(
        self,
        sections: list[SectionPreview],
        new_section: SectionPreview,
        connection: tuple[int, str] | None,
    ) -> tuple[list[SectionPreview], SectionPreview]:
        if connection is None:
            return sections, new_section

        neighbor_index, endtype = connection
        if neighbor_index < 0 or neighbor_index >= len(sections):
            return sections, new_section

        neighbor = sections[neighbor_index]
        if endtype == "end":
            new_section = replace(new_section, previous_id=neighbor_index)
            neighbor = replace(neighbor, next_id=new_section.section_id)
        else:
            new_section = replace(new_section, next_id=neighbor_index)
            neighbor = replace(neighbor, previous_id=new_section.section_id)

        sections[neighbor_index] = neighbor
        return sections, new_section

    def _set_new_straight_active(self, active: bool) -> None:
        if self._new_straight_active == active:
            return

        self._new_straight_active = active
        if active:
            self._set_delete_section_active(False)
        else:
            self._new_straight_connection = None
        self.newStraightModeChanged.emit(active)

    def _set_new_curve_active(self, active: bool) -> None:
        if self._new_curve_active == active:
            return

        self._new_curve_active = active
        if active:
            self._set_delete_section_active(False)
        else:
            self._new_curve_connection = None
        self.newCurveModeChanged.emit(active)

    def _handle_click(self, pos: QtCore.QPoint) -> None:
        if self._delete_section_active and self._handle_delete_click(pos):
            return

        widget_size = (self.width(), self.height())
        transform = self._controller.current_transform(widget_size)
        logger.debug(
            "Handling click at screen %s with widget size %s and transform %s",
            pos,
            widget_size,
            transform,
        )
        self._selection.handle_click(
            pos,
            lambda p: self._controller.map_to_track(p, widget_size, self.height(), transform),
            transform,
        )

    def _on_selection_changed(self, selection_value: object) -> None:
        self.selectedSectionChanged.emit(selection_value)
        self.update()

    def _handle_delete_click(self, pos: QtCore.QPoint) -> bool:
        widget_size = (self.width(), self.height())
        transform = self._controller.current_transform(widget_size)
        if transform is None:
            return False

        selection_index = self._selection.find_section_at_point(
            pos,
            lambda p: self._controller.map_to_track(p, widget_size, self.height(), transform),
            transform,
        )
        if selection_index is None:
            self._status_message = "Click a section to delete it."
            self.update()
            return False

        self._delete_section(selection_index)
        return True

    def _delete_section(self, index: int) -> None:
        if not self._sections or index < 0 or index >= len(self._sections):
            return

        removed_id = self._sections[index].section_id
        removed_targets = {removed_id, index}
        survivors = [sect for idx, sect in enumerate(self._sections) if idx != index]
        id_mapping = {sect.section_id: new_idx for new_idx, sect in enumerate(survivors)}

        new_sections: list[SectionPreview] = []
        cursor = 0.0
        for sect in survivors:
            new_prev = -1
            if sect.previous_id not in (None, -1) and sect.previous_id not in removed_targets:
                new_prev = id_mapping.get(sect.previous_id, -1)

            new_next = -1
            if sect.next_id not in (None, -1) and sect.next_id not in removed_targets:
                new_next = id_mapping.get(sect.next_id, -1)

            new_index = id_mapping.get(sect.section_id, -1)
            updated_section = replace(
                sect,
                section_id=new_index,
                previous_id=new_prev,
                next_id=new_next,
                start_dlong=cursor,
            )
            new_sections.append(update_section_geometry(updated_section))
            cursor += float(updated_section.length)

        self._track_length = cursor if new_sections else None
        self.set_sections(new_sections)
        self._selection.set_selected_section(None)
        self._status_message = f"Deleted section #{index}."
        self._set_delete_section_active(False)

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
            self._sampled_bounds = self._combine_bounds_with_background(bounds)
            self._centerline_index = index
            self._update_fit_scale()

        self._update_node_status()


        self._selection.update_context(
            self._sections,
            self._track_length,
            self._centerline_index,
            self._sampled_dlongs,
        )
        self._has_unsaved_changes = True
        self.sectionsChanged.emit()  # NEW
        self.update()

    def save_sg(self, path: Path) -> None:
        """Write the current SG (and any edits) to ``path``."""

        if self._sgfile is None:
            raise ValueError("No SG file loaded.")

        if not self._sections:
            raise ValueError("No sections available to save.")

        sgfile = self._sgfile

        desired_section_count = len(self._sections)
        current_section_count = len(sgfile.sects)

        if desired_section_count != current_section_count:
            section_record_length = 58 + 2 * sgfile.num_xsects
            if desired_section_count > current_section_count:
                template_section = [0] * section_record_length
                for _ in range(desired_section_count - current_section_count):
                    sgfile.sects.append(
                        SGFile.Section(template_section, sgfile.num_xsects)
                    )
            else:
                sgfile.sects = sgfile.sects[:desired_section_count]

        sgfile.num_sects = desired_section_count
        if len(sgfile.header) > 4:
            sgfile.header[4] = desired_section_count

        def _as_int(value: float | int | None, fallback: int = 0) -> int:
            if value is None:
                return fallback
            return int(round(value))

        for sg_section, preview_section in zip(sgfile.sects, self._sections):
            sg_section.type = 2 if preview_section.type_name == "curve" else 1
            sg_section.sec_prev = _as_int(preview_section.previous_id, -1)
            sg_section.sec_next = _as_int(preview_section.next_id, -1)

            start_x, start_y = preview_section.start
            end_x, end_y = preview_section.end
            sg_section.start_x = _as_int(start_x)
            sg_section.start_y = _as_int(start_y)
            sg_section.end_x = _as_int(end_x)
            sg_section.end_y = _as_int(end_y)

            sg_section.start_dlong = _as_int(preview_section.start_dlong)
            sg_section.length = _as_int(preview_section.length)

            center_x, center_y = preview_section.center or (0.0, 0.0)
            sg_section.center_x = _as_int(center_x)
            sg_section.center_y = _as_int(center_y)

            start_heading = (
                (preview_section.sang1, preview_section.sang2)
                if preview_section.sang1 is not None and preview_section.sang2 is not None
                else preview_section.start_heading
            )
            end_heading = (
                (preview_section.eang1, preview_section.eang2)
                if preview_section.eang1 is not None and preview_section.eang2 is not None
                else preview_section.end_heading
            )

            sang1 = sang2 = eang1 = eang2 = None
            if preview_section.type_name == "curve" and preview_section.center is not None:
                sang1, sang2, eang1, eang2 = _curve_angles(
                    (start_x, start_y),
                    (end_x, end_y),
                    (center_x, center_y),
                    preview_section.radius or 0.0,
                )
            else:
                sang1 = start_heading[0] if start_heading else None
                sang2 = start_heading[1] if start_heading else None
                eang1 = end_heading[0] if end_heading else None
                eang2 = end_heading[1] if end_heading else None

            sg_section.sang1 = _as_int(sang1)
            sg_section.sang2 = _as_int(sang2)
            sg_section.eang1 = _as_int(eang1)
            sg_section.eang2 = _as_int(eang2)

            sg_section.radius = _as_int(preview_section.radius)

        sgfile.output_sg(str(path))
        self._has_unsaved_changes = False

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
        return _solve_curve_drag_util(sect, start, end, self.CURVE_SOLVE_TOLERANCE)

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


