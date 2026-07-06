from __future__ import annotations

from collections import defaultdict
from typing import Callable

from PyQt5 import QtCore, QtWidgets

from sg_viewer.io.track3d_catalog import Track3DCatalog


class Track3DCatalogInspectorDialog(QtWidgets.QDialog):
    """Read-only inspector for parsed track .3D catalog data."""

    def __init__(
        self,
        catalog: Track3DCatalog,
        *,
        path_text: str,
        current_section: int | None = None,
        jump_to_section: Callable[[int], None] | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._catalog = catalog
        self._current_section = current_section
        self._jump_to_section = jump_to_section
        self.setWindowTitle(".3D Catalog Inspector (read-only)")
        self.resize(980, 720)

        layout = QtWidgets.QVBoxLayout(self)
        title = QtWidgets.QLabel(f"Catalog: {path_text}")
        title.setWordWrap(True)
        layout.addWidget(title)

        self._filter_combo = QtWidgets.QComboBox()
        self._filter_combo.addItem("All sections", None)
        sections = sorted(
            {s.section for s in catalog.section_summary}
            | {o.section for o in catalog.object_lists.values()}
            | {d.section for d in catalog.detail_lists.values()}
            | {f.section for f in catalog.faces}
        )
        for section in sections:
            self._filter_combo.addItem(f"Section {section}", section)
        if current_section in sections:
            self._filter_combo.setCurrentIndex(self._filter_combo.findData(current_section))

        self._lod_filter_combo = QtWidgets.QComboBox()
        self._lod_filter_combo.addItem("HI, MED and LO", None)
        for lod in ("HI", "MED", "LO"):
            self._lod_filter_combo.addItem(lod, lod)

        filter_row = QtWidgets.QHBoxLayout()
        filter_row.addWidget(QtWidgets.QLabel("Section:"))
        filter_row.addWidget(self._filter_combo, stretch=1)
        filter_row.addWidget(QtWidgets.QLabel("LOD:"))
        filter_row.addWidget(self._lod_filter_combo)
        current_button = QtWidgets.QPushButton("Show current SG section")
        current_button.setEnabled(current_section is not None and current_section in sections)
        current_button.clicked.connect(self._filter_current_section)
        filter_row.addWidget(current_button)
        layout.addLayout(filter_row)

        counts = ", ".join(f"{name}: {value}" for name, value in sorted(catalog.counts.items()))
        self._counts_label = QtWidgets.QLabel(f"Counts: {counts}")
        self._counts_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        layout.addWidget(self._counts_label)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        layout.addWidget(splitter, stretch=1)

        self._tabs = QtWidgets.QTabWidget()
        splitter.addWidget(self._tabs)

        self._section_table = self._make_table(["Section", "Subsection", "LOD", "DLONG start", "DLONG end", "ObjectLists", "DetailLists", "Section lists"])
        self._objects_tree = QtWidgets.QTreeWidget()
        self._objects_tree.setHeaderLabels(["Section / side / ObjectList", "TSO IDs", "Extern names", "Line"])
        self._details_tree = QtWidgets.QTreeWidget()
        self._details_tree.setHeaderLabels(["Section / LOD / DetailList", "Items", "TSO extern names", "Line"])
        self._tso_table = self._make_table(["ID", "Extern", "X", "Y", "Z", "Rot", "Line"])
        self._face_table = self._make_table(["Label", "Section", "Sub", "LOD", "DLONG range", "Materials", "ObjectLists", "Line"])
        self._tabs.addTab(self._section_table, "Sections")
        self._tabs.addTab(self._objects_tree, "ObjectLists")
        self._tabs.addTab(self._details_tree, "DetailLists")
        self._tabs.addTab(self._tso_table, "TSOs")
        self._tabs.addTab(self._face_table, "FACE blocks")

        details_group = QtWidgets.QGroupBox("Selected source/details")
        details_layout = QtWidgets.QVBoxLayout(details_group)
        self._details = QtWidgets.QPlainTextEdit()
        self._details.setReadOnly(True)
        details_layout.addWidget(self._details)
        splitter.addWidget(details_group)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        button_row = QtWidgets.QHBoxLayout()
        copy_button = QtWidgets.QPushButton("Copy selected labels/IDs")
        copy_button.clicked.connect(self._copy_selected)
        jump_button = QtWidgets.QPushButton("Jump SG to selected section")
        jump_button.setEnabled(jump_to_section is not None)
        jump_button.clicked.connect(self._jump_selected_section)
        close_button = QtWidgets.QPushButton("Close")
        close_button.clicked.connect(self.accept)
        button_row.addWidget(copy_button)
        button_row.addWidget(jump_button)
        button_row.addStretch(1)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        self._filter_combo.currentIndexChanged.connect(self._populate)
        self._lod_filter_combo.currentIndexChanged.connect(self._populate)
        self._section_table.itemSelectionChanged.connect(self._show_selected_details)
        self._tso_table.itemSelectionChanged.connect(self._show_selected_details)
        self._face_table.itemSelectionChanged.connect(self._show_selected_details)
        self._objects_tree.itemSelectionChanged.connect(self._show_selected_details)
        self._details_tree.itemSelectionChanged.connect(self._show_selected_details)
        self._populate()

    @staticmethod
    def _make_table(headers: list[str]) -> QtWidgets.QTableWidget:
        table = QtWidgets.QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        table.horizontalHeader().setStretchLastSection(True)
        table.setWordWrap(True)
        table.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        return table

    @staticmethod
    def _resize_table_to_wrapped_contents(table: QtWidgets.QTableWidget, max_column_width: int = 260) -> None:
        table.resizeColumnsToContents()
        for col in range(table.columnCount()):
            if table.columnWidth(col) > max_column_width:
                table.setColumnWidth(col, max_column_width)
        table.resizeRowsToContents()

    def _filter_section(self) -> int | None:
        return self._filter_combo.currentData()

    def _include_section(self, section: int) -> bool:
        selected = self._filter_section()
        return selected is None or section == selected

    def _filter_lod(self) -> str | None:
        value = self._lod_filter_combo.currentData()
        return value if isinstance(value, str) else None

    def _include_lod(self, lod: str) -> bool:
        selected = self._filter_lod()
        return selected is None or lod == selected

    @staticmethod
    def _item(text: object, copy_text: str | None = None, details: str | None = None, section: int | None = None) -> QtWidgets.QTableWidgetItem:
        item = QtWidgets.QTableWidgetItem(str(text))
        item.setData(QtCore.Qt.UserRole, copy_text if copy_text is not None else str(text))
        item.setData(QtCore.Qt.UserRole + 1, details or "")
        item.setData(QtCore.Qt.UserRole + 2, section)
        return item

    def _populate(self) -> None:
        self._populate_sections()
        self._populate_objects()
        self._populate_detail_lists()
        self._populate_tsos()
        self._populate_faces()
        self._details.clear()

    def _populate_sections(self) -> None:
        section_lists_by_section: dict[int, list[str]] = defaultdict(list)
        for label, section_list in self._catalog.section_lists.items():
            section_lists_by_section[section_list.section].append(label)

        rows = [
            face
            for face in sorted(
                self._catalog.faces,
                key=lambda f: (f.section, f.subsection, ("HI", "MED", "LO").index(f.lod) if f.lod in ("HI", "MED", "LO") else 99, f.line),
            )
            if self._include_section(face.section) and self._include_lod(face.lod)
        ]
        self._section_table.setRowCount(len(rows))
        for row, face in enumerate(rows):
            section_lists = sorted(section_lists_by_section.get(face.section, []))
            values = [
                face.section,
                face.subsection,
                face.lod,
                "–" if face.dlong_start is None else face.dlong_start,
                "–" if face.dlong_end is None else face.dlong_end,
                ", ".join(face.object_lists),
                ", ".join(face.detail_lists),
                ", ".join(section_lists),
            ]
            details = (
                f"{face.label}\n"
                f"Section {face.section}, subsection {face.subsection}, LOD {face.lod}\n"
                f"DLONG start: {face.dlong_start if face.dlong_start is not None else '–'}\n"
                f"DLONG end: {face.dlong_end if face.dlong_end is not None else '–'}\n"
                f"ObjectLists: {', '.join(face.object_lists)}\n"
                f"DetailLists: {', '.join(face.detail_lists)}\n"
                f"Section lists: {', '.join(section_lists)}\n\n"
                f"{face.span.text}"
            )
            for col, value in enumerate(values):
                copy_text = face.label if col == 0 else None
                self._section_table.setItem(row, col, self._item(value, copy_text, details, face.section))
        self._resize_table_to_wrapped_contents(self._section_table)

    def _populate_objects(self) -> None:
        self._objects_tree.clear()
        grouped: dict[int, dict[str, list[tuple[str, object]]]] = defaultdict(lambda: defaultdict(list))
        for label, obj in sorted(self._catalog.object_lists.items(), key=lambda kv: (kv[1].section, kv[1].side, kv[1].subsection, kv[0])):
            if self._include_section(obj.section):
                grouped[obj.section][obj.side].append((label, obj))
        for section, sides in sorted(grouped.items()):
            section_item = QtWidgets.QTreeWidgetItem([f"Section {section}", "", "", ""])
            section_item.setData(0, QtCore.Qt.UserRole, str(section))
            section_item.setData(0, QtCore.Qt.UserRole + 2, section)
            for side, entries in sorted(sides.items()):
                side_item = QtWidgets.QTreeWidgetItem([f"Side {side}", "", "", ""])
                side_item.setData(0, QtCore.Qt.UserRole, side)
                side_item.setData(0, QtCore.Qt.UserRole + 2, section)
                for label, obj in entries:
                    details = obj.span.text
                    child = QtWidgets.QTreeWidgetItem([label, ", ".join(obj.items), ", ".join(x or "?" for x in obj.externs), str(obj.line)])
                    child.setData(0, QtCore.Qt.UserRole, label)
                    child.setData(0, QtCore.Qt.UserRole + 1, details)
                    child.setData(0, QtCore.Qt.UserRole + 2, section)
                    side_item.addChild(child)
                section_item.addChild(side_item)
            self._objects_tree.addTopLevelItem(section_item)
        self._objects_tree.expandAll()
        for col in range(self._objects_tree.columnCount()):
            self._objects_tree.resizeColumnToContents(col)

    def _populate_detail_lists(self) -> None:
        self._details_tree.clear()
        grouped: dict[int, dict[str, list[tuple[str, object]]]] = defaultdict(lambda: defaultdict(list))
        lod_order = {"H": 0, "M": 1, "L": 2, "": 3}
        for label, detail in sorted(
            self._catalog.detail_lists.items(),
            key=lambda kv: (kv[1].section, lod_order.get(kv[1].lod_suffix, 99), kv[1].subsection, kv[0]),
        ):
            if self._include_section(detail.section):
                grouped[detail.section][detail.lod_suffix or "unspecified"].append((label, detail))
        for section, lods in sorted(grouped.items()):
            section_item = QtWidgets.QTreeWidgetItem([f"Section {section}", "", "", ""])
            section_item.setData(0, QtCore.Qt.UserRole, str(section))
            section_item.setData(0, QtCore.Qt.UserRole + 2, section)
            for lod, entries in sorted(lods.items(), key=lambda kv: lod_order.get(kv[0], 99)):
                lod_item = QtWidgets.QTreeWidgetItem([f"LOD {lod}", "", "", ""])
                lod_item.setData(0, QtCore.Qt.UserRole, lod)
                lod_item.setData(0, QtCore.Qt.UserRole + 2, section)
                for label, detail in entries:
                    details = (
                        f"{label}\n"
                        f"Section {detail.section}, subsection {detail.subsection}, LOD suffix {detail.lod_suffix or '–'}\n"
                        f"Items: {', '.join(detail.items)}\n"
                        f"TSO extern names: {', '.join(x or '?' for x in detail.externs)}\n\n"
                        f"{detail.span.text}"
                    )
                    child = QtWidgets.QTreeWidgetItem(
                        [
                            label,
                            ", ".join(detail.items),
                            ", ".join(x or "?" for x in detail.externs),
                            str(detail.line),
                        ]
                    )
                    child.setData(0, QtCore.Qt.UserRole, label)
                    child.setData(0, QtCore.Qt.UserRole + 1, details)
                    child.setData(0, QtCore.Qt.UserRole + 2, section)
                    lod_item.addChild(child)
                section_item.addChild(lod_item)
            self._details_tree.addTopLevelItem(section_item)
        self._details_tree.expandAll()
        for col in range(self._details_tree.columnCount()):
            self._details_tree.resizeColumnToContents(col)

    def _populate_tsos(self) -> None:
        section_filter = self._filter_section()
        allowed_ids = None
        if section_filter is not None:
            allowed_ids = {item for obj in self._catalog.object_lists.values() if obj.section == section_filter for item in obj.items}
        rows = [(label, tso) for label, tso in sorted(self._catalog.tsos.items()) if allowed_ids is None or label in allowed_ids]
        self._tso_table.setRowCount(len(rows))
        for row, (label, tso) in enumerate(rows):
            values = [label, tso.extern, tso.x, tso.y, tso.z, tso.rot, tso.line]
            for col, value in enumerate(values):
                self._tso_table.setItem(row, col, self._item(value, label if col == 0 else None, tso.span.text, None))
        self._resize_table_to_wrapped_contents(self._tso_table)

    def _populate_faces(self) -> None:
        faces = [f for f in self._catalog.faces if self._include_section(f.section) and self._include_lod(f.lod)]
        self._face_table.setRowCount(len(faces))
        for row, face in enumerate(faces):
            dlong = "–" if face.dlong_start is None else f"{face.dlong_start}-{face.dlong_end}"
            values = [face.label, face.section, face.subsection, face.lod, dlong, ", ".join(face.materials), ", ".join(face.object_lists), face.line]
            for col, value in enumerate(values):
                self._face_table.setItem(row, col, self._item(value, face.label if col == 0 else None, face.span.text, face.section))
        self._resize_table_to_wrapped_contents(self._face_table)

    def _filter_current_section(self) -> None:
        if self._current_section is None:
            return
        index = self._filter_combo.findData(self._current_section)
        if index >= 0:
            self._filter_combo.setCurrentIndex(index)

    def _selected_payload(self) -> tuple[str, str, int | None]:
        widget = self._tabs.currentWidget()
        if widget in (self._objects_tree, self._details_tree):
            tree = widget if isinstance(widget, QtWidgets.QTreeWidget) else self._objects_tree
            item = tree.currentItem()
            if item is None:
                return "", "", None
            return str(item.data(0, QtCore.Qt.UserRole) or item.text(0)), str(item.data(0, QtCore.Qt.UserRole + 1) or ""), item.data(0, QtCore.Qt.UserRole + 2)
        table = widget if isinstance(widget, QtWidgets.QTableWidget) else None
        if table is None or table.currentRow() < 0:
            return "", "", None
        row = table.currentRow()
        first = table.item(row, 0)
        copy = first.data(QtCore.Qt.UserRole) if first is not None else ""
        details = first.data(QtCore.Qt.UserRole + 1) if first is not None else ""
        section = first.data(QtCore.Qt.UserRole + 2) if first is not None else None
        return str(copy or ""), str(details or ""), section

    def _show_selected_details(self) -> None:
        _copy, details, _section = self._selected_payload()
        self._details.setPlainText(details)

    def _copy_selected(self) -> None:
        copy, _details, _section = self._selected_payload()
        if copy:
            QtWidgets.QApplication.clipboard().setText(copy)

    def _jump_selected_section(self) -> None:
        _copy, _details, section = self._selected_payload()
        if self._jump_to_section is not None and isinstance(section, int):
            self._jump_to_section(section)
