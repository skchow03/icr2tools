from __future__ import annotations

from time import perf_counter
from typing import Protocol

from PyQt5 import QtWidgets

from sg_viewer.model.sg_model import SectionPreview
from sg_viewer.geometry.topology import infer_section_connectivity
from sg_viewer.ui.heading_table_dialog import HeadingTableWindow
from sg_viewer.ui.section_table_dialog import SectionTableWindow
from sg_viewer.ui.xsect_table_dialog import XsectEntry, XsectTableWindow


class SectionEditingHost(Protocol):
    _window: QtWidgets.QMainWindow
    _section_table_window: SectionTableWindow | None
    _heading_table_window: HeadingTableWindow | None
    _xsect_table_window: XsectTableWindow | None

    def _current_xsect_index(self) -> int | None: ...
    def _populate_xsect_choices(self, preferred_index: int | None = None) -> None: ...
    def _refresh_elevation_profile(self) -> None: ...


class SectionEditingCoordinator:
    def __init__(self, host: SectionEditingHost, sections_controller: object) -> None:
        self._host = host
        self._sections_controller = sections_controller

    def show_section_table(self) -> None:
        sections, track_length = self._host._window.preview.get_section_set()
        if not sections:
            QtWidgets.QMessageBox.information(
                self._host._window, "No Sections", "Load an SG file to view sections."
            )
            return

        if self._host._section_table_window is None:
            self._host._section_table_window = SectionTableWindow(self._host._window)
            self._host._section_table_window.on_sections_edited(
                self.apply_section_table_edits
            )
            self._host._section_table_window.on_section_value_edited(
                self.apply_section_value_edit
            )

        self._host._section_table_window.set_sections(sections, track_length)
        self._host._section_table_window.show()
        self._host._section_table_window.raise_()
        self._host._section_table_window.activateWindow()

    def update_section_table(self) -> None:
        if self._host._section_table_window is None:
            return
        sections, track_length = self._host._window.preview.get_section_set()
        self._host._section_table_window.set_sections(sections, track_length)

    def apply_section_table_edits(self, sections: list[SectionPreview]) -> None:
        started = perf_counter()
        infer_section_connectivity(sections)
        self._host._window.preview.set_sections(sections)
        self.update_heading_table()
        print(
            f"[profiling] Section structural edit duration: {(perf_counter() - started) * 1000:.2f} ms"
        )

    def apply_section_value_edit(
        self,
        section_index: int,
        updated_section: SectionPreview,
        _neighbor_required: bool,
    ) -> None:
        started = perf_counter()
        sections, _track_length = self._host._window.preview.get_section_set()
        if not (0 <= section_index < len(sections)):
            return

        updated_sections = list(sections)
        updated_sections[section_index] = updated_section

        changed_indices = [section_index]
        if section_index + 1 < len(updated_sections):
            changed_indices.append(section_index + 1)

        geometry_started = perf_counter()
        self._host._window.preview.set_sections(
            updated_sections,
            changed_indices=changed_indices,
        )
        print(
            f"[profiling] Geometry recompute duration: {(perf_counter() - geometry_started) * 1000:.2f} ms"
        )
        self.update_heading_table()
        print(
            f"[profiling] Table cell edit duration: {(perf_counter() - started) * 1000:.2f} ms"
        )

    def show_heading_table(self) -> None:
        headings = self._host._window.preview.get_section_headings()
        if not headings:
            QtWidgets.QMessageBox.information(
                self._host._window, "No Headings", "Load an SG file to view headings."
            )
            return

        if self._host._heading_table_window is None:
            self._host._heading_table_window = HeadingTableWindow(self._host._window)

        self._host._heading_table_window.set_headings(headings)
        self._host._heading_table_window.show()
        self._host._heading_table_window.raise_()
        self._host._heading_table_window.activateWindow()

    def update_heading_table(self) -> None:
        if self._host._heading_table_window is None:
            return
        headings = self._host._window.preview.get_section_headings()
        self._host._heading_table_window.set_headings(headings)

    def show_xsect_table(self) -> None:
        metadata = self._host._window.preview.get_xsect_metadata()
        if not metadata:
            QtWidgets.QMessageBox.information(
                self._host._window,
                "No X-Sections",
                "Load an SG file to view X-section DLAT values.",
            )
            return

        if self._host._xsect_table_window is None:
            self._host._xsect_table_window = XsectTableWindow(self._host._window)
            self._host._xsect_table_window.on_xsects_edited(
                self.apply_xsect_table_edits
            )

        self._host._xsect_table_window.set_display_unit(
            unit_label=self._host._window.fsect_display_unit_label(),
            decimals=self._host._window.fsect_display_decimals(),
            to_display_units=self._host._window.fsect_dlat_to_display_units,
            from_display_units=self._host._window.fsect_dlat_from_display_units,
            altitude_unit_label=self._host._window.xsect_altitude_unit_label(),
            altitude_decimals=self._host._window.xsect_altitude_display_decimals(),
            altitude_to_display_units=self._host._window.xsect_altitude_to_display_units,
            altitude_from_display_units=self._host._window.xsect_altitude_from_display_units,
        )
        altitudes, grades = self._current_section_xsect_values()
        self._host._xsect_table_window.set_xsects(metadata, altitudes, grades)
        self._host._xsect_table_window.show()
        self._host._xsect_table_window.raise_()
        self._host._xsect_table_window.activateWindow()

    def update_xsect_table(self) -> None:
        if self._host._xsect_table_window is None:
            return
        metadata = self._host._window.preview.get_xsect_metadata()
        self._host._xsect_table_window.set_display_unit(
            unit_label=self._host._window.fsect_display_unit_label(),
            decimals=self._host._window.fsect_display_decimals(),
            to_display_units=self._host._window.fsect_dlat_to_display_units,
            from_display_units=self._host._window.fsect_dlat_from_display_units,
            altitude_unit_label=self._host._window.xsect_altitude_unit_label(),
            altitude_decimals=self._host._window.xsect_altitude_display_decimals(),
            altitude_to_display_units=self._host._window.xsect_altitude_to_display_units,
            altitude_from_display_units=self._host._window.xsect_altitude_from_display_units,
        )
        altitudes, grades = self._current_section_xsect_values()
        self._host._xsect_table_window.set_xsects(metadata, altitudes, grades)

    def _current_section_xsect_values(
        self,
    ) -> tuple[list[int | None] | None, list[int | None] | None]:
        selection = self._host._active_selection
        if selection is None:
            return None, None
        return (
            self._host._window.preview.get_section_xsect_altitudes(selection.index),
            self._host._window.preview.get_section_xsect_grades(selection.index),
        )

    def apply_xsect_table_edits(self, entries: list[XsectEntry]) -> None:
        if not entries:
            return
        sorted_entries = sorted(entries, key=lambda entry: entry.dlat)
        if len(sorted_entries) < 2:
            return
        payload = [
            (
                entry.key if entry.key is not None and entry.key >= 0 else None,
                entry.dlat,
            )
            for entry in sorted_entries
        ]
        old_selected = self._host._current_xsect_index()
        if not self._host._window.preview.set_xsect_definitions(payload):
            QtWidgets.QMessageBox.warning(
                self._host._window,
                "X-Section Table",
                "Unable to update X-section DLAT values.",
            )
            return

        selection = self._host._active_selection
        if selection is not None:
            for row, entry in enumerate(sorted_entries):
                if entry.altitude is not None:
                    self._host._window.preview.set_section_xsect_altitude(
                        selection.index, row, entry.altitude, validate=False
                    )
                if entry.grade is not None:
                    self._host._window.preview.set_section_xsect_grade(
                        selection.index, row, entry.grade, validate=False
                    )

        new_selected = None
        if old_selected is not None:
            for idx, (key, _) in enumerate(payload):
                if key == old_selected:
                    new_selected = idx
                    break

        self._host._populate_xsect_choices(preferred_index=new_selected)
        self._host._refresh_elevation_profile()
        self._host._sync_after_xsect_value_change()

    def connect_signals(self) -> None:
        host = self._host
        window = host._window
        window.xsect_dlat_line_checkbox.toggled.connect(
            window.preview.set_show_xsect_dlat_line
        )
        window.copy_fsects_prev_button.clicked.connect(self.copy_fsects_to_previous)
        host._copy_fsects_prev_action.triggered.connect(self.copy_fsects_to_previous)
        window.copy_fsects_next_button.clicked.connect(self.copy_fsects_to_next)
        host._copy_fsects_next_action.triggered.connect(self.copy_fsects_to_next)
        window.add_fsect_button.clicked.connect(host._add_fsect_below_selected)
        host._add_fsect_action.triggered.connect(host._add_fsect_below_selected)
        window.delete_fsect_button.clicked.connect(host._delete_selected_fsect)
        host._delete_fsect_action.triggered.connect(host._delete_selected_fsect)
        window.fsect_table.itemSelectionChanged.connect(host._update_fsect_edit_buttons)
        window.move_fsect_up_button.clicked.connect(host._move_selected_fsect_up)
        host._move_fsect_up_action.triggered.connect(host._move_selected_fsect_up)
        window.move_fsect_down_button.clicked.connect(host._move_selected_fsect_down)
        host._move_fsect_down_action.triggered.connect(host._move_selected_fsect_down)
        window.swap_fsect_types_button.clicked.connect(
            self.swap_fsect_type_across_sections
        )
        host._swap_fsect_types_action.triggered.connect(
            self.swap_fsect_type_across_sections
        )
        window.edit_xsect_list_button.clicked.connect(self.show_xsect_table)
        window.xsect_elevation_widget.xsectClicked.connect(host._on_xsect_node_clicked)
        window.xsect_elevation_table.itemSelectionChanged.connect(
            host._on_xsect_table_selection_changed
        )
        window.xsect_elevation_table.cellChanged.connect(
            host._on_xsect_table_cell_changed
        )
        window.fsectDiagramDlatChangeRequested.connect(
            host._on_fsect_diagram_dlat_change_requested
        )
        window.fsectDiagramDragRefreshRequested.connect(
            window.preview.refresh_fsections_preview_lightweight
        )
        window.fsectDiagramDragCommitRequested.connect(
            host._on_fsect_diagram_drag_commit_requested
        )

    def copy_fsects_to_previous(self) -> None:
        self._sections_controller.copy_fsects_to_previous()

    def copy_fsects_to_next(self) -> None:
        self._sections_controller.copy_fsects_to_next()

    def copy_fsects_to_neighbor(self, *, direction: str) -> None:
        self._sections_controller.copy_fsects_to_neighbor(direction=direction)

    def swap_fsect_type_across_sections(self) -> None:
        self._sections_controller.swap_fsect_type_across_sections()
