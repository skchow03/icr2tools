"""Tire TXT tab builder for the track viewer."""
from __future__ import annotations

from PyQt5 import QtCore, QtWidgets


class TireTxtTabBuilder:
    """Builds the tire.txt tab UI and wires signals."""

    def __init__(self, window: QtWidgets.QWidget) -> None:
        self._window = window

    def build(self) -> QtWidgets.QWidget:
        window = self._window
        window._track_txt_tire_status_label = QtWidgets.QLabel(
            "Select a track to edit track.txt parameters."
        )
        window._track_txt_tire_status_label.setWordWrap(True)
        window._theat_fields = [window._create_int_field("–") for _ in range(8)]
        window._tcff_fields = [window._create_int_field("–") for _ in range(8)]
        window._tcfr_fields = [window._create_int_field("–") for _ in range(8)]
        window._tires_fields = [window._create_int_field("–") for _ in range(7)]
        window._tire2_fields = [window._create_int_field("–") for _ in range(7)]
        window._track_txt_tire_save_button = QtWidgets.QPushButton(
            "Save Track TXT"
        )
        window._track_txt_tire_save_button.setEnabled(False)
        window._track_txt_tire_save_button.clicked.connect(
            window._handle_save_track_txt
        )

        tire_txt_sidebar = QtWidgets.QFrame()
        tire_txt_sidebar.setFrameShape(QtWidgets.QFrame.StyledPanel)
        tire_txt_layout = QtWidgets.QVBoxLayout()
        tire_txt_layout.setSpacing(8)
        tire_txt_title = QtWidgets.QLabel("Tire TXT parameters")
        tire_txt_title.setStyleSheet("font-weight: bold")
        tire_txt_layout.addWidget(tire_txt_title)
        tire_txt_layout.addWidget(window._track_txt_tire_status_label)
        tire_txt_form = QtWidgets.QFormLayout()
        tire_txt_form.setLabelAlignment(QtCore.Qt.AlignLeft)
        tire_txt_form.setFormAlignment(QtCore.Qt.AlignTop)
        tire_txt_form.addRow(QtWidgets.QLabel("Tire heat (THEAT)"))
        tire_txt_form.addRow(window._build_compound_grid(window._theat_fields))
        tire_txt_form.addRow(
            QtWidgets.QLabel("Tire compound friction front (TCFF)")
        )
        tire_txt_form.addRow(window._build_compound_grid(window._tcff_fields))
        tire_txt_form.addRow(
            QtWidgets.QLabel("Tire compound friction rear (TCFR)")
        )
        tire_txt_form.addRow(window._build_compound_grid(window._tcfr_fields))
        tire_txt_form.addRow(QtWidgets.QLabel("Goodyear tires (TIRES)"))
        tire_txt_form.addRow(
            window._build_number_row(window._tires_fields, show_labels=False)
        )
        tire_txt_form.addRow(QtWidgets.QLabel("Firestone tires (TIRE2)"))
        tire_txt_form.addRow(
            window._build_number_row(window._tire2_fields, show_labels=False)
        )
        tire_txt_layout.addLayout(tire_txt_form)
        tire_txt_layout.addStretch(1)
        tire_txt_layout.addWidget(window._track_txt_tire_save_button)
        tire_txt_sidebar.setLayout(tire_txt_layout)
        tire_txt_scroll = QtWidgets.QScrollArea()
        tire_txt_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        tire_txt_scroll.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarAlwaysOff
        )
        tire_txt_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        tire_txt_scroll.setWidgetResizable(True)
        tire_txt_scroll.setWidget(tire_txt_sidebar)
        return tire_txt_scroll
