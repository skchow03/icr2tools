from __future__ import annotations

from typing import Callable

from icr2_core.trk.sg_classes import SGFile
from icr2_core.trk.trk_classes import TRKFile
from sg_viewer.geometry.derived_geometry import DerivedGeometry
from sg_viewer.model.sg_document import SGDocument
from sg_viewer.model import preview_state, selection
from sg_viewer.model.preview_fsection import PreviewFSection
from sg_viewer.model.sg_model import PreviewData
from sg_viewer.preview.context import PreviewContext
from sg_viewer.preview.creation_controller import CreationController
from sg_viewer.preview.interaction_state import InteractionState
from sg_viewer.preview.trk_overlay_controller import TrkOverlayController
from sg_viewer.preview.transform_controller import TransformController
from sg_viewer.services.preview_background import PreviewBackground
from sg_viewer.model.preview_state import SgPreviewViewState
from sg_viewer.ui.preview_editor import PreviewEditor
from sg_viewer.ui.preview_interaction import PreviewInteraction
from sg_viewer.runtime.viewer_runtime_api import ViewerRuntimeApi
from sg_viewer.ui.preview_section_manager import PreviewSectionManager
from sg_viewer.ui.preview_state_controller import PreviewStateController
from sg_viewer.ui.preview_viewport import PreviewViewport
from sg_viewer.preview.runtime_ops.base_context import Point, Transform


