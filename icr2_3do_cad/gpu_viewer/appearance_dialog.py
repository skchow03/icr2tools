"""Color customization dialog for the GPU viewport and editable .3D source."""
from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QColorDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from gpu_viewer.appearance import (
    COLOR_GROUPS, DARK_COLORS, LIGHT_COLORS, swatch_text_color, validated_colors,
)


class AppearanceDialog(QDialog):
    """Each accepted color/preset updates the live editor and GPU immediately."""

    def __init__(self, colors, apply_colors, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Customize Viewer Colors")
        self.resize(500, 690)
        self._colors = validated_colors(colors)
        self._apply_colors = apply_colors
        self._buttons = {}

        root = QVBoxLayout(self)
        description = QLabel(
            "Colors apply immediately and are saved for future sessions. "
            "Dark and Light presets use matched, high-contrast syntax colors.")
        description.setWordWrap(True)
        root.addWidget(description)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        panel = QWidget()
        groups = QVBoxLayout(panel)
        for section, roles in COLOR_GROUPS:
            group = QGroupBox(section)
            form = QFormLayout(group)
            for name, title in roles:
                button = QPushButton()
                button.setMinimumWidth(130)
                button.setToolTip("Choose " + title.lower())
                button.clicked.connect(
                    lambda checked=False, key=name: self._choose(key))
                self._buttons[name] = button
                form.addRow(title + ":", button)
            groups.addWidget(group)
        groups.addStretch()
        scroll.setWidget(panel)
        root.addWidget(scroll, 1)

        preset_row = QHBoxLayout()
        dark = QPushButton("Restore Dark Defaults")
        dark.clicked.connect(lambda: self._set_colors(DARK_COLORS))
        light = QPushButton("Use Light Preset")
        light.clicked.connect(lambda: self._set_colors(LIGHT_COLORS))
        preset_row.addWidget(dark)
        preset_row.addWidget(light)
        root.addLayout(preset_row)

        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        root.addWidget(close)
        self._update_swatches()

    def _update_swatches(self):
        for name, button in self._buttons.items():
            color = self._colors[name]
            fg = swatch_text_color(color)
            button.setText(color)
            button.setStyleSheet(
                f"QPushButton {{background-color: {color}; color: {fg}; "
                "border: 1px solid #777; border-radius: 3px; "
                "padding: 5px; font-weight: bold;}}")

    def _set_colors(self, colors):
        self._colors = validated_colors(colors)
        self._update_swatches()
        self._apply_colors(dict(self._colors))

    def _choose(self, name):
        color = QColorDialog.getColor(
            QColor(self._colors[name]), self, "Choose " + name.replace("_", " "),
            QColorDialog.ColorDialogOption(0))
        if color.isValid():
            updated = dict(self._colors)
            updated[name] = color.name().upper()
            self._set_colors(updated)
