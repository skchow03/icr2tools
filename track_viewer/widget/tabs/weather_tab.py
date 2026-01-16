"""Weather TXT tab builder for the track viewer."""
from __future__ import annotations

from PyQt5 import QtCore, QtWidgets


class WeatherTabBuilder:
    """Builds the weather tab UI and wires signals."""

    def __init__(self, window: QtWidgets.QWidget) -> None:
        self._window = window

    def build(self) -> QtWidgets.QWidget:
        window = self._window
        window._track_txt_weather_status_label = QtWidgets.QLabel(
            "Select a track to edit track.txt parameters."
        )
        window._track_txt_weather_status_label.setWordWrap(True)
        window._temp_avg_field = window._create_int_field("–")
        window._temp_dev_field = window._create_int_field("–")
        window._temp2_avg_field = window._create_int_field("–")
        window._temp2_dev_field = window._create_int_field("–")
        window._wind_dir_field = window._create_int_field("–")
        window._wind_var_field = window._create_int_field("–")
        window._wind_speed_field = window._create_int_field("–")
        window._wind_speed_var_field = window._create_int_field("–")
        window._wind_heading_adjust_field = window._create_int_field("–")
        window._wind2_dir_field = window._create_int_field("–")
        window._wind2_var_field = window._create_int_field("–")
        window._wind2_speed_field = window._create_int_field("–")
        window._wind2_speed_var_field = window._create_int_field("–")
        window._wind2_heading_adjust_field = window._create_int_field("–")
        window._rain_level_field = window._create_int_field("–")
        window._rain_variation_field = window._create_int_field("–")
        window._track_txt_weather_save_button = QtWidgets.QPushButton(
            "Save Track TXT"
        )
        window._track_txt_weather_save_button.setEnabled(False)
        window._track_txt_weather_save_button.clicked.connect(
            window._handle_save_track_txt
        )
        window._weather_compass_group = QtWidgets.QButtonGroup(window)
        window._weather_compass_wind_button = QtWidgets.QRadioButton("WIND")
        window._weather_compass_wind2_button = QtWidgets.QRadioButton("WIND2")
        window._weather_compass_group.addButton(
            window._weather_compass_wind_button
        )
        window._weather_compass_group.addButton(
            window._weather_compass_wind2_button
        )
        window._weather_compass_wind_button.setChecked(True)
        window._weather_compass_wind_button.toggled.connect(
            lambda checked: window._handle_weather_compass_source_changed(
                "wind", checked
            )
        )
        window._weather_compass_wind2_button.toggled.connect(
            lambda checked: window._handle_weather_compass_source_changed(
                "wind2", checked
            )
        )
        window._wind_heading_adjust_field.textChanged.connect(
            lambda text: window._handle_weather_heading_adjust_changed(
                "wind", text
            )
        )
        window._wind2_heading_adjust_field.textChanged.connect(
            lambda text: window._handle_weather_heading_adjust_changed(
                "wind2", text
            )
        )
        window._wind_dir_field.textChanged.connect(
            lambda text: window._handle_weather_direction_changed("wind", text)
        )
        window._wind_var_field.textChanged.connect(
            lambda text: window._handle_weather_variation_changed("wind", text)
        )
        window._wind2_dir_field.textChanged.connect(
            lambda text: window._handle_weather_direction_changed("wind2", text)
        )
        window._wind2_var_field.textChanged.connect(
            lambda text: window._handle_weather_variation_changed("wind2", text)
        )

        weather_txt_sidebar = QtWidgets.QFrame()
        weather_txt_sidebar.setFrameShape(QtWidgets.QFrame.StyledPanel)
        weather_txt_layout = QtWidgets.QVBoxLayout()
        weather_txt_layout.setSpacing(8)
        weather_txt_title = QtWidgets.QLabel("Weather TXT parameters")
        weather_txt_title.setStyleSheet("font-weight: bold")
        weather_txt_layout.addWidget(weather_txt_title)
        weather_txt_layout.addWidget(window._track_txt_weather_status_label)
        compass_source_layout = QtWidgets.QHBoxLayout()
        compass_source_layout.setContentsMargins(0, 0, 0, 0)
        compass_source_layout.addWidget(QtWidgets.QLabel("Compass source"))
        compass_source_layout.addWidget(window._weather_compass_wind_button)
        compass_source_layout.addWidget(window._weather_compass_wind2_button)
        compass_source_layout.addStretch(1)
        compass_source_widget = QtWidgets.QWidget()
        compass_source_widget.setLayout(compass_source_layout)
        weather_txt_layout.addWidget(compass_source_widget)
        weather_txt_form = QtWidgets.QFormLayout()
        weather_txt_form.setLabelAlignment(QtCore.Qt.AlignLeft)
        weather_txt_form.setFormAlignment(QtCore.Qt.AlignTop)
        temp_layout = QtWidgets.QHBoxLayout()
        temp_layout.setContentsMargins(0, 0, 0, 0)
        temp_layout.addWidget(QtWidgets.QLabel("Average"))
        temp_layout.addWidget(window._temp_avg_field)
        temp_layout.addWidget(QtWidgets.QLabel("Deviation"))
        temp_layout.addWidget(window._temp_dev_field)
        temp_widget = QtWidgets.QWidget()
        temp_widget.setLayout(temp_layout)
        weather_txt_form.addRow("Temperature (TEMP)", temp_widget)
        temp2_layout = QtWidgets.QHBoxLayout()
        temp2_layout.setContentsMargins(0, 0, 0, 0)
        temp2_layout.addWidget(QtWidgets.QLabel("Average"))
        temp2_layout.addWidget(window._temp2_avg_field)
        temp2_layout.addWidget(QtWidgets.QLabel("Deviation"))
        temp2_layout.addWidget(window._temp2_dev_field)
        temp2_widget = QtWidgets.QWidget()
        temp2_widget.setLayout(temp2_layout)
        weather_txt_form.addRow("Temperature 2 (TEMP2)", temp2_widget)
        wind_layout = QtWidgets.QGridLayout()
        wind_layout.setContentsMargins(0, 0, 0, 0)
        wind_layout.setHorizontalSpacing(6)
        wind_layout.addWidget(QtWidgets.QLabel("Direction"), 0, 0)
        wind_layout.addWidget(window._wind_dir_field, 0, 1)
        wind_layout.addWidget(QtWidgets.QLabel("Variation"), 0, 2)
        wind_layout.addWidget(window._wind_var_field, 0, 3)
        wind_layout.addWidget(QtWidgets.QLabel("Speed (0.1 mph)"), 1, 0)
        wind_layout.addWidget(window._wind_speed_field, 1, 1)
        wind_layout.addWidget(QtWidgets.QLabel("Speed variation"), 1, 2)
        wind_layout.addWidget(window._wind_speed_var_field, 1, 3)
        wind_layout.addWidget(QtWidgets.QLabel("Heading adjust"), 2, 0)
        wind_layout.addWidget(window._wind_heading_adjust_field, 2, 1)
        wind_widget = QtWidgets.QWidget()
        wind_widget.setLayout(wind_layout)
        weather_txt_form.addRow(QtWidgets.QLabel("Wind (WIND)"))
        weather_txt_form.addRow(wind_widget)
        wind2_layout = QtWidgets.QGridLayout()
        wind2_layout.setContentsMargins(0, 0, 0, 0)
        wind2_layout.setHorizontalSpacing(6)
        wind2_layout.addWidget(QtWidgets.QLabel("Direction"), 0, 0)
        wind2_layout.addWidget(window._wind2_dir_field, 0, 1)
        wind2_layout.addWidget(QtWidgets.QLabel("Variation"), 0, 2)
        wind2_layout.addWidget(window._wind2_var_field, 0, 3)
        wind2_layout.addWidget(QtWidgets.QLabel("Speed (0.1 mph)"), 1, 0)
        wind2_layout.addWidget(window._wind2_speed_field, 1, 1)
        wind2_layout.addWidget(QtWidgets.QLabel("Speed variation"), 1, 2)
        wind2_layout.addWidget(window._wind2_speed_var_field, 1, 3)
        wind2_layout.addWidget(QtWidgets.QLabel("Heading adjust"), 2, 0)
        wind2_layout.addWidget(window._wind2_heading_adjust_field, 2, 1)
        wind2_widget = QtWidgets.QWidget()
        wind2_widget.setLayout(wind2_layout)
        weather_txt_form.addRow(QtWidgets.QLabel("Wind 2 (WIND2)"))
        weather_txt_form.addRow(wind2_widget)
        rain_layout = QtWidgets.QHBoxLayout()
        rain_layout.setContentsMargins(0, 0, 0, 0)
        rain_layout.addWidget(QtWidgets.QLabel("Parameter 1"))
        rain_layout.addWidget(window._rain_level_field)
        rain_layout.addWidget(QtWidgets.QLabel("Parameter 2"))
        rain_layout.addWidget(window._rain_variation_field)
        rain_widget = QtWidgets.QWidget()
        rain_widget.setLayout(rain_layout)
        weather_txt_form.addRow(QtWidgets.QLabel("Rain (RAIN)"))
        weather_txt_form.addRow(rain_widget)
        weather_txt_layout.addLayout(weather_txt_form)
        weather_txt_layout.addStretch(1)
        weather_txt_layout.addWidget(window._track_txt_weather_save_button)
        weather_txt_sidebar.setLayout(weather_txt_layout)
        weather_txt_scroll = QtWidgets.QScrollArea()
        weather_txt_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        weather_txt_scroll.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarAlwaysOff
        )
        weather_txt_scroll.setVerticalScrollBarPolicy(
            QtCore.Qt.ScrollBarAsNeeded
        )
        weather_txt_scroll.setWidgetResizable(True)
        weather_txt_scroll.setWidget(weather_txt_sidebar)
        return weather_txt_scroll
