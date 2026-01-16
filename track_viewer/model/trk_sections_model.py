"""Table model for TRK section geometry."""
from __future__ import annotations

from PyQt5 import QtCore

from icr2_core.trk.trk_utils import ground_type_name


class TrkSectionsModel(QtCore.QAbstractTableModel):
    """Table model for TRK section geometry."""

    _BASE_HEADERS = [
        "Section",
        "Type",
        "Start DLONG",
        "Length",
    ]

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._sections: list[object] = []
        self._headers: list[str] = list(self._BASE_HEADERS)
        self._max_bounds = 0
        self._max_surfaces = 0

    def rowCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._sections)

    def columnCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._headers)

    def data(
        self, index: QtCore.QModelIndex, role: int = QtCore.Qt.DisplayRole
    ) -> object | None:
        if not index.isValid():
            return None
        row = index.row()
        if row < 0 or row >= len(self._sections):
            return None
        section = self._sections[row]
        column = index.column()
        if role == QtCore.Qt.TextAlignmentRole:
            if column == 1:
                return QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter
            return QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
        if role != QtCore.Qt.DisplayRole:
            return None
        if column == 0:
            return str(row)
        if column == 1:
            if section.type == 1:
                return "Straight"
            if section.type == 2:
                return "Curve"
            return f"Type {section.type}"
        if column == 2:
            return str(section.start_dlong)
        if column == 3:
            return str(section.length)
        boundary_base = len(self._BASE_HEADERS)
        surface_base = boundary_base + self._max_bounds * 2
        if boundary_base <= column < surface_base:
            bound_index = (column - boundary_base) // 2
            if bound_index >= len(section.bound_dlat_start):
                return ""
            if (column - boundary_base) % 2 == 0:
                return str(section.bound_dlat_start[bound_index])
            return str(section.bound_dlat_end[bound_index])
        if column >= surface_base:
            surface_index = (column - surface_base) // 3
            if surface_index >= len(section.ground_dlat_start):
                return ""
            offset = (column - surface_base) % 3
            if offset == 0:
                return str(section.ground_dlat_start[surface_index])
            if offset == 1:
                return str(section.ground_dlat_end[surface_index])
            ground_type = section.ground_type[surface_index]
            name = ground_type_name(ground_type)
            return name or str(ground_type)
        return None

    def flags(self, index: QtCore.QModelIndex) -> QtCore.Qt.ItemFlags:
        if not index.isValid():
            return QtCore.Qt.NoItemFlags
        return QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable

    def headerData(
        self,
        section: int,
        orientation: QtCore.Qt.Orientation,
        role: int = QtCore.Qt.DisplayRole,
    ) -> object | None:
        if role != QtCore.Qt.DisplayRole:
            return None
        if orientation == QtCore.Qt.Horizontal:
            if 0 <= section < len(self._headers):
                return self._headers[section]
            return None
        return str(section)

    def set_sections(self, sections: list[object]) -> None:
        self.beginResetModel()
        self._sections = list(sections)
        self._max_bounds = max(
            (len(sect.bound_dlat_start) for sect in sections), default=0
        )
        self._max_surfaces = max(
            (len(sect.ground_dlat_start) for sect in sections), default=0
        )
        self._headers = list(self._BASE_HEADERS)
        for bound_index in range(self._max_bounds):
            label = bound_index + 1
            self._headers.append(f"Boundary {label} Start DLAT")
            self._headers.append(f"Boundary {label} End DLAT")
        for surface_index in range(self._max_surfaces):
            label = surface_index + 1
            self._headers.append(f"Surface {label} Start DLAT")
            self._headers.append(f"Surface {label} End DLAT")
            self._headers.append(f"Surface {label} Type")
        self.endResetModel()
