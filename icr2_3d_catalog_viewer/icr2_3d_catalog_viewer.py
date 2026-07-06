#!/usr/bin/env python3
"""
ICR2 .3D Catalog Viewer

Small PyQt5 UI for browsing an ICR2/N2-style text .3D file.

Features:
  - File navigator rooted at a chosen folder
  - Open .3D/.txt files from the navigator or File > Open
  - Catalog tree for Sections, Section Lists, Object Lists, TSOs, and final index
  - Detail inspector table for selected catalog nodes
  - Raw JSON inspector for selected catalog nodes
  - Export parsed catalog to JSON/CSV using icr2_3d_catalog_parser.write_outputs

Expected project layout:
  icr2_3d_catalog_parser.py
  icr2_3d_catalog_viewer.py

Run:
  python icr2_3d_catalog_viewer.py
  python icr2_3d_catalog_viewer.py C:\\ICR2\\TRACKS\\FIREBIRD\\FBIRDEAS.txt
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

try:
    from PyQt5.QtCore import QModelIndex, Qt, QDir
    from PyQt5.QtGui import QFont
    from PyQt5.QtWidgets import (
        QAction,
        QApplication,
        QFileDialog,
        QFileSystemModel,
        QHeaderView,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QSplitter,
        QStatusBar,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QTextEdit,
        QToolBar,
        QTreeWidget,
        QTreeWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover - user-facing runtime guard
    raise SystemExit(
        "PyQt5 is required. Install with: pip install PyQt5\n"
        f"Original import error: {exc}"
    )

from icr2_3d_catalog_parser import parse_3d, write_outputs


DETAIL_ROLE = Qt.UserRole + 1
KIND_ROLE = Qt.UserRole + 2
LABEL_ROLE = Qt.UserRole + 3


def as_text(value: Any) -> str:
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, indent=2, sort_keys=True)
    if value is None:
        return ""
    return str(value)


class DetailPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.tabs = QTabWidget()

        self.summary = QTableWidget(0, 2)
        self.summary.setHorizontalHeaderLabels(["Field", "Value"])
        self.summary.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.summary.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.summary.verticalHeader().setVisible(False)
        self.summary.setWordWrap(True)

        self.children = QTableWidget(0, 1)
        self.children.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.children.verticalHeader().setVisible(False)
        self.children.setWordWrap(False)

        self.json_text = QTextEdit()
        self.json_text.setReadOnly(True)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        self.json_text.setFont(mono)

        self.tabs.addTab(self.summary, "Selected")
        self.tabs.addTab(self.children, "List")
        self.tabs.addTab(self.json_text, "JSON")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tabs)

    def show_data(self, title: str, data: Any) -> None:
        self.summary.setRowCount(0)
        self.children.setRowCount(0)
        self.children.setColumnCount(1)
        self.children.setHorizontalHeaderLabels([title or "Items"])

        if isinstance(data, dict):
            self.summary.setRowCount(len(data))
            for row, (key, value) in enumerate(data.items()):
                key_item = QTableWidgetItem(str(key))
                key_item.setFlags(key_item.flags() & ~Qt.ItemIsEditable)
                val_item = QTableWidgetItem(as_text(value))
                val_item.setFlags(val_item.flags() & ~Qt.ItemIsEditable)
                self.summary.setItem(row, 0, key_item)
                self.summary.setItem(row, 1, val_item)

            list_like = None
            for key in ("items", "entries", "faces", "object_lists", "detail_lists", "section_lists", "subsections", "dlong_ranges"):
                if key in data and isinstance(data[key], list):
                    list_like = data[key]
                    self.children.setHorizontalHeaderLabels([key])
                    break
            if list_like is not None:
                self._fill_list(list_like)
        elif isinstance(data, list):
            self._fill_list(data)
        else:
            self.summary.setRowCount(1)
            self.summary.setItem(0, 0, QTableWidgetItem("value"))
            self.summary.setItem(0, 1, QTableWidgetItem(as_text(data)))

        self.summary.resizeRowsToContents()
        self.children.resizeRowsToContents()
        self.json_text.setPlainText(json.dumps(data, indent=2, sort_keys=True, default=str))

    def _fill_list(self, values: list[Any]) -> None:
        self.children.setRowCount(len(values))
        for row, value in enumerate(values):
            item = QTableWidgetItem(as_text(value))
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.children.setItem(row, 0, item)


class CatalogViewer(QMainWindow):
    def __init__(self, start_file: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle("ICR2 .3D Catalog Viewer")
        self.resize(1450, 850)

        self.current_file: Path | None = None
        self.catalog: dict[str, Any] | None = None
        self._filter_text = ""

        self.file_model = QFileSystemModel()
        self.file_model.setNameFilters(["*.3D", "*.3d", "*.txt", "*.TXT"])
        self.file_model.setNameFilterDisables(False)
        self.file_model.setFilter(QDir.AllDirs | QDir.Files | QDir.NoDotAndDotDot)

        root_path = str(Path(start_file).parent if start_file else Path.cwd())
        self.file_model.setRootPath(root_path)

        self.file_tree = QTreeWidget()  # placeholder replaced by filesystem tree below? no multi-inheritance needed
        from PyQt5.QtWidgets import QTreeView
        self.nav = QTreeView()
        self.nav.setModel(self.file_model)
        self.nav.setRootIndex(self.file_model.index(root_path))
        self.nav.setColumnWidth(0, 320)
        self.nav.setSortingEnabled(True)
        self.nav.doubleClicked.connect(self._open_from_nav)

        self.catalog_tree = QTreeWidget()
        self.catalog_tree.setHeaderLabels(["Catalog"])
        self.catalog_tree.itemSelectionChanged.connect(self._on_catalog_selection)

        self.detail_panel = DetailPanel()

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(4, 4, 4, 4)
        self.root_label = QLabel(root_path)
        choose_button = QPushButton("Choose Folder")
        choose_button.clicked.connect(self.choose_folder)
        left_layout.addWidget(self.root_label)
        left_layout.addWidget(choose_button)
        left_layout.addWidget(self.nav)

        middle = QWidget()
        middle_layout = QVBoxLayout(middle)
        middle_layout.setContentsMargins(4, 4, 4, 4)
        self.filter_box = QLineEdit()
        self.filter_box.setPlaceholderText("Filter catalog labels, object names, materials...")
        self.filter_box.textChanged.connect(self._refilter_catalog)
        middle_layout.addWidget(self.filter_box)
        middle_layout.addWidget(self.catalog_tree)

        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(middle)
        splitter.addWidget(self.detail_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 2)
        splitter.setSizes([360, 430, 660])
        self.setCentralWidget(splitter)

        self.setStatusBar(QStatusBar())
        self._build_actions()

        if start_file:
            self.open_file(Path(start_file))

    def _build_actions(self) -> None:
        toolbar = QToolBar("Main")
        self.addToolBar(toolbar)

        open_action = QAction("Open .3D", self)
        open_action.triggered.connect(self.choose_file)
        export_action = QAction("Export Catalog", self)
        export_action.triggered.connect(self.export_catalog)
        reload_action = QAction("Reload", self)
        reload_action.triggered.connect(self.reload_file)

        self.menuBar().addMenu("File").addAction(open_action)
        self.menuBar().addMenu("File").addAction(export_action)
        self.menuBar().addMenu("File").addAction(reload_action)
        toolbar.addAction(open_action)
        toolbar.addAction(export_action)
        toolbar.addAction(reload_action)

    def choose_folder(self) -> None:
        start = str(self.current_file.parent if self.current_file else Path.cwd())
        folder = QFileDialog.getExistingDirectory(self, "Choose root folder", start)
        if folder:
            self.file_model.setRootPath(folder)
            self.nav.setRootIndex(self.file_model.index(folder))
            self.root_label.setText(folder)

    def choose_file(self) -> None:
        start = str(self.current_file.parent if self.current_file else Path.cwd())
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open text .3D file",
            start,
            "ICR2 3D text files (*.3D *.3d *.txt *.TXT);;All files (*.*)",
        )
        if path:
            self.open_file(Path(path))

    def _open_from_nav(self, index: QModelIndex) -> None:
        path = Path(self.file_model.filePath(index))
        if path.is_file():
            self.open_file(path)

    def reload_file(self) -> None:
        if self.current_file:
            self.open_file(self.current_file)

    def open_file(self, path: Path) -> None:
        try:
            catalog = parse_3d(path)
        except Exception as exc:
            QMessageBox.critical(self, "Parse failed", f"Could not parse:\n{path}\n\n{exc}\n\n{traceback.format_exc()}")
            return

        self.current_file = path
        self.catalog = catalog
        self.setWindowTitle(f"ICR2 .3D Catalog Viewer - {path.name}")
        self.statusBar().showMessage(
            f"Loaded {path} | TSOs {catalog['counts']['tsos']} | ObjectLists {catalog['counts']['object_lists']} | "
            f"FACE blocks {catalog['counts']['faces']} | Section lists {catalog['counts']['section_lists']}"
        )
        self.file_model.setRootPath(str(path.parent))
        self.nav.setRootIndex(self.file_model.index(str(path.parent)))
        self.root_label.setText(str(path.parent))
        self.populate_catalog_tree()

    def export_catalog(self) -> None:
        if not self.catalog or not self.current_file:
            QMessageBox.information(self, "No catalog", "Open a .3D file first.")
            return
        default = self.current_file.with_suffix("_catalog") if False else self.current_file.parent / f"{self.current_file.stem}_catalog"
        prefix, _ = QFileDialog.getSaveFileName(self, "Export catalog prefix", str(default), "Output prefix (*)")
        if not prefix:
            return
        try:
            write_outputs(self.catalog, prefix)
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        QMessageBox.information(self, "Export complete", f"Wrote:\n{prefix}.json\n{prefix}.sections.csv\n{prefix}.faces.csv")

    def populate_catalog_tree(self) -> None:
        self.catalog_tree.clear()
        if not self.catalog:
            return
        catalog = self.catalog
        needle = self._filter_text.lower().strip()

        def matches(label: str, data: Any = None) -> bool:
            if not needle:
                return True
            blob = label + " " + json.dumps(data, default=str)
            return needle in blob.lower()

        root = QTreeWidgetItem([catalog.get("source", "Track .3D")])
        root.setData(0, DETAIL_ROLE, {"source": catalog.get("source"), "counts": catalog.get("counts")})
        self.catalog_tree.addTopLevelItem(root)

        sections_root = QTreeWidgetItem(["Sections"])
        sections_root.setData(0, DETAIL_ROLE, catalog["section_summary"])
        root.addChild(sections_root)

        faces_by_sec_sub: dict[tuple[int, int], list[dict[str, Any]]] = {}
        for face in catalog["faces"]:
            faces_by_sec_sub.setdefault((face["section"], face["subsection"]), []).append(face)

        sec_lists_by_sec: dict[int, list[dict[str, Any]]] = {}
        for label, sec_list in catalog["section_lists"].items():
            item = dict(sec_list)
            item["label"] = label
            sec_lists_by_sec.setdefault(sec_list["section"], []).append(item)

        for summary in catalog["section_summary"]:
            sec_no = summary["section"]
            if not matches(f"Section {sec_no}", summary):
                # still include if any child matches
                child_has_match = any(matches(face["label"], face) for (s, _), faces in faces_by_sec_sub.items() if s == sec_no for face in faces)
                child_has_match |= any(matches(sl["label"], sl) for sl in sec_lists_by_sec.get(sec_no, []))
                if not child_has_match:
                    continue
            sec_item = QTreeWidgetItem([f"Section {sec_no}"])
            sec_item.setData(0, DETAIL_ROLE, summary)
            sections_root.addChild(sec_item)

            layouts = QTreeWidgetItem(["Layouts"])
            layouts.setData(0, DETAIL_ROLE, sec_lists_by_sec.get(sec_no, []))
            sec_item.addChild(layouts)
            for sec_list in sorted(sec_lists_by_sec.get(sec_no, []), key=lambda x: x["label"]):
                if matches(sec_list["label"], sec_list):
                    child = QTreeWidgetItem([f"{sec_list['label']}  DATA {sec_list.get('dlongs', [])}"])
                    child.setData(0, DETAIL_ROLE, sec_list)
                    layouts.addChild(child)

            subs = QTreeWidgetItem(["Subsections / LOD FACE blocks"])
            subs.setData(0, DETAIL_ROLE, [f for (s, _), faces in faces_by_sec_sub.items() if s == sec_no for f in faces])
            sec_item.addChild(subs)
            sub_numbers = sorted({sub for (s, sub) in faces_by_sec_sub if s == sec_no})
            for sub_no in sub_numbers:
                sub_faces = faces_by_sec_sub[(sec_no, sub_no)]
                if not matches(f"Subsection {sub_no}", sub_faces) and not any(matches(face["label"], face) for face in sub_faces):
                    continue
                sub_item = QTreeWidgetItem([f"Subsection {sub_no}"])
                sub_item.setData(0, DETAIL_ROLE, sub_faces)
                subs.addChild(sub_item)
                for face in sorted(sub_faces, key=lambda f: {"HI": 0, "MED": 1, "LO": 2}.get(f["lod"], 9)):
                    if not matches(face["label"], face):
                        continue
                    dlong = ""
                    if face.get("dlong_start") is not None:
                        dlong = f"  DLONG {face['dlong_start']}–{face['dlong_end']}"
                    face_item = QTreeWidgetItem([f"{face['label']}{dlong}"])
                    face_item.setData(0, DETAIL_ROLE, face)
                    sub_item.addChild(face_item)

        obj_root = QTreeWidgetItem(["Object Lists"])
        obj_root.setData(0, DETAIL_ROLE, catalog["object_lists"])
        root.addChild(obj_root)
        for label, obj in sorted(catalog["object_lists"].items()):
            if not matches(label, obj):
                continue
            item = QTreeWidgetItem([f"{label}  ({len(obj.get('items', []))} objects)"])
            item.setData(0, DETAIL_ROLE, {"label": label, **obj})
            obj_root.addChild(item)

        tso_root = QTreeWidgetItem(["Dynamic TSOs"])
        tso_root.setData(0, DETAIL_ROLE, catalog["tsos"])
        root.addChild(tso_root)
        for label, tso in sorted(catalog["tsos"].items(), key=lambda kv: int(kv[0].replace("__TSO", ""))):
            if not matches(label, tso):
                continue
            item = QTreeWidgetItem([f"{label}  {tso.get('extern', '')}"])
            item.setData(0, DETAIL_ROLE, {"label": label, **tso})
            tso_root.addChild(item)

        index_root = QTreeWidgetItem(["Final index"])
        index_root.setData(0, DETAIL_ROLE, catalog["index"])
        root.addChild(index_root)
        for entry in catalog["index"]:
            if matches(entry):
                item = QTreeWidgetItem([entry])
                item.setData(0, DETAIL_ROLE, entry)
                index_root.addChild(item)

        self.catalog_tree.expandToDepth(2)
        self.catalog_tree.setCurrentItem(root)

    def _refilter_catalog(self, text: str) -> None:
        self._filter_text = text
        self.populate_catalog_tree()

    def _on_catalog_selection(self) -> None:
        items = self.catalog_tree.selectedItems()
        if not items:
            return
        item = items[0]
        data = item.data(0, DETAIL_ROLE)
        self.detail_panel.show_data(item.text(0), data)


def main() -> None:
    app = QApplication(sys.argv)
    start_file = sys.argv[1] if len(sys.argv) > 1 else None
    viewer = CatalogViewer(start_file=start_file)
    viewer.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