class _RuntimeCoreBaseMixin:
    def __init__(
        self,
        context: PreviewContext,
        sg_document: SGDocument,
        show_status: Callable[[str], None] | None = None,
        emit_selected_section_changed: Callable[[object], None] | None = None,
        emit_sections_changed: Callable[[], None] | None = None,
        emit_new_straight_mode_changed: Callable[[bool], None] | None = None,
        emit_new_curve_mode_changed: Callable[[bool], None] | None = None,
        emit_delete_mode_changed: Callable[[bool], None] | None = None,
        emit_split_section_mode_changed: Callable[[bool], None] | None = None,
        emit_scale_changed: Callable[[float], None] | None = None,
        emit_interaction_drag_changed: Callable[[bool], None] | None = None,
    ) -> None:
        self._context = context
        self._emit_selected_section_changed = emit_selected_section_changed
        self._emit_sections_changed = emit_sections_changed
        self._emit_new_straight_mode_changed = emit_new_straight_mode_changed
        self._emit_new_curve_mode_changed = emit_new_curve_mode_changed
        self._emit_delete_mode_changed = emit_delete_mode_changed
        self._emit_split_section_mode_changed = emit_split_section_mode_changed
        self._emit_scale_changed = emit_scale_changed
        self._emit_interaction_drag_changed = emit_interaction_drag_changed
        self._document = sg_document
        self._derived_geometry = DerivedGeometry(self._document)
        self._suppress_document_dirty = False

        self._document.section_changed.connect(self._on_section_changed)
        self._document.geometry_changed.connect(self._on_geometry_changed)
        self._document.elevation_changed.connect(self._on_elevation_changed)

        self._controller = PreviewStateController()

        self._background = PreviewBackground()
        self._viewport = PreviewViewport(
            background=self._background,
            get_transform_state=lambda: self._transform_state,
            set_transform_state=self._set_transform_state,
        )
        self._transform_controller = TransformController(
            viewport=self._viewport,
            get_state=lambda: self._transform_state,
            set_state=self._set_transform_state,
            map_to_track_cb=self._map_to_track_cb,
        )
        self._section_manager = PreviewSectionManager(
            self._viewport.combine_bounds_with_background
        )

        self._preview_data: PreviewData | None = None
        self._trk_overlay = TrkOverlayController()
        self._start_finish_dlong: float | None = None
        self._start_finish_mapping: tuple[Point, Point, Point] | None = None

        self._sg_preview_model = None
        self._sg_preview_view_state = SgPreviewViewState()
        self._show_sg_fsects = False
        self._show_xsect_dlat_line = False
        self._selected_xsect_index: int | None = None
        self._fsects_by_section: list[list[PreviewFSection]] = []
        self._fsect_undo_stack: list[list[list[PreviewFSection]]] = []
        self._fsect_redo_stack: list[list[list[PreviewFSection]]] = []
        self._suspend_fsect_history = False
        self._fsect_edit_session_active = False
        self._fsect_edit_session_snapshot: list[list[PreviewFSection]] | None = None
        self._last_elevation_recalc_message: str | None = None

        self._selection = selection.SelectionManager()
        self._selection.selectionChanged.connect(self._on_selection_changed)

        self._creation_controller = CreationController()
        self._interaction_state = InteractionState()

        self._drag_transform: Transform | None = None
        self._drag_transform_active = False

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
        self._show_background_image = True
        self._track_opacity = 1.0

        self._node_status = {}  # (index, "start"|"end") -> "green" or "orange"
        self._disconnected_nodes: set[tuple[int, str]] = set()
        self._node_radius_px = 6
        self._has_unsaved_changes = False
        self._show_status = show_status or self.set_status_text
        self._sg_version = 0
        self._elevation_bounds_cache: dict[tuple[int, int], tuple[float, float] | None] = {}
        self._elevation_xsect_bounds_cache: dict[
            tuple[int, int], dict[int, tuple[float, float] | None]
        ] = {}
        self._elevation_xsect_bounds_dirty: dict[tuple[int, int], set[int]] = {}
        self._elevation_profile_cache: dict[
            tuple[int, int], tuple[list[float], list[tuple[float, float]]]
        ] = {}

        self._interaction = PreviewInteraction(
            self._context,
            self._selection,
            self._section_manager,
            self._editor,
            self.set_sections,
            self.update_drag_preview,
            self.rebuild_after_start_finish,
            self._node_radius_px,
            self._stop_panning,
            show_status=self._show_status,
            emit_drag_state_changed=self._emit_interaction_drag_changed,
            sync_fsects_on_connection=self._sync_fsects_on_connection,
            apply_preview_to_sgfile=self.sync_preview_to_sgfile_if_loaded,
            runtime_api=ViewerRuntimeApi(preview_context=self._context),
            recalculate_elevations=self.recalculate_elevations,
        )

        self._set_default_view_bounds()

        assert hasattr(self, "_editor")

    @property
    def is_interaction_dragging(self) -> bool:
        return (
            self._interaction.is_dragging_node
            or self._interaction.is_dragging_section
        )

    def set_section_drag_enabled(self, enabled: bool) -> None:
        self._interaction.set_section_drag_enabled(enabled)

    def _widget_size(self) -> tuple[int, int]:
        return self._context.widget_size()

    def _widget_height(self) -> int:
        return self._context.widget_height()

    def widget_size(self) -> tuple[int, int]:
        return self._widget_size()

    @property
    def controller(self) -> PreviewStateController:
        return self._controller

    @property
    def transform_state(self) -> preview_state.TransformState:
        return self._transform_state

    @property
    def delete_section_active(self) -> bool:
        return self._delete_section_active

    @property
    def creation_active(self) -> bool:
        return self._creation_active()

    def _stop_panning(self) -> None:
        self._interaction_state.stop_panning()
        self._transform_controller.end_pan()

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
    def document(self) -> SGDocument:
        return self._document

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
            if self._emit_scale_changed is not None:
                self._emit_scale_changed(value.current_scale)

    def _set_transform_state(self, value: preview_state.TransformState) -> None:
        self._transform_state = value

    @property
    def _delete_section_active(self) -> bool:
        return self._editor.delete_section_active

    def _update_fit_scale(self) -> None:
        if self._drag_transform_active:
            return
        self._transform_controller.update_fit_scale(
            self._section_manager.sampled_bounds, self._widget_size()
        )
