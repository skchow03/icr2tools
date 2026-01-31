from __future__ import annotations

from sg_viewer.geometry.dlong import set_start_finish
from sg_viewer.geometry.topology import is_closed_loop


class _RuntimeCoreCommitOpsMixin:
    def _finalize_new_straight(self) -> None:
        was_closed = is_closed_loop(self._section_manager.sections)
        updated_sections, track_length, new_index, status = (
            self._editor.finalize_new_straight(
                self._section_manager.sections, self._track_length
            )
        )
        if new_index is None:
            return

        self._track_length = track_length
        source_index = None
        source_endtype = None
        connection = self._creation_controller.straight_interaction.connection
        if connection is not None:
            source_index, source_endtype = connection
        self._insert_fsects_by_section(new_index, source_index, source_endtype)
        if not was_closed and is_closed_loop(updated_sections):
            if not self._has_fsections():
                order = self._closed_loop_order(updated_sections)
                if order and len(order) == len(self._fsects_by_section):
                    self._fsects_by_section = [self._fsects_by_section[i] for i in order]
                    if new_index in order:
                        new_index = order.index(new_index)
                updated_sections = set_start_finish(updated_sections, 0)
        self.set_sections(updated_sections)
        self._validate_section_fsects_alignment()
        self._selection.set_selected_section(new_index)
        self._apply_creation_update(self._creation_controller.finish_straight(status))

    def _finalize_new_curve(self) -> None:
        was_closed = is_closed_loop(self._section_manager.sections)
        updated_sections, track_length, new_index, status = self._editor.finalize_new_curve(
            self._section_manager.sections, self._track_length
        )
        if new_index is None:
            return

        self._track_length = track_length
        source_index = None
        source_endtype = None
        connection = self._creation_controller.curve_interaction.connection
        if connection is not None:
            source_index, source_endtype = connection
        self._insert_fsects_by_section(new_index, source_index, source_endtype)
        if not was_closed and is_closed_loop(updated_sections):
            if not self._has_fsections():
                order = self._closed_loop_order(updated_sections)
                if order and len(order) == len(self._fsects_by_section):
                    self._fsects_by_section = [self._fsects_by_section[i] for i in order]
                    if new_index in order:
                        new_index = order.index(new_index)
                updated_sections = set_start_finish(updated_sections, 0)
        self.set_sections(updated_sections)
        self._validate_section_fsects_alignment()
        self._selection.set_selected_section(new_index)
        self._apply_creation_update(self._creation_controller.finish_curve(status))

    def _next_section_start_dlong(self) -> float:
        return self._editor.next_section_start_dlong(self._section_manager.sections)
