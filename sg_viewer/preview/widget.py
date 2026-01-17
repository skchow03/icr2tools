from __future__ import annotations

import logging
import math
from dataclasses import replace
from pathlib import Path
from typing import Callable, List, Tuple

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

from icr2_core.trk.sg_classes import SGFile
from icr2_core.trk.trk_classes import TRKFile
from icr2_core.trk.trk_utils import get_alt
from track_viewer.geometry import CenterlineIndex, project_point_to_centerline
from sg_viewer.models import preview_state, selection
from sg_viewer.preview.geometry import (
    CURVE_SOLVE_TOLERANCE as CURVE_SOLVE_TOLERANCE_DEFAULT,
    curve_angles,
)
from sg_viewer.preview.render_state import split_nodes_by_status
from sg_viewer.preview.selection import build_node_positions, find_unconnected_node_hit
from sg_viewer.preview.transform import pan_transform_state, zoom_transform_state
from sg_viewer.services import preview_painter
from sg_viewer.services.preview_background import PreviewBackground
from sg_viewer.ui.elevation_profile import ElevationProfileData
from sg_viewer.geometry.centerline_utils import (
    compute_centerline_normal_and_tangent,
    compute_start_finish_mapping_from_centerline,
)
from sg_viewer.geometry.picking import project_point_to_segment
from sg_viewer.geometry.sg_geometry import (
    build_section_polyline,
    derive_heading_vectors,
    scale_section,
    rebuild_centerline_from_sections,
)
from sg_viewer.ui.preview_editor import PreviewEditor
from sg_viewer.preview.creation_controller import CreationController, CreationEvent, CreationEventContext, CreationUpdate
from sg_viewer.ui.preview_interaction import PreviewInteraction
from sg_viewer.ui.preview_state_controller import PreviewStateController
from sg_viewer.ui.preview_section_manager import PreviewSectionManager
from sg_viewer.ui.preview_viewport import PreviewViewport
from sg_viewer.models.preview_state_utils import update_node_status
from sg_viewer.models.sg_model import SectionPreview
from sg_viewer.preview.hover_detection import find_hovered_unconnected_node
from sg_viewer.geometry.dlong import set_start_finish
from sg_viewer.geometry.topology import is_closed_loop, loop_length


logger = logging.getLogger(__name__)

Point = Tuple[float, float]
Transform = tuple[float, tuple[float, float]]


def _project_point_to_polyline(point: Point, polyline: list[Point]) -> Point | None:
    if len(polyline) < 2:
        return None

    best_point: Point | None = None
    best_distance_sq = float("inf")
    for start, end in zip(polyline, polyline[1:]):
        projection = project_point_to_segment(point, start, end)
        if projection is None:
            continue
        dx = projection[0] - point[0]
        dy = projection[1] - point[1]
        distance_sq = dx * dx + dy * dy
        if distance_sq < best_distance_sq:
            best_distance_sq = distance_sq
            best_point = projection

    return best_point


