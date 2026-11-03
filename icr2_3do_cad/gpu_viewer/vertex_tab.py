"""Qt vertex inspector/editor beside the shared OpenGL CAD viewport.

The model owns the *compiled* vertices; user edits are emitted as requests to
Window, which patches and recompiles the authoritative .3D source. The list
is virtualized so giant track models do not create thousands of Qt widgets.
"""
from __future__ import annotations

from bisect import bisect_left

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QListView, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from vertex_labels import declaration_label, names_for_vertices


class VertexListModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = None
        self.offsets = []
        self.names = {}

    def replace(self, model, names):
        self.beginResetModel()
        self.model = model
        self.offsets = sorted(model.vertices) if model is not None else []
        self.names = names or {}
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.offsets)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.offsets):
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            off = self.offsets[index.row()]
            v = self.model.vertices[off]
            named = self.names.get(off)
            tag = " UV" if v.textured else ""
            return (f"@{off}  {named}  {v.xyz[0]}, {v.xyz[1]}, {v.xyz[2]}{tag}"
                    if named else
                    f"@{off}  {v.xyz[0]}, {v.xyz[1]}, {v.xyz[2]}{tag}")
        if role == Qt.ItemDataRole.UserRole:
            return self.offsets[index.row()]
        return None

    def row_for_offset(self, off):
        index = bisect_left(self.offsets, off)
        return index if index < len(self.offsets) and self.offsets[index] == off else -1


