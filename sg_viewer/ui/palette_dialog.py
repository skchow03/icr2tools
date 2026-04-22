from __future__ import annotations

from PyQt5 import QtCore, QtGui, QtWidgets


class PaletteColorDialog(QtWidgets.QDialog):
    """Displays a 16x16 grid of palette colors and selected color index."""

    def __init__(
        self,
        palette: list[QtGui.QColor],
        parent: QtWidgets.QWidget | None = None,
        *,
        selection_mode: bool = False,
        initial_index: int | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = list(palette[:256])
        self.setWindowTitle("SUNNY.PCX Palette")
        self.setModal(selection_mode)
        self.resize(560, 640)
        self._buttons: list[QtWidgets.QPushButton] = []
        self._selected_button: QtWidgets.QPushButton | None = None
        self.selected_index: int | None = None

        layout = QtWidgets.QVBoxLayout(self)
        if selection_mode:
            info_text = "Click a color tile, then press OK to assign it."
        else:
            info_text = "Click a color tile to see the palette index used by SG surfaces."
        info_label = QtWidgets.QLabel(info_text)
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        self._selected_label = QtWidgets.QLabel("Selected index: none")
        self._selected_label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        layout.addWidget(self._selected_label)

        grid_widget = QtWidgets.QWidget(self)
        grid_layout = QtWidgets.QGridLayout(grid_widget)
        grid_layout.setSpacing(2)
        grid_layout.setContentsMargins(0, 0, 0, 0)

        for index, color in enumerate(self._palette):
            button = QtWidgets.QPushButton()
            button.setFixedSize(30, 30)
            button.setFocusPolicy(QtCore.Qt.NoFocus)
            self._set_button_style(button, color)
            button.setToolTip(
                f"Index {index}: rgb({color.red()}, {color.green()}, {color.blue()})"
            )
            button.clicked.connect(
                lambda _checked=False, idx=index, c=color: self._on_color_selected(idx, c)
            )
            self._buttons.append(button)
            grid_layout.addWidget(button, index // 16, index % 16)

        layout.addWidget(grid_widget)

        if selection_mode:
            button_box = QtWidgets.QDialogButtonBox(
                QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
                parent=self,
            )
            self._ok_button = button_box.button(QtWidgets.QDialogButtonBox.Ok)
            self._ok_button.setEnabled(False)
            button_box.accepted.connect(self.accept)
            button_box.rejected.connect(self.reject)
            layout.addWidget(button_box)
        else:
            close_button = QtWidgets.QPushButton("Close")
            close_button.clicked.connect(self.close)
            layout.addWidget(close_button, alignment=QtCore.Qt.AlignRight)

        if initial_index is not None and 0 <= initial_index < len(self._palette):
            self._on_color_selected(initial_index, self._palette[initial_index])

    def _on_color_selected(self, index: int, color: QtGui.QColor) -> None:
        if self._selected_button is not None and self.selected_index is not None:
            self._set_button_style(self._selected_button, self._palette[self.selected_index])

        selected_button = self._buttons[index]
        self._set_button_style(selected_button, color, selected=True)
        self._selected_button = selected_button
        self.selected_index = int(index)
        self._selected_label.setText(
            f"Selected index: {index}   rgb({color.red()}, {color.green()}, {color.blue()})"
        )
        if hasattr(self, "_ok_button"):
            self._ok_button.setEnabled(True)

    @staticmethod
    def _set_button_style(
        button: QtWidgets.QPushButton, color: QtGui.QColor, *, selected: bool = False
    ) -> None:
        border = "2px solid white" if selected else "1px solid #222"
        button.setStyleSheet(
            "background-color: rgb(%d, %d, %d); border: %s;"
            % (color.red(), color.green(), color.blue(), border)
        )
