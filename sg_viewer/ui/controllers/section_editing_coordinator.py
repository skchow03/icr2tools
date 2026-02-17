from __future__ import annotations

from typing import Protocol

from PyQt5 import QtWidgets

from sg_viewer.model.sg_model import SectionPreview
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
            self._host._section_table_window.on_sections_edited(self.apply_section_table_edits)

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
        self._host._window.preview.set_sections(sections)
        self.update_heading_table()

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
            self._host._xsect_table_window.on_xsects_edited(self.apply_xsect_table_edits)

        self._host._xsect_table_window.set_xsects(metadata)
        self._host._xsect_table_window.show()
        self._host._xsect_table_window.raise_()
        self._host._xsect_table_window.activateWindow()

    def update_xsect_table(self) -> None:
        if self._host._xsect_table_window is None:
            return
        metadata = self._host._window.preview.get_xsect_metadata()
        self._host._xsect_table_window.set_xsects(metadata)

    def apply_xsect_table_edits(self, entries: list[XsectEntry]) -> None:
        if not entries:
            return
        sorted_entries = sorted(entries, key=lambda entry: entry.dlat)
        if len(sorted_entries) < 2:
            return
        payload = [
            (entry.key if entry.key is not None and entry.key >= 0 else None, entry.dlat)
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

        new_selected = None
        if old_selected is not None:
            for idx, (key, _) in enumerate(payload):
                if key == old_selected:
                    new_selected = idx
                    break

        self._host._populate_xsect_choices(preferred_index=new_selected)
        self._host._refresh_elevation_profile()

    def copy_fsects_to_previous(self) -> None:
        self._sections_controller.copy_fsects_to_previous()

    def copy_fsects_to_next(self) -> None:
        self._sections_controller.copy_fsects_to_next()

    def copy_fsects_to_neighbor(self, *, direction: str) -> None:
        self._sections_controller.copy_fsects_to_neighbor(direction=direction)
