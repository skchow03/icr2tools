from __future__ import annotations

from sg_viewer.preview.geometry import (
    CURVE_SOLVE_TOLERANCE as CURVE_SOLVE_TOLERANCE_DEFAULT,
)
from sg_viewer.preview.runtime_ops_core import _RuntimeCoreMixin
from sg_viewer.preview.runtime_ops_editing import _RuntimeEditingMixin
from sg_viewer.preview.runtime_ops_loading import _RuntimeLoadingMixin
from sg_viewer.preview.runtime_ops_persistence import _RuntimePersistenceMixin


class PreviewRuntimeOps(
    _RuntimeCoreMixin,
    _RuntimeLoadingMixin,
    _RuntimeEditingMixin,
    _RuntimePersistenceMixin,
):
    """Preview interaction and data model logic."""

    CURVE_SOLVE_TOLERANCE = CURVE_SOLVE_TOLERANCE_DEFAULT  # inches

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
        super().__init__(
            context,
            sg_document,
            show_status,
            emit_selected_section_changed,
            emit_sections_changed,
            emit_new_straight_mode_changed,
            emit_new_curve_mode_changed,
            emit_delete_mode_changed,
            emit_split_section_mode_changed,
            emit_scale_changed,
            emit_interaction_drag_changed,
        )