class SGPreviewWidget(QtWidgets.QWidget):
    """Minimal preview widget that draws an SG file centreline."""

    selectedSectionChanged = QtCore.pyqtSignal(object)
    sectionsChanged = QtCore.pyqtSignal()  # NEW
    newStraightModeChanged = QtCore.pyqtSignal(bool)
    newCurveModeChanged = QtCore.pyqtSignal(bool)
    deleteModeChanged = QtCore.pyqtSignal(bool)
    splitSectionModeChanged = QtCore.pyqtSignal(bool)
    scaleChanged = QtCore.pyqtSignal(float)

    CURVE_SOLVE_TOLERANCE = CURVE_SOLVE_TOLERANCE_DEFAULT  # inches

    def __init__(
        self,
        parent: QtWidgets.QWidget | None = None,
        show_status: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setMinimumSize(640, 480)
        self.setMouseTracking(True)

        palette = self.palette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor("black"))
        self.setPalette(palette)

        self._controller = PreviewStateController()

        self._background = PreviewBackground()
        self._viewport = PreviewViewport(
            background=self._background,
            get_transform_state=lambda: self._transform_state,
            set_transform_state=self._set_transform_state,
        )
        self._section_manager = PreviewSectionManager(
            self._viewport.combine_bounds_with_background
        )

        self._cline: List[Point] | None = None
        self._start_finish_dlong: float | None = None
        self._start_finish_mapping: tuple[Point, Point, Point] | None = None

        self._is_panning = False
        self._last_mouse_pos: QtCore.QPoint | None = None
        self._press_pos: QtCore.QPoint | None = None
        self._selection = selection.SelectionManager()
        self._selection.selectionChanged.connect(self._on_selection_changed)

        self._creation_controller = CreationController()
        self._hovered_endpoint: tuple[int, str] | None = None

        self._split_section_mode = False
        self._split_previous_status_message: str | None = None
        self._split_hover_point: Point | None = None
        self._split_hover_section_index: int | None = None


        self._straight_creation = self._creation_controller.straight_interaction
        self._curve_creation = self._creation_controller.curve_interaction

        self._editor = PreviewEditor(
            self._controller,
            self._selection,
            self._straight_creation,
            self._curve_creation,
        )


        self._show_curve_markers = True
        self._show_axes = False

        self._node_status = {}   # (index, "start"|"end") -> "green" or "orange"
        self._disconnected_nodes: set[tuple[int, str]] = set()
        self._node_radius_px = 6
        self._has_unsaved_changes = False
        self._show_status = show_status or self.set_status_text

        self._interaction = PreviewInteraction(
            self,
            self._selection,
            self._section_manager,
            self._editor,
            self.set_sections,
            self.rebuild_after_start_finish,
            self._node_radius_px,
            self._stop_panning,
            show_status=self._show_status,
        )


        self._set_default_view_bounds()

        assert hasattr(self, "_editor")


    def current_transform(self, widget_size: tuple[int, int]) -> Transform | None:
        return self._controller.current_transform(widget_size)

    def map_to_track(
        self,
        screen_pos: tuple[float, float] | Point,
        widget_size: tuple[int, int],
        widget_height: int,
        transform: Transform | None = None,
    ) -> Point | None:
        point = (
            QtCore.QPointF(*screen_pos)
            if isinstance(screen_pos, tuple)
            else QtCore.QPointF(screen_pos)
        )
        return self._controller.map_to_track(point, widget_size, widget_height, transform)

    def set_status(self, text: str) -> None:
        self._status_message = text
        self.update()

    def set_status_text(self, text: str) -> None:
        self.set_status(text)

    def request_repaint(self) -> None:
        self.update()

    def widget_size(self) -> tuple[int, int]:
        return (self.width(), self.height())

    def widget_height(self) -> int:
        return self.height()

    def _stop_panning(self) -> None:
        self._is_panning = False
        self._last_mouse_pos = None
        self._press_pos = None

    @staticmethod
    def _create_empty_sgfile() -> SGFile:
        header = np.array(
            [int.from_bytes(b"\x00\x00GS", "little"), 1, 1, 0, 0, 0],
            dtype=np.int32,
        )
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

    def _set_transform_state(self, value: preview_state.TransformState) -> None:
        self._transform_state = value

    @property
    def _delete_section_active(self) -> bool:
        return self._editor.delete_section_active
    
    @property
    def has_unsaved_changes(self) -> bool:
        return self._has_unsaved_changes

    def _update_fit_scale(self) -> None:
        self._viewport.update_fit_scale(
            self._section_manager.sampled_bounds, (self.width(), self.height())
        )


    def clear(self, message: str | None = None) -> None:
        self._controller.clear(message)
        self._cline = None
        self._section_manager.reset()
        self._sampled_centerline = []
        self._sampled_bounds = None
        self._start_finish_dlong = None
        self._start_finish_mapping = None
        self._disconnected_nodes.clear()
        self._apply_creation_update(self._creation_controller.reset())
        self.cancel_split_section()
        self._editor.reset()
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
        default_bounds = self._viewport.default_bounds()
        self._section_manager.sampled_bounds = default_bounds
        self._sampled_bounds = default_bounds

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def load_sg_file(self, path: Path) -> None:
        self.cancel_split_section()
        data = self._controller.load_sg_file(path)
        if data is None:
            self.clear()
            return

        self._cline = data.cline
        self._section_manager.load_sections(
            sections=data.sections,
            section_endpoints=data.section_endpoints,
            sampled_centerline=data.sampled_centerline,
            sampled_dlongs=data.sampled_dlongs,
            sampled_bounds=data.sampled_bounds,
            centerline_index=data.centerline_index,
        )
        self._sampled_bounds = self._section_manager.sampled_bounds
        self._sampled_centerline = self._section_manager.sampled_centerline
        self._track_length = data.track_length
        self._start_finish_dlong = 0.0 if data.track_length else None
        self._start_finish_mapping = data.start_finish_mapping
        self._disconnected_nodes = set()
        self._apply_creation_update(self._creation_controller.reset())
        self._status_message = data.status_message
        self._selection.reset(
            self._section_manager.sections,
            self._track_length,
            self._section_manager.centerline_index,
            self._section_manager.sampled_dlongs,
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
        self._start_finish_dlong = None
        self._has_unsaved_changes = False
        self._update_fit_scale()
        self.update()

    def refresh_geometry(self) -> None:
        if self._sgfile is None:
            return

        sections = self._sections_from_sgfile()

        if sections:
            last_section = sections[-1]
            self._track_length = float(last_section.start_dlong + last_section.length)
        else:
            self._track_length = None

        needs_rebuild = self._section_manager.set_sections(sections)

        self._sampled_bounds = self._section_manager.sampled_bounds
        self._sampled_centerline = self._section_manager.sampled_centerline

        if needs_rebuild:
            self._update_fit_scale()

        self._update_node_status()

        self._selection.update_context(
            self._section_manager.sections,
            self._track_length,
            self._section_manager.centerline_index,
            self._section_manager.sampled_dlongs,
        )
        self._has_unsaved_changes = True
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
        self.cancel_split_section()
        update = self._creation_controller.begin_new_straight(
            bool(self._sampled_bounds)
        )
        self._apply_creation_update(update)
        return update.handled

    def begin_new_curve(self) -> bool:
        self.cancel_split_section()
        update = self._creation_controller.begin_new_curve(bool(self._sampled_bounds))
        self._apply_creation_update(update)
        return update.handled

    def _finalize_new_straight(self) -> None:
        updated_sections, track_length, new_index, status = self._editor.finalize_new_straight(
            self._section_manager.sections, self._track_length
        )
        if new_index is None:
            return

        self._track_length = track_length
        self.set_sections(updated_sections)
        self._selection.set_selected_section(new_index)
        self._apply_creation_update(self._creation_controller.finish_straight(status))

    def _finalize_new_curve(self) -> None:
        updated_sections, track_length, new_index, status = self._editor.finalize_new_curve(
            self._section_manager.sections, self._track_length
        )
        if new_index is None:
            return

        self._track_length = track_length
        self.set_sections(updated_sections)
        self._selection.set_selected_section(new_index)
        self._apply_creation_update(self._creation_controller.finish_curve(status))

    def _next_section_start_dlong(self) -> float:
        return self._editor.next_section_start_dlong(self._section_manager.sections)

    # ------------------------------------------------------------------
    # Delete section
    # ------------------------------------------------------------------
    def begin_delete_section(self) -> bool:
        if not self._section_manager.sections:
            return False

        self._set_delete_section_active(True)
        self._status_message = "Click a section to delete it."
        self.update()
        return True

    def cancel_delete_section(self) -> None:
        self._set_delete_section_active(False)

    def _set_delete_section_active(self, active: bool) -> None:
        if active:
            changed = self._editor.begin_delete_section(self._section_manager.sections)
        else:
            changed = self._editor.cancel_delete_section()

        if not changed:
            return

        if active:
            self.cancel_split_section()
            self._apply_creation_update(
                self._creation_controller.deactivate_creation()
            )
        self.deleteModeChanged.emit(active)

    # ------------------------------------------------------------------
    # Split section
    # ------------------------------------------------------------------
    def begin_split_section(self) -> bool:
        if not self._section_manager.sections:
            return False

        if self._split_section_mode:
            return True

        self._split_previous_status_message = self._status_message
        self._clear_split_hover()
        self._split_section_mode = True
        self._apply_creation_update(self._creation_controller.deactivate_creation())
        self.set_status_text("Hover over a straight or curve section to choose split point.")
        self.splitSectionModeChanged.emit(True)
        self.request_repaint()
        return True

    def cancel_split_section(self) -> None:
        if not self._split_section_mode and self._split_hover_point is None:
            return

        self._exit_split_section_mode()

    def _update_split_hover(self, screen_pos: QtCore.QPoint) -> None:
        widget_size = (self.width(), self.height())
        transform = self.current_transform(widget_size)
        if transform is None:
            self._clear_split_hover()
            return

        track_point = self.map_to_track(
            screen_pos, widget_size, self.height(), transform
        )
        if track_point is None:
            self._clear_split_hover()
            return

        section_index = self._selection.find_section_at_point(
            screen_pos,
            lambda p: self.map_to_track(p, widget_size, self.height(), transform),
            transform,
        )
        if section_index is None:
            self._clear_split_hover()
            return

        section = self._section_manager.sections[section_index]
        if section.type_name not in {"straight", "curve"}:
            self._clear_split_hover()
            return

        if section.type_name == "straight":
            projected = project_point_to_segment(track_point, section.start, section.end)
        else:
            projected = _project_point_to_polyline(track_point, section.polyline)
        if projected is None:
            self._clear_split_hover()
            return

        self._split_hover_point = projected
        self._split_hover_section_index = section_index
        self.request_repaint()

    def _clear_split_hover(self) -> None:
        if self._split_hover_point is not None or self._split_hover_section_index is not None:
            self._split_hover_point = None
            self._split_hover_section_index = None
            self.request_repaint()

    def _commit_split(self) -> None:
        idx = self._split_hover_section_index
        point = self._split_hover_point

        if idx is None or point is None:
            return

        section = self._section_manager.sections[idx]
        if section.type_name == "curve":
            result = self._editor.split_curve_section(
                list(self._section_manager.sections), idx, point
            )
        else:
            result = self._editor.split_straight_section(
                list(self._section_manager.sections), idx, point
            )
        if result is None:
            return

        sections, track_length = result
        self._track_length = track_length
        self.set_sections(sections)
        if idx + 1 < len(sections):
            self._selection.set_selected_section(idx + 1)
        self._exit_split_section_mode("Split complete.")

    def _exit_split_section_mode(self, status_message: str | None = None) -> None:
        self._split_section_mode = False
        self._clear_split_hover()
        if status_message is not None:
            self._status_message = status_message
        elif self._split_previous_status_message is not None:
            self._status_message = self._split_previous_status_message
        self._split_previous_status_message = None
        self.splitSectionModeChanged.emit(False)
        self._show_status(self._status_message)
        self.request_repaint()

    def set_background_settings(
        self, scale_500ths_per_px: float, origin: Point
    ) -> None:
        self._background.scale_500ths_per_px = scale_500ths_per_px
        self._background.world_xy_at_image_uv_00 = origin
        self._fit_view_to_background()
        self.update()

    def get_background_settings(self) -> tuple[float, Point]:
        return self._background.scale_500ths_per_px, self._background.world_xy_at_image_uv_00

    def _background_bounds(self) -> tuple[float, float, float, float] | None:
        return self._background.bounds()

    def _combine_bounds_with_background(
        self, bounds: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        return self._viewport.combine_bounds_with_background(bounds)

    def _fit_view_to_background(self) -> None:
        active_bounds = self._viewport.fit_view_to_background(
            self._section_manager.sampled_bounds, (self.width(), self.height())
        )
        if active_bounds is None:
            return

        self._section_manager.sampled_bounds = active_bounds
        self._sampled_bounds = active_bounds

    def get_background_image_path(self) -> Path | None:
        return self._background.image_path

    def has_background_image(self) -> bool:
        return self._background.image is not None

    def _update_node_status(self) -> None:
        """Update cached node colors directly from section connectivity."""
        update_node_status(self._section_manager.sections, self._node_status)

    def _build_node_positions(self):
        return build_node_positions(self._section_manager.sections)

    def _can_drag_section_node(self, section: SectionPreview) -> bool:
        return self._editor.can_drag_section_node(
            self._section_manager.sections, section
        )

    def _can_drag_section_polyline(self, section: SectionPreview, index: int | None = None) -> bool:
        return self._editor.can_drag_section_polyline(
            self._section_manager.sections, section, index
        )

    def _connected_neighbor_index(self, index: int, direction: str) -> int | None:
        return self._editor.connected_neighbor_index(
            self._section_manager.sections, index, direction
        )

    def _get_drag_chain(self, index: int | None) -> list[int] | None:
        return self._editor.get_drag_chain(self._section_manager.sections, index)

    def _can_drag_node(self, section: SectionPreview, endtype: str) -> bool:
        return self._editor.can_drag_node(
            self._section_manager.sections, section, endtype
        )

    def _creation_context(self) -> CreationEventContext | None:
        widget_size = (self.width(), self.height())
        transform = self._controller.current_transform(widget_size)
        if transform is None:
            return None

        def map_to_track(point: tuple[float, float]) -> Point | None:
            return self._controller.map_to_track(
                QtCore.QPointF(*point), widget_size, self.height(), transform
            )

        def find_unconnected_node(
            point: tuple[float, float],
        ) -> tuple[int, str, Point, tuple[float, float] | None] | None:
            return find_unconnected_node_hit(
                point,
                self._section_manager.sections,
                transform,
                self.height(),
                self._node_radius_px,
            )

        return CreationEventContext(
            map_to_track=map_to_track, find_unconnected_node=find_unconnected_node
        )

    def _lock_user_transform(self) -> None:
        """Prevent auto-fit from overriding the current zoom/pan during creation."""
        state = self._transform_state
        if state.user_transform_active:
            return

        if state.current_scale is None or state.view_center is None:
            self._update_fit_scale()
            state = self._transform_state

        self._transform_state = replace(
            state,
            user_transform_active=True,
            current_scale=state.current_scale or state.fit_scale,
        )

    def _apply_creation_update(self, update: CreationUpdate) -> None:
        if update is None:
            return
        if update.stop_panning:
            self._stop_panning()
        if update.status_changed:
            self._status_message = self._creation_controller.status_text
        if update.straight_mode_changed:
            if self._creation_controller.straight_active:
                self._set_delete_section_active(False)
                self.cancel_split_section()
                self._lock_user_transform()
            self.newStraightModeChanged.emit(self._creation_controller.straight_active)
        if update.curve_mode_changed:
            if self._creation_controller.curve_active:
                self._set_delete_section_active(False)
                self.cancel_split_section()
                self._lock_user_transform()
            self.newCurveModeChanged.emit(self._creation_controller.curve_active)
        if update.finalize_straight:
            self._finalize_new_straight()
        if update.finalize_curve:
            self._finalize_new_curve()
        if update.repaint:
            self.update()

    def _creation_active(self) -> bool:
        return self._creation_controller.straight_active or self._creation_controller.curve_active

    def _handle_creation_mouse_press(self, event: QtGui.QMouseEvent) -> bool:
        context = self._creation_context()
        if context is None:
            return False

        button = "left" if event.button() == QtCore.Qt.LeftButton else None
        creation_event = CreationEvent(
            pos=(event.pos().x(), event.pos().y()), button=button
        )
        update = self._creation_controller.handle_mouse_press(creation_event, context)
        self._apply_creation_update(update)
        return update.handled

    def _handle_creation_mouse_move(self, pos: QtCore.QPoint) -> bool:
        context = self._creation_context()
        if context is None:
            return False

        update = self._creation_controller.handle_mouse_move(
            (pos.x(), pos.y()), context
        )
        self._apply_creation_update(update)
        return update.handled

    def _handle_creation_mouse_release(self, event: QtGui.QMouseEvent) -> bool:
        context = self._creation_context()
        if context is None:
            return False

        button = "left" if event.button() == QtCore.Qt.LeftButton else None
        creation_event = CreationEvent(
            pos=(event.pos().x(), event.pos().y()), button=button
        )
        update = self._creation_controller.handle_mouse_release(creation_event, context)
        self._apply_creation_update(update)
        return update.handled



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

        node_state = None
        if transform is not None:
            node_state = preview_painter.NodeOverlayState(
                node_positions=self._build_node_positions(),
                node_status=self._node_status,
                node_radius_px=self._node_radius_px,
                hovered_node=self._hovered_endpoint,
                connection_target=self._interaction.connection_target,
            )

        creation_preview = self._creation_controller.preview_sections()
        drag_heading_state = None
        if transform is not None:
            dragged_heading = self._interaction.dragged_curve_heading()
            if dragged_heading is not None:
                drag_section, drag_end_point = dragged_heading
                drag_heading_state = preview_painter.DragHeadingState(
                    section=drag_section,
                    end_point=drag_end_point,
                )

        preview_painter.paint_preview(
            painter,
            preview_painter.BasePreviewState(
                rect=self.rect(),
                background_color=self.palette().color(QtGui.QPalette.Window),
                background_image=self._background.image,
                background_scale_500ths_per_px=self._background.scale_500ths_per_px,
                background_origin=self._background.world_xy_at_image_uv_00,
                sampled_centerline=self._section_manager.sampled_centerline,
                centerline_polylines=self._section_manager.centerline_polylines,
                selected_section_points=self._selection.selected_section_points,
                section_endpoints=self._section_manager.section_endpoints,
                selected_section_index=self._selection.selected_section_index,
                show_curve_markers=self._show_curve_markers,
                show_axes=self._show_axes,
                sections=self._section_manager.sections,
                selected_curve_index=self._selection.selected_curve_index,
                start_finish_mapping=self._start_finish_mapping,
                status_message=self._status_message,
                split_section_mode=self._split_section_mode,
                split_hover_point=self._split_hover_point,
            ),
            preview_painter.CreationOverlayState(
                new_straight_active=creation_preview.new_straight_active,
                new_straight_start=creation_preview.new_straight_start,
                new_straight_end=creation_preview.new_straight_end,
                new_curve_active=creation_preview.new_curve_active,
                new_curve_start=creation_preview.new_curve_start,
                new_curve_end=creation_preview.new_curve_end,
                new_curve_preview=creation_preview.new_curve_preview,
            ),
            node_state,
            drag_heading_state,
            transform,
            self.height(),
        )

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:  # noqa: D401
        widget_size = (self.width(), self.height())
        transform = self._controller.current_transform(widget_size)
        state = self._transform_state
        new_state = zoom_transform_state(
            state,
            event.angleDelta().y(),
            (event.pos().x(), event.pos().y()),
            widget_size,
            self.height(),
            transform,
            self._controller.clamp_scale,
            self._controller.default_center,
            lambda p: self._controller.map_to_track(
                QtCore.QPointF(*p), widget_size, self.height(), transform
            ),
        )
        if new_state is None:
            return
        self._transform_state = new_state
        self.update()
        event.accept()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401
        if self._handle_creation_mouse_press(event):
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
        if self._creation_active():
            event.accept()
            return

        if self._split_section_mode:
            self._is_panning = False
            self._last_mouse_pos = None
            self._press_pos = None
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
        
        if self._handle_creation_mouse_move(event.pos()):
            event.accept()
            return

        if self._creation_active():
            event.accept()
            return

        if self._delete_section_active:
            event.accept()
            return

        if self._split_section_mode:
            self._update_split_hover(event.pos())
            event.accept()
            return



        # --------------------------------------------------
        # THEN let interaction handle the move
        # --------------------------------------------------
        if self._interaction.handle_mouse_move(event):
            self.update()
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
                    self._transform_state = pan_transform_state(
                        state,
                        (delta.x(), delta.y()),
                        scale,
                        center,
                    )
                    self.update()
            event.accept()
            return
        
        context = self._creation_context()
        if context is not None:
            hover = find_hovered_unconnected_node(
                (event.pos().x(), event.pos().y()),
                context,
            )

            if hover != self._hovered_endpoint:
                self._hovered_endpoint = hover
                self.update()



        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401
        if self._handle_creation_mouse_release(event):
            return

        if self._split_section_mode:
            if event.button() == QtCore.Qt.LeftButton and self._split_hover_point is not None:
                self._commit_split()
            self._press_pos = None
            event.accept()
            return

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
            if self._split_section_mode:
                self._press_pos = None
                event.accept()
                return
            if self._creation_active():
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

    def leaveEvent(self, event: QtCore.QEvent) -> None:  # noqa: D401
        self._clear_split_hover()
        super().leaveEvent(event)

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

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
            list(self._section_manager.sections), index
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
        return list(self._section_manager.sections), track_length

    def get_surface_preview_data(
        self,
    ) -> tuple[
        TRKFile | None,
        list[Point] | None,
        list[Point],
        tuple[float, float, float, float] | None,
    ]:
        return (
            self._trk,
            list(self._cline) if self._cline is not None else None,
            list(self._sampled_centerline),
            self._sampled_bounds,
        )

    def track_length_message(self) -> str:
        sections = self._section_manager.sections
        if not sections or not is_closed_loop(sections):
            return "Complete the loop to show track length"

        try:
            total_length = loop_length(sections)
        except ValueError:
            return "Complete the loop to show track length"

        miles = total_length / (500.0 * 12 * 5280)
        return f"Track length: {total_length:.0f} DLONG (500ths) — {miles:.3f} miles"

    def scale_track_to_length(self, target_length: float) -> str | None:
        """Scale the current closed loop to ``target_length`` DLONG (500ths)."""

        sections = self._section_manager.sections
        if not sections or not is_closed_loop(sections):
            return None

        try:
            current_length = loop_length(sections)
        except ValueError:
            return None

        if current_length <= 0:
            return None

        factor = target_length / current_length
        if math.isclose(factor, 1.0, rel_tol=1e-9):
            return "Track already at desired length."

        scaled_sections = [scale_section(sect, factor) for sect in sections]
        scaled_start_finish = self._start_finish_dlong
        if scaled_start_finish is not None:
            scaled_start_finish *= factor

        self.set_sections(scaled_sections, start_finish_dlong=scaled_start_finish)

        return f"Scaled track by {factor:.3f}× to {target_length:.0f} DLONG."

    def _current_start_finish_dlong(self) -> float | None:
        if self._track_length is None or self._track_length <= 0:
            return None

        if self._start_finish_dlong is not None:
            return float(self._start_finish_dlong) % float(self._track_length)

        if (
            self._start_finish_mapping is None
            or self._section_manager.centerline_index is None
            or not self._section_manager.sampled_dlongs
        ):
            return None

        track_length = self._track_length
        if track_length is None and self._section_manager.sampled_dlongs:
            track_length = self._section_manager.sampled_dlongs[-1]

        if track_length is None or track_length <= 0:
            return None

        (cx, cy), _, _ = self._start_finish_mapping
        _, nearest_dlong, _ = project_point_to_centerline(
            (cx, cy),
            self._section_manager.centerline_index,
            self._section_manager.sampled_dlongs,
            track_length,
        )
        return nearest_dlong

    def set_sections(self, sections: list[SectionPreview], start_finish_dlong: float | None = None) -> None:
        self._clear_split_hover()

        preserved_start_finish_dlong = start_finish_dlong
        if preserved_start_finish_dlong is None:
            preserved_start_finish_dlong = self._start_finish_dlong
        if preserved_start_finish_dlong is None:
            preserved_start_finish_dlong = self._current_start_finish_dlong()

        needs_rebuild = self._section_manager.set_sections(sections)

        self._sampled_bounds = self._section_manager.sampled_bounds
        self._sampled_centerline = self._section_manager.sampled_centerline
        if self._section_manager.sampled_dlongs:
            self._track_length = self._section_manager.sampled_dlongs[-1]
        self._update_start_finish_mapping(preserved_start_finish_dlong)

        if needs_rebuild:
            self._update_fit_scale()

        self._update_node_status()


        self._selection.update_context(
            self._section_manager.sections,
            self._track_length,
            self._section_manager.centerline_index,
            self._section_manager.sampled_dlongs,
        )
        if preserved_start_finish_dlong is not None and self._track_length:
            self._start_finish_dlong = float(preserved_start_finish_dlong) % float(self._track_length)
        self._has_unsaved_changes = True
        self.sectionsChanged.emit()  # NEW
        self.update()

    def rebuild_after_start_finish(self, sections: list[SectionPreview]) -> None:
        (
            cline,
            sampled_dlongs,
            sampled_bounds,
            centerline_index,
        ) = rebuild_centerline_from_sections(sections)

        track_length = sampled_dlongs[-1] if sampled_dlongs else 0.0

        self._section_manager.load_sections(
            sections=sections,
            section_endpoints=[(sect.start, sect.end) for sect in sections],
            sampled_centerline=cline,
            sampled_dlongs=sampled_dlongs,
            sampled_bounds=sampled_bounds or (0.0, 0.0, 0.0, 0.0),
            centerline_index=centerline_index,
        )
        self._sampled_bounds = self._section_manager.sampled_bounds
        self._sampled_centerline = self._section_manager.sampled_centerline
        self._track_length = track_length
        self._start_finish_mapping = None
        self._start_finish_dlong = 0.0 if track_length > 0 else None

        previous_block_state = self._selection.blockSignals(True)
        try:
            self._selection.reset(
                self._section_manager.sections,
                self._track_length,
                self._section_manager.centerline_index,
                self._section_manager.sampled_dlongs,
            )
            self._update_node_status()
            self._update_start_finish_mapping(0.0 if track_length > 0 else None)
        finally:
            self._selection.blockSignals(previous_block_state)

        self._has_unsaved_changes = True
        self.sectionsChanged.emit()
        self._selection.set_selected_section(
            0 if self._section_manager.sections else None
        )


    def _compute_start_finish_mapping_from_samples(
        self, start_dlong: float | None
    ) -> tuple[Point, Point, Point] | None:
        if (
            start_dlong is None
            or self._track_length is None
            or self._track_length <= 0
        ):
            return None

        points = self._section_manager.sampled_centerline
        dlongs = self._section_manager.sampled_dlongs
        if len(points) < 2 or len(points) != len(dlongs):
            return None

        target = float(start_dlong) % float(self._track_length)

        for idx in range(len(dlongs) - 1):
            seg_start = points[idx]
            seg_end = points[idx + 1]
            seg_span = dlongs[idx + 1] - dlongs[idx]
            if seg_span <= 0:
                continue
            if not (dlongs[idx] <= target <= dlongs[idx + 1]):
                continue

            fraction = (target - dlongs[idx]) / seg_span
            cx = seg_start[0] + (seg_end[0] - seg_start[0]) * fraction
            cy = seg_start[1] + (seg_end[1] - seg_start[1]) * fraction

            dx = seg_end[0] - seg_start[0]
            dy = seg_end[1] - seg_start[1]
            length = math.hypot(dx, dy)
            if length == 0:
                return None

            tangent = (dx / length, dy / length)
            normal = (-tangent[1], tangent[0])
            return (cx, cy), normal, tangent

        start = points[0]
        end = points[1]
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.hypot(dx, dy)
        if length == 0:
            return None

        tangent = (dx / length, dy / length)
        normal = (-tangent[1], tangent[0])
        return start, normal, tangent

    def _update_start_finish_mapping(self, start_dlong: float | None) -> None:
        mapping = self._compute_start_finish_mapping_from_samples(start_dlong)

        if mapping is None and start_dlong is not None:
            if (
                self._trk is not None
                and self._cline is not None
                and self._track_length
                and self._track_length > 0
            ):
                mapping = compute_centerline_normal_and_tangent(
                    self._trk, self._cline, self._track_length, start_dlong
                )

        if mapping is None:
            mapping = compute_start_finish_mapping_from_centerline(
                self._section_manager.sampled_centerline
            )

        self._start_finish_mapping = mapping
        if start_dlong is not None and self._track_length:
            self._start_finish_dlong = float(start_dlong) % float(self._track_length)

    def apply_preview_to_sgfile(self) -> SGFile:
        return self._apply_preview_to_sgfile()

    def save_sg(self, path: Path) -> None:
        """Write the current SG (and any edits) to ``path``."""

        sgfile = self._apply_preview_to_sgfile()

        sgfile.output_sg(str(path))
        self._has_unsaved_changes = False

    def _apply_preview_to_sgfile(self) -> SGFile:
        if self._sgfile is None:
            raise ValueError("No SG file loaded.")

        if not self._section_manager.sections:
            raise ValueError("No sections available to save.")

        sgfile = self._sgfile

        desired_section_count = len(self._section_manager.sections)
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

        for sg_section, preview_section in zip(
            sgfile.sects, self._section_manager.sections
        ):
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
                sang1, sang2, eang1, eang2 = curve_angles(
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

            sg_section.recompute_curve_length()

        return sgfile

    def get_section_headings(self) -> list[selection.SectionHeadingData]:
        return self._selection.get_section_headings()

    def get_xsect_metadata(self) -> list[tuple[int, float]]:
        if self._sgfile is None:
            return []
        return [(idx, float(dlat)) for idx, dlat in enumerate(self._sgfile.xsect_dlats)]

    def get_section_range(self, index: int) -> tuple[float, float] | None:
        if (
            not self._section_manager.sections
            or index < 0
            or index >= len(self._section_manager.sections)
        ):
            return None
        start = float(self._section_manager.sections[index].start_dlong)
        end = start + float(self._section_manager.sections[index].length)
        return start, end

    def build_elevation_profile(self, xsect_index: int, samples_per_section: int = 24) -> ElevationProfileData | None:
        if (
            self._sgfile is None
            or self._track_length is None
            or xsect_index < 0
            or xsect_index >= self._sgfile.num_xsects
        ):
            return None

        def _xsect_label(dlat_value: float) -> str:
            return f"X-Section {xsect_index} (DLAT {dlat_value:.0f})"

        dlat_values = (
            self._trk.xsect_dlats
            if self._trk is not None
            else self._sgfile.xsect_dlats
        )
        if xsect_index >= len(dlat_values):
            return None

        dlat_value = float(dlat_values[xsect_index])

        if self._trk is None or self._track_length <= 0:
            track_length = float(self._track_length or 0.0)
            track_length = track_length if track_length > 0 else 1.0
            return ElevationProfileData(
                dlongs=[0.0, track_length],
                sg_altitudes=[0.0, 0.0],
                trk_altitudes=[0.0, 0.0],
                section_ranges=[],
                track_length=track_length,
                xsect_label=_xsect_label(dlat_value),
            )

        dlongs: list[float] = []
        sg_altitudes: list[float] = []
        trk_altitudes: list[float] = []
        section_ranges: list[tuple[float, float]] = []

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

        return ElevationProfileData(
            dlongs=dlongs,
            sg_altitudes=sg_altitudes,
            trk_altitudes=trk_altitudes,
            section_ranges=section_ranges,
            track_length=float(self._track_length),
            xsect_label=_xsect_label(dlat_value),
        )

    # ------------------------------------------------------------------
    # Public controls
    # ------------------------------------------------------------------
    def set_show_curve_markers(self, visible: bool) -> None:
        self._show_curve_markers = visible
        self.update()

    def set_show_axes(self, visible: bool) -> None:
        self._show_axes = visible
        self.update()

    def activate_set_start_finish_mode(self) -> None:
        """Backward-compatible alias for setting start/finish."""
        self.set_start_finish_at_selected_section()

    def set_start_finish_at_selected_section(self) -> None:
        if not self._section_manager.sections:
            return

        selected_index = self._selection.selected_section_index
        if selected_index is None:
            self._show_status("Select a section to set start/finish")
            return

        if not is_closed_loop(self._section_manager.sections):
            self._show_status("Track must be closed to set start/finish")
            return

        try:
            new_sections = set_start_finish(
                self._section_manager.sections, selected_index
            )
        except ValueError:
            self._show_status("Track must be closed to set start/finish")
            return
        except RuntimeError:
            self._show_status("Invalid loop topology; cannot set start/finish")
            return

        self.rebuild_after_start_finish(new_sections)
        self._show_status("Start/finish set to selected section (now section 0)")

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

    def _sections_from_sgfile(self) -> list[SectionPreview]:
        if self._sgfile is None:
            return []

        sections: list[SectionPreview] = []
        for idx, sg_section in enumerate(self._sgfile.sects):
            type_name = "curve" if sg_section.type == 2 else "straight"
            start = (float(sg_section.start_x), float(sg_section.start_y))
            end = (float(sg_section.end_x), float(sg_section.end_y))

            center = (
                (float(sg_section.center_x), float(sg_section.center_y))
                if type_name == "curve"
                else None
            )
            radius = float(sg_section.radius) if type_name == "curve" else None

            sang1 = sang2 = eang1 = eang2 = None
            if type_name == "curve":
                sang1 = float(sg_section.sang1)
                sang2 = float(sg_section.sang2)
                eang1 = float(sg_section.eang1)
                eang2 = float(sg_section.eang2)

            polyline = build_section_polyline(
                type_name,
                start,
                end,
                center,
                radius,
                (sang1, sang2) if sang1 is not None and sang2 is not None else None,
                (eang1, eang2) if eang1 is not None and eang2 is not None else None,
            )
            start_heading, end_heading = derive_heading_vectors(
                polyline, sang1, sang2, eang1, eang2
            )

            sections.append(
                SectionPreview(
                    section_id=idx,
                    type_name=type_name,
                    previous_id=int(getattr(sg_section, "sec_prev", idx - 1)),
                    next_id=int(getattr(sg_section, "sec_next", idx + 1)),
                    start=start,
                    end=end,
                    start_dlong=float(sg_section.start_dlong),
                    length=float(sg_section.length),
                    center=center,
                    sang1=sang1,
                    sang2=sang2,
                    eang1=eang1,
                    eang2=eang2,
                    radius=radius,
                    start_heading=start_heading,
                    end_heading=end_heading,
                    polyline=polyline,
                )
            )

        return sections