class VertexPane(QWidget):
    vertexSelected = Signal(int)
    coordinatesRequested = Signal(object)
    uvRequested = Signal(object)
    renameRequested = Signal(str)
    nudgeRequested = Signal(int)
    undoRequested = Signal()
    redoRequested = Signal()
    frameRequested = Signal()
    saveRequested = Signal()
    exportRequested = Signal()
    visualChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = None
        self._document = None
        self.selected = None
        self._names = {}
        self._blocked = False
        self.list_model = VertexListModel(self)

        layout = QVBoxLayout(self)
        self.selection_label = QLabel("Open a model and click a vertex dot")
        self.selection_label.setWordWrap(True)
        layout.addWidget(self.selection_label)

        row = QHBoxLayout()
        self.dots = QCheckBox("Vertex dots")
        self.dots.setChecked(True)
        self.dots.toggled.connect(lambda _: self.visualChanged.emit())
        row.addWidget(self.dots)
        self.visible_only = QCheckBox("Active BSP / LOD only")
        self.visible_only.setChecked(True)
        self.visible_only.toggled.connect(lambda _: self.visualChanged.emit())
        row.addWidget(self.visible_only)
        layout.addLayout(row)

        label_row = QHBoxLayout()
        label_row.addWidget(QLabel("Labels:"))
        self.label_mode = QComboBox()
        self.label_mode.addItems(("Off", "Names", "Offsets"))
        self.label_mode.currentIndexChanged.connect(lambda _: self.visualChanged.emit())
        label_row.addWidget(self.label_mode)
        label_row.addStretch()
        layout.addLayout(label_row)

        rename_row = QHBoxLayout()
        self.pointer_name = QLineEdit()
        self.pointer_name.setPlaceholderText(".3D vertex pointer name")
        self.pointer_name.returnPressed.connect(self.request_rename)
        rename_row.addWidget(self.pointer_name, 1)
        self.rename_button = QPushButton("Rename")
        self.rename_button.clicked.connect(self.request_rename)
        rename_row.addWidget(self.rename_button)
        layout.addWidget(QLabel("Pointer name (.3D source only)"))
        layout.addLayout(rename_row)

        coordinate_form = QFormLayout()
        self.xyz = []
        for axis in "XYZ":
            edit = QLineEdit()
            edit.setPlaceholderText(f"Raw {axis}")
            edit.returnPressed.connect(self.request_coordinates)
            coordinate_form.addRow(axis, edit)
            self.xyz.append(edit)
        self.uv = []
        for axis in ("U", "V"):
            edit = QLineEdit()
            edit.setPlaceholderText(f"{axis} (0–65535)")
            edit.returnPressed.connect(self.request_uv)
            coordinate_form.addRow(axis, edit)
            self.uv.append(edit)
        layout.addLayout(coordinate_form)
        apply_row = QHBoxLayout()
        self.xyz_apply = QPushButton("Apply XYZ")
        self.xyz_apply.clicked.connect(self.request_coordinates)
        apply_row.addWidget(self.xyz_apply)
        self.uv_apply = QPushButton("Apply UV")
        self.uv_apply.clicked.connect(self.request_uv)
        apply_row.addWidget(self.uv_apply)
        layout.addLayout(apply_row)

        movement = QHBoxLayout()
        movement.addWidget(QLabel("Drag / nudge axis:"))
        self.axis = QComboBox()
        self.axis.addItems(("X", "Y", "Z"))
        movement.addWidget(self.axis)
        movement.addWidget(QLabel("Step:"))
        self.step = QSpinBox()
        self.step.setRange(1, 2_000_000_000)
        self.step.setValue(500)
        movement.addWidget(self.step)
        layout.addLayout(movement)
        nudge = QHBoxLayout()
        minus = QPushButton("− Step")
        minus.clicked.connect(lambda: self.nudgeRequested.emit(-1))
        nudge.addWidget(minus)
        plus = QPushButton("+ Step")
        plus.clicked.connect(lambda: self.nudgeRequested.emit(1))
        nudge.addWidget(plus)
        layout.addLayout(nudge)

        find = QHBoxLayout()
        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("Vertex body offset (decimal or 0x)")
        self.find_input.returnPressed.connect(self.find_offset)
        find.addWidget(self.find_input, 1)
        go = QPushButton("Go")
        go.clicked.connect(self.find_offset)
        find.addWidget(go)
        layout.addLayout(find)

        self.vertex_list = QListView()
        self.vertex_list.setUniformItemSizes(True)
        self.vertex_list.setModel(self.list_model)
        self.vertex_list.clicked.connect(self._selected_list)
        layout.addWidget(self.vertex_list, 1)

        bottom = QHBoxLayout()
        undo = QPushButton("Undo")
        undo.clicked.connect(self.undoRequested.emit)
        bottom.addWidget(undo)
        redo = QPushButton("Redo")
        redo.clicked.connect(self.redoRequested.emit)
        bottom.addWidget(redo)
        frame = QPushButton("Frame selected")
        frame.clicked.connect(self.frameRequested.emit)
        bottom.addWidget(frame)
        layout.addLayout(bottom)
        saves = QHBoxLayout()
        save = QPushButton("Save .3D as…")
        save.clicked.connect(self.saveRequested.emit)
        saves.addWidget(save)
        export = QPushButton("Export compiled .3DO…")
        export.clicked.connect(self.exportRequested.emit)
        saves.addWidget(export)
        layout.addLayout(saves)
        self.status = QLabel("Left-click a dot to select; drag on chosen axis. "
                             "Right-drag or empty-space left-drag to orbit; "
                             "Shift+left-drag/middle-drag to pan.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self._refresh_selection()

    def set_model(self, model, document, *, original_n3=False, selected=None):
        self._model = model
        self._document = document
        self._names = names_for_vertices(
            model, document, original_n3=original_n3)
        self.list_model.replace(model, self._names)
        # A model-reset invalidates the old view index even if the Papyrus
        # body offset remains unchanged. Reapply its selection explicitly.
        self.selected = None
        self.select_offset(selected, emit=False)

    def select_offset(self, off, *, emit=True):
        if self._model is None or off not in self._model.vertices:
            off = None
        if off == self.selected and self._model is not None:
            self._refresh_selection()
            return
        self.selected = off
        self._refresh_selection()
        row = self.list_model.row_for_offset(off) if off is not None else -1
        self.vertex_list.blockSignals(True)
        try:
            if row >= 0:
                index = self.list_model.index(row, 0)
                self.vertex_list.setCurrentIndex(index)
                self.vertex_list.scrollTo(index)
            else:
                self.vertex_list.clearSelection()
        finally:
            self.vertex_list.blockSignals(False)
        if emit and off is not None:
            self.vertexSelected.emit(off)

    def _refresh_selection(self):
        available = self._model is not None and self.selected in self._model.vertices
        for w in (*self.xyz, *self.uv, self.pointer_name):
            w.setEnabled(available)
        self.xyz_apply.setEnabled(available)
        self.rename_button.setEnabled(available and self._document is not None)
        self.uv_apply.setEnabled(
            available and self._model.vertices[self.selected].textured)
        if not available:
            self.selection_label.setText("Click a visible vertex or select one from the list")
            for w in (*self.xyz, *self.uv, self.pointer_name):
                w.clear()
            return
        vertex = self._model.vertices[self.selected]
        name = self._names.get(self.selected)
        self.selection_label.setText(
            f"Vertex @{self.selected}" + (f" • {name}" if name else "") +
            (" • UV mapped" if vertex.textured else " • no UV") +
            (" • RES anchor" if self.selected in self._model.lod_anchors else ""))
        for field, value in zip(self.xyz, vertex.xyz):
            field.setText(str(value))
        for field, value in zip(self.uv, vertex.uv or ("", "")):
            field.setText(str(value))
            field.setEnabled(vertex.textured)
        self.pointer_name.setText(
            name or (declaration_label(self._model, self._document, self.selected)
                     if self._document is not None else ""))

    def _selected_list(self, index):
        off = self.list_model.data(index, Qt.ItemDataRole.UserRole)
        if off is not None:
            self.select_offset(off)

    def find_offset(self):
        try:
            text = self.find_input.text().strip()
            off = int(text, 16 if text.lower().startswith("0x") else 10)
        except ValueError:
            QMessageBox.warning(self, "Invalid offset", "Enter a decimal or 0x body offset.")
            return
        if self.list_model.row_for_offset(off) < 0:
            QMessageBox.information(self, "Vertex not found", f"No vertex at body offset {off}.")
            return
        self.select_offset(off)

    def request_coordinates(self):
        try:
            values = tuple(int(field.text().strip()) for field in self.xyz)
        except ValueError:
            QMessageBox.warning(self, "Invalid XYZ", "X, Y, Z must be whole integers.")
            return
        self.coordinatesRequested.emit(values)

    def request_uv(self):
        try:
            values = tuple(int(field.text().strip()) for field in self.uv)
        except ValueError:
            QMessageBox.warning(self, "Invalid UV", "U and V must be whole integers.")
            return
        self.uvRequested.emit(values)

    def request_rename(self):
        self.renameRequested.emit(self.pointer_name.text().strip())
