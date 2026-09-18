from __future__ import annotations

from PyQt5 import QtCore, QtWidgets

from sg_viewer.services.track3d_topo_tso_calls import SectionTopoTsoCalls


class TopoTsoCallsTab(QtWidgets.QWidget):
    """Editor for the ordered left/right output calls in each .3D section."""

    changed = QtCore.pyqtSignal()
    loadRequested = QtCore.pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.load_button = QtWidgets.QPushButton("Load LISTs from .3D file")
        self.section_combo = QtWidgets.QComboBox()
        self.available_sections_list = self._make_list()
        self.add_section_left_button = QtWidgets.QPushButton("Add selected to left")
        self.add_section_right_button = QtWidgets.QPushButton("Add selected to right")
        self.left_list = self._make_list()
        self.right_list = self._make_list()
        self._calls: list[SectionTopoTsoCalls] = []
        self._visible_index = -1

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.load_button)
        layout.addWidget(QtWidgets.QLabel("Section:"))
        layout.addWidget(self.section_combo)
        layout.addWidget(self._section_picker_panel())
        columns = QtWidgets.QHBoxLayout()
        columns.addWidget(self._list_panel("Output left side TSOs", self.left_list))
        columns.addWidget(self._list_panel("Output right side TSOs", self.right_list))
        layout.addLayout(columns)
        layout.addStretch(1)
        self.load_button.clicked.connect(self.loadRequested)
        self.section_combo.currentIndexChanged.connect(self._show_section)
        self.add_section_left_button.clicked.connect(
            lambda: self._add_selected_section(self.left_list)
        )
        self.add_section_right_button.clicked.connect(
            lambda: self._add_selected_section(self.right_list)
        )

    def _make_list(self) -> QtWidgets.QListWidget:
        widget = QtWidgets.QListWidget()
        widget.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        return widget

    def _list_panel(
        self, title: str, widget: QtWidgets.QListWidget
    ) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox(title)
        layout = QtWidgets.QVBoxLayout(group)
        layout.addWidget(widget)
        buttons = QtWidgets.QHBoxLayout()
        for label, callback in (
            ("Add…", lambda _=False, w=widget: self._add(w)),
            ("Edit…", lambda _=False, w=widget: self._edit(w)),
            ("Remove", lambda _=False, w=widget: self._remove(w)),
            ("↑", lambda _=False, w=widget: self._move(w, -1)),
            ("↓", lambda _=False, w=widget: self._move(w, 1)),
        ):
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        return group

    def _section_picker_panel(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("Available sections")
        layout = QtWidgets.QVBoxLayout(group)
        layout.addWidget(self.available_sections_list)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(self.add_section_left_button)
        buttons.addWidget(self.add_section_right_button)
        layout.addLayout(buttons)
        return group

    def set_calls(self, calls: list[SectionTopoTsoCalls]) -> None:
        self._calls = [
            SectionTopoTsoCalls(c.section, list(c.left), list(c.right)) for c in calls
        ]
        with QtCore.QSignalBlocker(self.section_combo):
            self.section_combo.clear()
            self.section_combo.addItems([call.section for call in self._calls])
        self.available_sections_list.clear()
        self.available_sections_list.addItems([call.section for call in self._calls])
        if self.available_sections_list.count():
            self.available_sections_list.setCurrentRow(0)
        self._visible_index = -1
        self._show_section(0)

    def calls(self) -> list[SectionTopoTsoCalls]:
        self._store_visible()
        return [
            SectionTopoTsoCalls(c.section, list(c.left), list(c.right))
            for c in self._calls
        ]

    def serialize(self) -> list[dict[str, object]]:
        return [
            {"section": c.section, "left": c.left, "right": c.right}
            for c in self.calls()
        ]

    def load_payload(self, payload: object) -> None:
        calls: list[SectionTopoTsoCalls] = []
        if isinstance(payload, list):
            for row in payload:
                if not isinstance(row, dict) or not isinstance(row.get("section"), str):
                    continue
                left = row.get("left", [])
                right = row.get("right", [])
                calls.append(
                    SectionTopoTsoCalls(
                        row["section"],
                        [str(x) for x in left] if isinstance(left, list) else [],
                        [str(x) for x in right] if isinstance(right, list) else [],
                    )
                )
        self.set_calls(calls)

    def _store_visible(self) -> None:
        index = self._visible_index
        if 0 <= index < len(self._calls):
            self._calls[index].left = [
                self.left_list.item(i).text() for i in range(self.left_list.count())
            ]
            self._calls[index].right = [
                self.right_list.item(i).text() for i in range(self.right_list.count())
            ]

    def _show_section(self, index: int) -> None:
        self._store_visible()
        self.left_list.clear()
        self.right_list.clear()
        if 0 <= index < len(self._calls):
            self.left_list.addItems(self._calls[index].left)
            self.right_list.addItems(self._calls[index].right)
        self._visible_index = index

    def _add(self, widget: QtWidgets.QListWidget) -> None:
        value, ok = QtWidgets.QInputDialog.getText(self, "Add TOPO/TSO call", "Call:")
        if ok:
            widget.addItem(value)
            self.changed.emit()

    def _add_selected_section(self, widget: QtWidgets.QListWidget) -> None:
        section = self.available_sections_list.currentItem()
        if section is None:
            return
        widget.addItem(section.text())
        widget.setCurrentRow(widget.count() - 1)
        self.changed.emit()

    def _edit(self, widget: QtWidgets.QListWidget) -> None:
        item = widget.currentItem()
        if item is None:
            return
        value, ok = QtWidgets.QInputDialog.getText(
            self, "Edit TOPO/TSO call", "Call:", text=item.text()
        )
        if ok:
            item.setText(value)
            self.changed.emit()

    def _remove(self, widget: QtWidgets.QListWidget) -> None:
        row = widget.currentRow()
        if row >= 0:
            widget.takeItem(row)
            self.changed.emit()

    def _move(self, widget: QtWidgets.QListWidget, delta: int) -> None:
        row = widget.currentRow()
        destination = row + delta
        if row < 0 or destination < 0 or destination >= widget.count():
            return
        item = widget.takeItem(row)
        widget.insertItem(destination, item)
        widget.setCurrentRow(destination)
        self.changed.emit()
