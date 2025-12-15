from __future__ import annotations

import logging
import math
from dataclasses import replace
from pathlib import Path
from typing import List, Tuple

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

from icr2_core.trk.sg_classes import SGFile
from icr2_core.trk.trk_classes import TRKFile
from icr2_core.trk.trk_utils import get_alt
from track_viewer.geometry import CenterlineIndex, project_point_to_centerline
from sg_viewer.elevation_profile import ElevationProfileData
from sg_viewer import preview_state, preview_transform
from sg_viewer import preview_painter, selection
from sg_viewer.preview_background import PreviewBackground
from sg_viewer.preview_editor import PreviewEditor
from sg_viewer.preview_interaction import PreviewInteraction
from sg_viewer.preview_interactions_create import PreviewCreationAdapter
from sg_viewer.preview_state_controller import PreviewStateController
from sg_viewer.preview_state_utils import (
    compute_section_signatures,
    is_disconnected_endpoint,
    section_signature,
    update_node_status,
)
from sg_viewer.sg_geometry import (
    rebuild_centerline_from_sections,
    update_section_geometry,
)
from sg_viewer.curve_solver import _solve_curve_drag as _solve_curve_drag_util
from sg_viewer.sg_model import SectionPreview

logger = logging.getLogger(__name__)

Point = Tuple[float, float]
Transform = tuple[float, tuple[float, float]]


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

        self._background = PreviewBackground()

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
        self._creation_interactions = PreviewCreationAdapter(self)
        self._editor = PreviewEditor(
            self._controller,
            self._selection,
            self._creation_interactions.straight,
            self._creation_interactions.curve,
        )

        self._show_curve_markers = True

        self._node_status = {}   # (index, "start"|"end") -> "green" or "orange"
        self._disconnected_nodes: set[tuple[int, str]] = set()
        self._node_radius_px = 6
        self._straight_creation = self._creation_interactions.straight
        self._curve_creation = self._creation_interactions.curve
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
    def _new_straight_active(self) -> bool:
        return self._straight_creation.active

    @_new_straight_active.setter
    def _new_straight_active(self, value: bool) -> None:
        self._straight_creation.active = value

    @property
    def _new_straight_start(self) -> Point | None:
        return self._straight_creation.start

    @_new_straight_start.setter
    def _new_straight_start(self, value: Point | None) -> None:
        self._straight_creation.start = value

    @property
    def _new_straight_end(self) -> Point | None:
        return self._straight_creation.end

    @_new_straight_end.setter
    def _new_straight_end(self, value: Point | None) -> None:
        self._straight_creation.end = value

    @property
    def _new_straight_heading(self) -> tuple[float, float] | None:
        return self._straight_creation.heading

    @_new_straight_heading.setter
    def _new_straight_heading(self, value: tuple[float, float] | None) -> None:
        self._straight_creation.heading = value

    @property
    def _new_straight_connection(self) -> tuple[int, str] | None:
        return self._straight_creation.connection

    @_new_straight_connection.setter
    def _new_straight_connection(self, value: tuple[int, str] | None) -> None:
        self._straight_creation.connection = value

    @property
    def _new_curve_active(self) -> bool:
        return self._curve_creation.active

    @_new_curve_active.setter
    def _new_curve_active(self, value: bool) -> None:
        self._curve_creation.active = value

    @property
    def _new_curve_start(self) -> Point | None:
        return self._curve_creation.start

    @_new_curve_start.setter
    def _new_curve_start(self, value: Point | None) -> None:
        self._curve_creation.start = value

    @property
    def _new_curve_end(self) -> Point | None:
        return self._curve_creation.end

    @_new_curve_end.setter
    def _new_curve_end(self, value: Point | None) -> None:
        self._curve_creation.end = value

    @property
    def _new_curve_heading(self) -> tuple[float, float] | None:
        return self._curve_creation.heading

    @_new_curve_heading.setter
    def _new_curve_heading(self, value: tuple[float, float] | None) -> None:
        self._curve_creation.heading = value

    @property
    def _new_curve_preview(self) -> SectionPreview | None:
        return self._curve_creation.preview

    @_new_curve_preview.setter
    def _new_curve_preview(self, value: SectionPreview | None) -> None:
        self._curve_creation.preview = value

    @property
    def _new_curve_connection(self) -> tuple[int, str] | None:
        return self._curve_creation.connection

    @_new_curve_connection.setter
    def _new_curve_connection(self, value: tuple[int, str] | None) -> None:
        self._curve_creation.connection = value

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

    @property
    def _delete_section_active(self) -> bool:
        return self._editor.delete_section_active

    def _update_fit_scale(self) -> None:
        new_state = preview_transform.update_fit_scale(
            self._transform_state,
            self._sampled_bounds,
            (self.width(), self.height()),
        )
        self._transform_state = new_state


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
        self._creation_interactions.reset()
        self._editor.reset()
        self._set_new_straight_active(False)
        self._set_new_curve_active(False)
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
        self._sampled_bounds = preview_transform.default_bounds()

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
        self._sampled_bounds = preview_transform.active_bounds(
            data.sampled_bounds, self._background.bounds()
        )
        self._centerline_index = data.centerline_index
        self._track_length = data.track_length
        self._sections = data.sections
        self._section_signatures = compute_section_signatures(data.sections)
        self._section_endpoints = data.section_endpoints
        self._start_finish_mapping = data.start_finish_mapping
        self._disconnected_nodes = set()
        self._creation_interactions.reset()
        self._set_new_straight_active(False)
        self._set_new_curve_active(False)
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
        self._background.load_image(path)
        self._fit_view_to_background()
        self.update()

    def clear_background_image(self) -> None:
        self._background.clear()
        self.update()

    # ------------------------------------------------------------------
    # New straight creation
    # ------------------------------------------------------------------
    def begin_new_straight(self) -> bool:
        return self._straight_creation.begin()

    def begin_new_curve(self) -> bool:
        return self._curve_creation.begin()

    def _finalize_new_straight(self) -> None:
        updated_sections, track_length, new_index, status = self._editor.finalize_new_straight(
            self._sections, self._track_length
        )
        if new_index is None:
            return

        self._track_length = track_length
        self.set_sections(updated_sections)
        self._selection.set_selected_section(new_index)
        self._set_new_straight_active(False)
        self._new_straight_start = None
        self._new_straight_end = None
        self._new_straight_heading = None
        self._new_straight_connection = None
        if status:
            self._status_message = status

    def _finalize_new_curve(self) -> None:
        updated_sections, track_length, new_index, status = self._editor.finalize_new_curve(
            self._sections, self._track_length
        )
        if new_index is None:
            return

        self._track_length = track_length
        self.set_sections(updated_sections)
        self._selection.set_selected_section(new_index)
        self._set_new_curve_active(False)
        self._new_curve_start = None
        self._new_curve_end = None
        self._new_curve_heading = None
        self._new_curve_preview = None
        self._new_curve_connection = None
        if status:
            self._status_message = status

    def _next_section_start_dlong(self) -> float:
        return self._editor.next_section_start_dlong(self._sections)

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
        if active:
            changed = self._editor.begin_delete_section(self._sections)
        else:
            changed = self._editor.cancel_delete_section()

        if not changed:
            return

        if active:
            self._set_new_straight_active(False)
            self._set_new_curve_active(False)
        self.deleteModeChanged.emit(active)

    def set_background_settings(
        self, scale_500ths_per_px: float, origin: Point
    ) -> None:
        self._background.scale_500ths_per_px = scale_500ths_per_px
        self._background.origin = origin
        self._fit_view_to_background()
        self.update()

    def get_background_settings(self) -> tuple[float, Point]:
        return self._background.scale_500ths_per_px, self._background.origin

    def _background_bounds(self) -> tuple[float, float, float, float] | None:
        return self._background.bounds()

    def _combine_bounds_with_background(
        self, bounds: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        return preview_transform.active_bounds(bounds, self._background.bounds())

    def _fit_view_to_background(self) -> None:
        result = self._background.fit_view(
            self._sampled_bounds, (self.width(), self.height())
        )
        if result is None:
            return

        fit_scale, center, active_bounds = result
        self._sampled_bounds = active_bounds
        self._transform_state = replace(
            self._transform_state,
            fit_scale=fit_scale,
            current_scale=fit_scale,
            view_center=center,
            user_transform_active=False,
        )

    def get_background_image_path(self) -> Path | None:
        return self._background.image_path

    def has_background_image(self) -> bool:
        return self._background.image is not None

    def _update_node_status(self) -> None:
        """Update cached node colors directly from section connectivity."""
        update_node_status(self._sections, self._node_status)

    def _build_node_positions(self):
        pos = {}
        for i, sect in enumerate(self._sections):
            pos[(i, "start")] = sect.start
            pos[(i, "end")] = sect.end
        return pos

    def _can_drag_section_node(self, section: SectionPreview) -> bool:
        return self._editor.can_drag_section_node(self._sections, section)

    def _can_drag_section_polyline(self, section: SectionPreview, index: int | None = None) -> bool:
        return self._editor.can_drag_section_polyline(self._sections, section, index)

    def _connected_neighbor_index(self, index: int, direction: str) -> int | None:
        return self._editor.connected_neighbor_index(self._sections, index, direction)

    def _get_drag_chain(self, index: int | None) -> list[int] | None:
        return self._editor.get_drag_chain(self._sections, index)

    def _can_drag_node(self, section: SectionPreview, endtype: str) -> bool:
        return self._editor.can_drag_node(self._sections, section, endtype)



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

        preview_painter.paint_preview(
            painter,
            preview_painter.BasePreviewState(
                rect=self.rect(),
                background_color=self.palette().color(QtGui.QPalette.Window),
                background_image=self._background.image,
                background_scale_500ths_per_px=self._background.scale_500ths_per_px,
                background_origin=self._background.origin,
                sampled_centerline=self._sampled_centerline,
                centerline_polylines=self._centerline_polylines,
                selected_section_points=self._selection.selected_section_points,
                section_endpoints=self._section_endpoints,
                selected_section_index=self._selection.selected_section_index,
                show_curve_markers=self._show_curve_markers,
                sections=self._sections,
                selected_curve_index=self._selection.selected_curve_index,
                start_finish_mapping=self._start_finish_mapping,
                status_message=self._status_message,
            ),
            preview_painter.CreationOverlayState(
                new_straight_active=self._new_straight_active,
                new_straight_start=self._new_straight_start,
                new_straight_end=self._new_straight_end,
                new_curve_active=self._new_curve_active,
                new_curve_start=self._new_curve_start,
                new_curve_end=self._new_curve_end,
                new_curve_preview=self._new_curve_preview,
            ),
            transform,
            self.height(),
        )

        # If we have no transform yet (no track), we’re done
        if transform is None:
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
        widget_size = (self.width(), self.height())
        transform = self._controller.current_transform(widget_size)
        if transform is None:
            return
        state = self._transform_state
        if state.current_scale is None:
            return

        delta = event.angleDelta().y()
        factor = 1.15 if delta > 0 else 1 / 1.15
        new_scale = self._controller.clamp_scale(state.current_scale * factor)
        center = state.view_center or self._controller.default_center()
        cursor_track = self._controller.map_to_track(
            event.pos(), widget_size, self.height(), transform
        )
        if cursor_track is None:
            cursor_track = center
        if center is None or cursor_track is None:
            return
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
        if self._creation_interactions.handle_mouse_press(event):
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
        if self._creation_interactions.is_active():
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
            and self._controller.current_transform((self.width(), self.height())) is not None
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
        if self._creation_interactions.handle_mouse_move(event.pos()):
            event.accept()
            return

        if self._creation_interactions.is_active():
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
            if self._creation_interactions.is_active():
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
                if not is_disconnected_endpoint(self._sections, section, endtype):
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
        new_sections, track_length, status = self._editor.delete_section(
            list(self._sections), index
        )
        if not status:
            return

        self._track_length = track_length
        self.set_sections(new_sections)
        self._selection.set_selected_section(None)
        self._status_message = status
        self._set_delete_section_active(False)

    def get_section_set(self) -> tuple[list[SectionPreview], float | None]:
        track_length = float(self._track_length) if self._track_length is not None else None
        return list(self._sections), track_length

    def set_sections(self, sections: list[SectionPreview]) -> None:
        previous_signatures = self._section_signatures

        new_sections: list[SectionPreview] = []
        new_signatures: list[tuple] = []
        changed_indices: list[int] = []

        for idx, sect in enumerate(sections):
            signature = section_signature(sect)
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


