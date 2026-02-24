from __future__ import annotations

from PyQt5 import QtCore, QtGui, QtWidgets


class PaletteColorDialog(QtWidgets.QDialog):
    """Displays a 16x16 grid of palette colors and selected color index."""

    def __init__(self, palette: list[QtGui.QColor], parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("SUNNY.PCX Palette")
        self.setModal(False)
        self.resize(560, 640)
        self._buttons: list[QtWidgets.QPushButton] = []

        layout = QtWidgets.QVBoxLayout(self)
        info_label = QtWidgets.QLabel(
            "Click a color tile to see the palette index used by SG surfaces."
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        self._selected_label = QtWidgets.QLabel("Selected index: none")
        self._selected_label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        layout.addWidget(self._selected_label)

        grid_widget = QtWidgets.QWidget(self)
        grid_layout = QtWidgets.QGridLayout(grid_widget)
        grid_layout.setSpacing(2)
        grid_layout.setContentsMargins(0, 0, 0, 0)

        for index, color in enumerate(palette[:256]):
            button = QtWidgets.QPushButton()
            button.setFixedSize(30, 30)
            button.setFocusPolicy(QtCore.Qt.NoFocus)
            button.setStyleSheet(
                "background-color: rgb(%d, %d, %d); border: 1px solid #222;" % (
                    color.red(),
                    color.green(),
                    color.blue(),
                )
            )
            button.setToolTip(
                f"Index {index}: rgb({color.red()}, {color.green()}, {color.blue()})"
            )
            button.clicked.connect(
                lambda _checked=False, idx=index, c=color: self._on_color_selected(idx, c)
            )
            self._buttons.append(button)
            grid_layout.addWidget(button, index // 16, index % 16)

        layout.addWidget(grid_widget)

        close_button = QtWidgets.QPushButton("Close")
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button, alignment=QtCore.Qt.AlignRight)

    def _on_color_selected(self, index: int, color: QtGui.QColor) -> None:
        self._selected_label.setText(
            f"Selected index: {index}   rgb({color.red()}, {color.green()}, {color.blue()})"
        )
