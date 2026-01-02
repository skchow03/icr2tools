"""LP editing logic for the track preview widget."""
from __future__ import annotations

from PyQt5 import QtCore

from track_viewer.widget.selection.selection_controller import SelectionController


class LpEditController:
    """Handles LP record selection."""

    def __init__(
        self,
        selection: SelectionController,
    ) -> None:
        self._selection = selection

    def select_lp_record_at_point(
        self, point: QtCore.QPointF, lp_name: str, size: QtCore.QSize
    ) -> bool:
        lp_index = self._selection.lp_record_at_point(point, lp_name, size)
        if lp_index is None:
            return False
        self._selection.select_lp_record(lp_name, lp_index)
        return True
