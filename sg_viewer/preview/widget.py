from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from typing import List, Tuple

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
from sg_viewer.ui.preview_editor import PreviewEditor
from sg_viewer.preview.creation_controller import CreationController, CreationEvent, CreationEventContext, CreationUpdate
from sg_viewer.ui.preview_interaction import PreviewInteraction
from sg_viewer.ui.preview_state_controller import PreviewStateController
from sg_viewer.ui.preview_section_manager import PreviewSectionManager
from sg_viewer.ui.preview_viewport import PreviewViewport
from sg_viewer.models.preview_state_utils import update_node_status
from sg_viewer.models.sg_model import SectionPreview
from sg_viewer.preview.hover_detection import find_hovered_unconnected_node


logger = logging.getLogger(__name__)

Point = Tuple[float, float]
Transform = tuple[float, tuple[float, float]]


class SGPreviewWidget(QtWidgets.QWidget):
    """Minimal preview widget that draws an SG file centreline."""

    selectedSectionChanged = QtCore.pyqtSignal(object)
    sectionsChanged = QtCore.pyqtSignal()  # NEW
    newStraightModeChanged = QtCore.pyqtSignal(bool)
    newCurveModeChanged = QtCore.pyqtSignal(bool)
    deleteModeChanged = QtCore.pyqtSignal(bool)
    scaleChanged = QtCore.pyqtSignal(float)

    CURVE_SOLVE_TOLERANCE = CURVE_SOLVE_TOLERANCE_DEFAULT  # inches

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
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
        self._start_finish_mapping: tuple[Point, Point, Point] | None = None

        self._is_panning = False
        self._last_mouse_pos: QtCore.QPoint | None = None
        self._press_pos: QtCore.QPoint | None = None
        self._selection = selection.SelectionManager()
        self._selection.selectionChanged.connect(self._on_selection_changed)

        self._creation_controller = CreationController()
        self._hovered_endpoint: tuple[int, str] | None = None


        self._straight_creation = self._creation_controller.straight_interaction
        self._curve_creation = self._creation_controller.curve_interaction

        self._editor = PreviewEditor(
            self._controller,
            self._selection,
            self._straight_creation,
            self._curve_creation,
        )


        self._show_curve_markers = True

        self._node_status = {}   # (index, "start"|"end") -> "green" or "orange"
        self._disconnected_nodes: set[tuple[int, str]] = set()
        self._node_radius_px = 6
        self._has_unsaved_changes = False

        self._interaction = PreviewInteraction(
            self,
            self._selection,
            self._section_manager,
            self._editor,
            self.set_sections,
            self._node_radius_px,
            self._stop_panning,
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
        self._start_finish_mapping = None
        self._disconnected_nodes.clear()
        self._apply_creation_update(self._creation_controller.reset())
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
        update = self._creation_controller.begin_new_straight(
            bool(self._sampled_bounds)
        )
        self._apply_creation_update(update)
        return update.handled

    def begin_new_curve(self) -> bool:
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
            self._apply_creation_update(
                self._creation_controller.deactivate_creation()
            )
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
            self.newStraightModeChanged.emit(self._creation_controller.straight_active)
        if update.curve_mode_changed:
            if self._creation_controller.curve_active:
                self._set_delete_section_active(False)
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
            )

        creation_preview = self._creation_controller.preview_sections()

        preview_painter.paint_preview(
            painter,
            preview_painter.BasePreviewState(
                rect=self.rect(),
                background_color=self.palette().color(QtGui.QPalette.Window),
                background_image=self._background.image,
                background_scale_500ths_per_px=self._background.scale_500ths_per_px,
                background_origin=self._background.origin,
                sampled_centerline=self._section_manager.sampled_centerline,
                centerline_polylines=self._section_manager.centerline_polylines,
                selected_section_points=self._selection.selected_section_points,
                section_endpoints=self._section_manager.section_endpoints,
                selected_section_index=self._selection.selected_section_index,
                show_curve_markers=self._show_curve_markers,
                sections=self._section_manager.sections,
                selected_curve_index=self._selection.selected_curve_index,
                start_finish_mapping=self._start_finish_mapping,
                status_message=self._status_message,
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

    def set_sections(self, sections: list[SectionPreview]) -> None:
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
        self.sectionsChanged.emit()  # NEW
        self.update()

    def save_sg(self, path: Path) -> None:
        """Write the current SG (and any edits) to ``path``."""

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

        sgfile.output_sg(str(path))
        self._has_unsaved_changes = False

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


