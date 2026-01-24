from __future__ import annotations

from typing import Iterable

from PyQt5 import QtCore
import numpy as np

from icr2_core.trk.sg_classes import SGFile
from sg_viewer.sg_document_fsects import (
    FSection,
    delete_fsection,
    insert_fsection,
    replace_fsections,
    update_fsection,
)


class SGDocument(QtCore.QObject):
    section_changed = QtCore.pyqtSignal(int)
    geometry_changed = QtCore.pyqtSignal()
    metadata_changed = QtCore.pyqtSignal()

    ELEVATION_MIN = -1_000_000
    ELEVATION_MAX = 1_000_000

    def __init__(self, sg_data: SGFile | None = None, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._sg_data = sg_data
        if self._sg_data is not None:
            self.validate()

    @property
    def sg_data(self) -> SGFile | None:
        return self._sg_data

    def set_sg_data(self, sg_data: SGFile | None, *, validate: bool = True) -> None:
        self._sg_data = sg_data
        if self._sg_data is not None and validate:
            self.validate()
        self.metadata_changed.emit()
        self.geometry_changed.emit()

    def set_section_elevation(self, section_id: int, new_value: float) -> None:
        if self._sg_data is None:
            raise ValueError("No SG data loaded.")

        if section_id < 0 or section_id >= len(self._sg_data.sects):
            raise IndexError("Section index out of range.")

        section = self._sg_data.sects[section_id]
        if not section.alt:
            raise ValueError("Section has no elevation data.")

        updated = int(round(new_value))
        section.alt = [updated for _ in section.alt]

        if __debug__:
            self.validate()

        self.section_changed.emit(section_id)
        self.geometry_changed.emit()

    def set_section_xsect_altitude(
        self, section_id: int, xsect_index: int, new_value: float
    ) -> None:
        if self._sg_data is None:
            raise ValueError("No SG data loaded.")

        if section_id < 0 or section_id >= len(self._sg_data.sects):
            raise IndexError("Section index out of range.")

        if xsect_index < 0 or xsect_index >= self._sg_data.num_xsects:
            raise IndexError("X-section index out of range.")

        section = self._sg_data.sects[section_id]
        if not section.alt or xsect_index >= len(section.alt):
            raise ValueError("Section has no elevation data.")

        updated = int(round(new_value))
        section.alt[xsect_index] = updated

        if __debug__:
            self.validate()

        self.section_changed.emit(section_id)
        self.geometry_changed.emit()

    def set_section_xsect_grade(
        self, section_id: int, xsect_index: int, new_value: float
    ) -> None:
        if self._sg_data is None:
            raise ValueError("No SG data loaded.")

        if section_id < 0 or section_id >= len(self._sg_data.sects):
            raise IndexError("Section index out of range.")

        if xsect_index < 0 or xsect_index >= self._sg_data.num_xsects:
            raise IndexError("X-section index out of range.")

        section = self._sg_data.sects[section_id]
        if not section.grade or xsect_index >= len(section.grade):
            raise ValueError("Section has no grade data.")

        updated = int(round(new_value))
        section.grade[xsect_index] = updated

        if __debug__:
            self.validate()

        self.section_changed.emit(section_id)
        self.geometry_changed.emit()

    def copy_xsect_data_to_all(self, xsect_index: int) -> None:
        if self._sg_data is None:
            raise ValueError("No SG data loaded.")

        if xsect_index < 0 or xsect_index >= self._sg_data.num_xsects:
            raise IndexError("X-section index out of range.")

        if not self._sg_data.sects:
            raise ValueError("No sections available to update.")

        for idx, section in enumerate(self._sg_data.sects):
            if not section.alt or xsect_index >= len(section.alt):
                raise ValueError(f"Section {idx} has no elevation data.")
            if not section.grade or xsect_index >= len(section.grade):
                raise ValueError(f"Section {idx} has no grade data.")

        num_xsects = self._sg_data.num_xsects
        for section in self._sg_data.sects:
            altitude = int(section.alt[xsect_index])
            grade = int(section.grade[xsect_index])
            section.alt = [altitude for _ in range(num_xsects)]
            section.grade = [grade for _ in range(num_xsects)]

        if __debug__:
            self.validate()

        self.geometry_changed.emit()

    def set_xsect_definitions(self, entries: list[tuple[int | None, float]]) -> None:
        if self._sg_data is None:
            raise ValueError("No SG data loaded.")

        if len(entries) < 2:
            raise ValueError("At least two X-sections are required.")
        if len(entries) > 10:
            raise ValueError("At most ten X-sections are supported.")

        num_existing = int(self._sg_data.num_xsects)
        used_indices: set[int] = set()
        index_map: list[int | None] = []
        dlats: list[int] = []

        for key, dlat in entries:
            if key is None:
                index_map.append(None)
            else:
                index = int(key)
                if index < 0 or index >= num_existing:
                    raise IndexError("X-section index out of range.")
                if index in used_indices:
                    raise ValueError("Duplicate X-section entries provided.")
                used_indices.add(index)
                index_map.append(index)
            dlats.append(int(round(dlat)))

        dtype = getattr(self._sg_data.xsect_dlats, "dtype", np.int32)
        self._sg_data.xsect_dlats = np.array(dlats, dtype=dtype)
        self._sg_data.num_xsects = len(dlats)
        if len(self._sg_data.header) > 5:
            self._sg_data.header[5] = len(dlats)

        for section in self._sg_data.sects:
            altitudes = list(getattr(section, "alt", []))
            grades = list(getattr(section, "grade", []))
            new_altitudes: list[int] = []
            new_grades: list[int] = []
            for source in index_map:
                if source is None:
                    new_altitudes.append(0)
                    new_grades.append(0)
                else:
                    if source >= len(altitudes) or source >= len(grades):
                        raise ValueError("Section elevation data is incomplete.")
                    new_altitudes.append(int(altitudes[source]))
                    new_grades.append(int(grades[source]))
            section.alt = new_altitudes
            section.grade = new_grades

        if __debug__:
            self.validate()

        self.metadata_changed.emit()
        self.geometry_changed.emit()

    def rebuild_dlongs(self, start_index: int = 0, start_dlong: int = 0) -> None:
        if self._sg_data is None:
            raise ValueError("No SG data loaded.")

        self._sg_data.rebuild_dlongs(start_index, start_dlong)

        if __debug__:
            self.validate()

        self.geometry_changed.emit()

    def add_fsection(self, section_id: int, index: int, fsect: FSection) -> None:
        if self._sg_data is None:
            raise ValueError("No SG data loaded.")

        insert_fsection(self._sg_data, section_id, index, fsect)

        self.section_changed.emit(section_id)
        self.geometry_changed.emit()

    def edit_fsection(self, section_id: int, index: int, **fields: object) -> None:
        if self._sg_data is None:
            raise ValueError("No SG data loaded.")

        update_fsection(self._sg_data, section_id, index, **fields)

        self.section_changed.emit(section_id)
        self.geometry_changed.emit()

    def remove_fsection(self, section_id: int, index: int) -> None:
        if self._sg_data is None:
            raise ValueError("No SG data loaded.")

        delete_fsection(self._sg_data, section_id, index)

        self.section_changed.emit(section_id)
        self.geometry_changed.emit()

    def replace_fsections(self, section_id: int, fsects: list[FSection]) -> None:
        if self._sg_data is None:
            raise ValueError("No SG data loaded.")

        replace_fsections(self._sg_data, section_id, fsects)

        self.section_changed.emit(section_id)
        self.geometry_changed.emit()

    def validate(self) -> None:
        sg_data = self._sg_data
        if sg_data is None:
            return

        if sg_data.num_sects != len(sg_data.sects):
            raise ValueError("Section count does not match SG header.")

        self._validate_section_links(sg_data.sects)
        self._validate_dlongs(sg_data.sects)
        self._validate_elevations(sg_data)

    def _validate_section_links(self, sections: Iterable[object]) -> None:
        sections_list = list(sections)
        total = len(sections_list)
        if total == 0:
            return

        for idx, section in enumerate(sections_list):
            sec_prev = int(getattr(section, "sec_prev", -1))
            sec_next = int(getattr(section, "sec_next", -1))

            expected_prev = idx - 1
            expected_next = idx + 1
            if idx == 0 and total > 1:
                expected_prev = total - 1
            if idx == total - 1 and total > 1:
                expected_next = 0

            if sec_prev not in (-1, expected_prev):
                raise ValueError(f"Section {idx} has invalid previous index {sec_prev}.")
            if sec_next not in (-1, expected_next):
                raise ValueError(f"Section {idx} has invalid next index {sec_next}.")

    def _validate_dlongs(self, sections: Iterable[object]) -> None:
        last_start = None
        for idx, section in enumerate(sections):
            start_dlong = float(getattr(section, "start_dlong", 0.0))
            length = float(getattr(section, "length", 0.0))

            if last_start is not None and start_dlong < last_start:
                raise ValueError(
                    f"Section {idx} start_dlong {start_dlong} is less than previous {last_start}."
                )

            if length < 0:
                raise ValueError(f"Section {idx} has negative length {length}.")

            last_start = start_dlong

    def _validate_elevations(self, sg_data: SGFile) -> None:
        num_xsects = sg_data.num_xsects
        for idx, section in enumerate(sg_data.sects):
            altitudes = list(getattr(section, "alt", []))
            if len(altitudes) != num_xsects:
                raise ValueError(
                    f"Section {idx} elevation count {len(altitudes)} does not match {num_xsects}."
                )
            for altitude in altitudes:
                if altitude < self.ELEVATION_MIN or altitude > self.ELEVATION_MAX:
                    raise ValueError(
                        f"Section {idx} elevation {altitude} outside bounds."
                    )
            grades = list(getattr(section, "grade", []))
            if len(grades) != num_xsects:
                raise ValueError(
                    f"Section {idx} grade count {len(grades)} does not match {num_xsects}."
                )
