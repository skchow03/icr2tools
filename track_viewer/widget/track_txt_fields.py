"""Helpers for managing track.txt-related fields in the main window."""
from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from PyQt5 import QtCore, QtWidgets

from track_viewer.services.io_service import TrackTxtMetadata, TrackTxtResult


class TrackTxtFieldMixin:
    """Mixin for track.txt field management on TrackViewerWindow."""

    def _set_track_txt_field(
        self, field: QtWidgets.QLineEdit, value: str | None
    ) -> None:
        with QtCore.QSignalBlocker(field):
            if value is not None:
                field.setText(value)
            else:
                field.clear()

    def _set_track_txt_sequence(
        self, fields: Sequence[QtWidgets.QLineEdit], values: Sequence[int] | None
    ) -> None:
        for index, field in enumerate(fields):
            with QtCore.QSignalBlocker(field):
                if values is not None and index < len(values):
                    field.setText(str(values[index]))
                else:
                    field.clear()

    def _set_qual_mode(self, mode: int | None) -> None:
        with QtCore.QSignalBlocker(self._qual_mode_field):
            if mode in (0, 1, 2):
                self._qual_mode_field.setCurrentIndex(mode)
            else:
                self._qual_mode_field.setCurrentIndex(-1)
        self._update_qual_value_label(mode)

    def _set_track_type(self, ttype: int | None) -> None:
        with QtCore.QSignalBlocker(self._ttype_field):
            if ttype in (0, 1, 2, 3, 4, 5):
                self._ttype_field.setCurrentIndex(ttype)
            else:
                self._ttype_field.setCurrentIndex(-1)

    def _clear_track_txt_fields(self) -> None:
        for field in (
            self._track_name_field,
            self._track_short_name_field,
            self._track_city_field,
            self._track_country_field,
            self._track_pit_window_start_field,
            self._track_pit_window_end_field,
            self._track_length_field,
            self._track_laps_field,
            self._track_full_name_field,
            self._cars_min_field,
            self._cars_max_field,
            self._temp_avg_field,
            self._temp_dev_field,
            self._temp2_avg_field,
            self._temp2_dev_field,
            self._wind_dir_field,
            self._wind_var_field,
            self._wind_speed_field,
            self._wind_speed_var_field,
            self._wind_heading_adjust_field,
            self._wind2_dir_field,
            self._wind2_var_field,
            self._wind2_speed_field,
            self._wind2_speed_var_field,
            self._wind2_heading_adjust_field,
            self._rain_level_field,
            self._rain_variation_field,
            self._blap_field,
            self._rels_field,
            self._qual_value_field,
            self._blimp_x_field,
            self._blimp_y_field,
            self._gflag_field,
            self._pacea_cars_abreast_field,
            self._pacea_start_dlong_field,
            self._pacea_right_dlat_field,
            self._pacea_left_dlat_field,
            self._pacea_unknown_field,
        ):
            with QtCore.QSignalBlocker(field):
                field.clear()
        for field in (
            *self._theat_fields,
            *self._tcff_fields,
            *self._tcfr_fields,
            *self._tires_fields,
            *self._tire2_fields,
            *self._sctns_fields,
        ):
            with QtCore.QSignalBlocker(field):
                field.clear()
        self._set_qual_mode(None)
        self._set_track_type(None)
        self._sync_weather_compass_from_fields()

    def _update_track_txt_fields(self, result: TrackTxtResult) -> None:
        if not result.exists:
            status_text = f"No {result.txt_path.name} found."
        else:
            status_text = f"Loaded {result.txt_path.name}."
        self._track_txt_status_label.setText(status_text)
        self._track_txt_tire_status_label.setText(status_text)
        self._track_txt_weather_status_label.setText(status_text)
        metadata = result.metadata
        self._set_track_txt_field(self._track_name_field, metadata.tname)
        self._set_track_txt_field(self._track_short_name_field, metadata.sname)
        self._set_track_txt_field(self._track_city_field, metadata.cityn)
        self._set_track_txt_field(self._track_country_field, metadata.count)
        pit_window_start = (
            str(metadata.spdwy_start) if metadata.spdwy_start is not None else None
        )
        pit_window_end = (
            str(metadata.spdwy_end) if metadata.spdwy_end is not None else None
        )
        self._set_track_txt_field(self._track_pit_window_start_field, pit_window_start)
        self._set_track_txt_field(self._track_pit_window_end_field, pit_window_end)
        track_length = str(metadata.lengt) if metadata.lengt is not None else None
        self._set_track_txt_field(self._track_length_field, track_length)
        laps = str(metadata.laps) if metadata.laps is not None else None
        self._set_track_txt_field(self._track_laps_field, laps)
        self._set_track_txt_field(self._track_full_name_field, metadata.fname)
        cars_min = str(metadata.cars_min) if metadata.cars_min is not None else None
        cars_max = str(metadata.cars_max) if metadata.cars_max is not None else None
        self._set_track_txt_field(self._cars_min_field, cars_min)
        self._set_track_txt_field(self._cars_max_field, cars_max)
        temp_avg = str(metadata.temp_avg) if metadata.temp_avg is not None else None
        temp_dev = str(metadata.temp_dev) if metadata.temp_dev is not None else None
        self._set_track_txt_field(self._temp_avg_field, temp_avg)
        self._set_track_txt_field(self._temp_dev_field, temp_dev)
        temp2_avg = str(metadata.temp2_avg) if metadata.temp2_avg is not None else None
        temp2_dev = str(metadata.temp2_dev) if metadata.temp2_dev is not None else None
        self._set_track_txt_field(self._temp2_avg_field, temp2_avg)
        self._set_track_txt_field(self._temp2_dev_field, temp2_dev)
        wind_values = (
            metadata.wind_dir,
            metadata.wind_var,
            metadata.wind_speed,
            metadata.wind_speed_var,
            metadata.wind_heading_adjust,
        )
        wind_text = [
            str(value) if value is not None else None for value in wind_values
        ]
        self._set_track_txt_field(self._wind_dir_field, wind_text[0])
        self._set_track_txt_field(self._wind_var_field, wind_text[1])
        self._set_track_txt_field(self._wind_speed_field, wind_text[2])
        self._set_track_txt_field(self._wind_speed_var_field, wind_text[3])
        self._set_track_txt_field(self._wind_heading_adjust_field, wind_text[4])
        wind2_values = (
            metadata.wind2_dir,
            metadata.wind2_var,
            metadata.wind2_speed,
            metadata.wind2_speed_var,
            metadata.wind2_heading_adjust,
        )
        wind2_text = [
            str(value) if value is not None else None for value in wind2_values
        ]
        self._set_track_txt_field(self._wind2_dir_field, wind2_text[0])
        self._set_track_txt_field(self._wind2_var_field, wind2_text[1])
        self._set_track_txt_field(self._wind2_speed_field, wind2_text[2])
        self._set_track_txt_field(self._wind2_speed_var_field, wind2_text[3])
        self._set_track_txt_field(
            self._wind2_heading_adjust_field, wind2_text[4]
        )
        rain_level = (
            str(metadata.rain_level) if metadata.rain_level is not None else None
        )
        rain_variation = (
            str(metadata.rain_variation)
            if metadata.rain_variation is not None
            else None
        )
        self._set_track_txt_field(self._rain_level_field, rain_level)
        self._set_track_txt_field(self._rain_variation_field, rain_variation)
        blap = str(metadata.blap) if metadata.blap is not None else None
        self._set_track_txt_field(self._blap_field, blap)
        rels = str(metadata.rels) if metadata.rels is not None else None
        self._set_track_txt_field(self._rels_field, rels)
        self._set_track_txt_sequence(self._theat_fields, metadata.theat)
        self._set_track_txt_sequence(self._tcff_fields, metadata.tcff)
        self._set_track_txt_sequence(self._tcfr_fields, metadata.tcfr)
        self._set_track_txt_sequence(self._tires_fields, metadata.tires)
        self._set_track_txt_sequence(self._tire2_fields, metadata.tire2)
        self._set_track_txt_sequence(self._sctns_fields, metadata.sctns)
        qual_mode_value = metadata.qual_session_mode
        qual_value = (
            str(metadata.qual_session_value)
            if metadata.qual_session_value is not None
            else None
        )
        self._set_qual_mode(qual_mode_value)
        self._set_track_txt_field(self._qual_value_field, qual_value)
        blimp_x = str(metadata.blimp_x) if metadata.blimp_x is not None else None
        blimp_y = str(metadata.blimp_y) if metadata.blimp_y is not None else None
        self._set_track_txt_field(self._blimp_x_field, blimp_x)
        self._set_track_txt_field(self._blimp_y_field, blimp_y)
        gflag = str(metadata.gflag) if metadata.gflag is not None else None
        self._set_track_txt_field(self._gflag_field, gflag)
        self._set_track_type(metadata.ttype)
        pacea_values = (
            metadata.pacea_cars_abreast,
            metadata.pacea_start_dlong,
            metadata.pacea_right_dlat,
            metadata.pacea_left_dlat,
            metadata.pacea_unknown,
        )
        pacea_text = [
            str(value) if value is not None else None for value in pacea_values
        ]
        self._set_track_txt_field(self._pacea_cars_abreast_field, pacea_text[0])
        self._set_track_txt_field(self._pacea_start_dlong_field, pacea_text[1])
        self._set_track_txt_field(self._pacea_right_dlat_field, pacea_text[2])
        self._set_track_txt_field(self._pacea_left_dlat_field, pacea_text[3])
        self._set_track_txt_field(self._pacea_unknown_field, pacea_text[4])
        self._sync_weather_compass_from_fields()

    def _sync_weather_compass_from_fields(self) -> None:
        self.preview_api.set_weather_heading_adjust(
            "wind", self._parse_optional_int(self._wind_heading_adjust_field.text())
        )
        self.preview_api.set_weather_heading_adjust(
            "wind2",
            self._parse_optional_int(self._wind2_heading_adjust_field.text()),
        )
        self.preview_api.set_weather_wind_direction(
            "wind", self._parse_optional_int(self._wind_dir_field.text())
        )
        self.preview_api.set_weather_wind_variation(
            "wind", self._parse_optional_int(self._wind_var_field.text())
        )
        self.preview_api.set_weather_wind_direction(
            "wind2", self._parse_optional_int(self._wind2_dir_field.text())
        )
        self.preview_api.set_weather_wind_variation(
            "wind2", self._parse_optional_int(self._wind2_var_field.text())
        )

    def _handle_weather_compass_source_changed(
        self, source: str, checked: bool
    ) -> None:
        if not checked:
            return
        self.preview_api.set_weather_compass_source(source)
        self.visualization_widget.update()

    def _handle_weather_heading_adjust_changed(
        self, source: str, text: str
    ) -> None:
        self.preview_api.set_weather_heading_adjust(
            source, self._parse_optional_int(text)
        )

    def _handle_weather_direction_changed(self, source: str, text: str) -> None:
        self.preview_api.set_weather_wind_direction(
            source, self._parse_optional_int(text)
        )

    def _handle_weather_variation_changed(self, source: str, text: str) -> None:
        self.preview_api.set_weather_wind_variation(
            source, self._parse_optional_int(text)
        )

    def _handle_weather_compass_heading_adjust_changed(
        self, source: str, value: int
    ) -> None:
        field = (
            self._wind2_heading_adjust_field
            if source == "wind2"
            else self._wind_heading_adjust_field
        )
        with QtCore.QSignalBlocker(field):
            field.setText(str(value))

    def _handle_weather_compass_wind_direction_changed(
        self, source: str, value: int
    ) -> None:
        field = self._wind2_dir_field if source == "wind2" else self._wind_dir_field
        with QtCore.QSignalBlocker(field):
            field.setText(str(value))

    def _track_txt_fields_dirty(self, fields: Sequence[str]) -> bool:
        if self.controller.track_txt_result is None:
            return False
        current = self._collect_track_txt_metadata()
        baseline = self.controller.track_txt_result.metadata
        for field in fields:
            if getattr(current, field) != getattr(baseline, field):
                return True
        return False

    def _track_tab_dirty(self) -> bool:
        return self._track_txt_fields_dirty(
            (
                "tname",
                "sname",
                "cityn",
                "count",
                "spdwy_start",
                "spdwy_end",
                "lengt",
                "laps",
                "fname",
                "cars_min",
                "cars_max",
                "blap",
                "rels",
                "sctns",
                "qual_session_mode",
                "qual_session_value",
                "blimp_x",
                "blimp_y",
                "gflag",
                "ttype",
                "pacea_cars_abreast",
                "pacea_start_dlong",
                "pacea_right_dlat",
                "pacea_left_dlat",
                "pacea_unknown",
            )
        )

    def _weather_tab_dirty(self) -> bool:
        return self._track_txt_fields_dirty(
            (
                "temp_avg",
                "temp_dev",
                "temp2_avg",
                "temp2_dev",
                "wind_dir",
                "wind_var",
                "wind_speed",
                "wind_speed_var",
                "wind_heading_adjust",
                "wind2_dir",
                "wind2_var",
                "wind2_speed",
                "wind2_speed_var",
                "wind2_heading_adjust",
                "rain_level",
                "rain_variation",
            )
        )

    def _tire_tab_dirty(self) -> bool:
        return self._track_txt_fields_dirty(
            (
                "theat",
                "tcff",
                "tcfr",
                "tires",
                "tire2",
            )
        )

    def _handle_track_txt_fields_changed(self) -> None:
        self._update_dirty_tab_labels()

    def _connect_track_txt_dirty_signals(self) -> None:
        fields = [
            self._track_name_field,
            self._track_short_name_field,
            self._track_city_field,
            self._track_country_field,
            self._track_pit_window_start_field,
            self._track_pit_window_end_field,
            self._track_length_field,
            self._track_laps_field,
            self._track_full_name_field,
            self._cars_min_field,
            self._cars_max_field,
            self._temp_avg_field,
            self._temp_dev_field,
            self._temp2_avg_field,
            self._temp2_dev_field,
            self._wind_dir_field,
            self._wind_var_field,
            self._wind_speed_field,
            self._wind_speed_var_field,
            self._wind_heading_adjust_field,
            self._wind2_dir_field,
            self._wind2_var_field,
            self._wind2_speed_field,
            self._wind2_speed_var_field,
            self._wind2_heading_adjust_field,
            self._rain_level_field,
            self._rain_variation_field,
            self._blap_field,
            self._rels_field,
            self._qual_value_field,
            self._blimp_x_field,
            self._blimp_y_field,
            self._gflag_field,
            self._pacea_cars_abreast_field,
            self._pacea_start_dlong_field,
            self._pacea_right_dlat_field,
            self._pacea_left_dlat_field,
            self._pacea_unknown_field,
        ]
        fields.extend(self._theat_fields)
        fields.extend(self._tcff_fields)
        fields.extend(self._tcfr_fields)
        fields.extend(self._tires_fields)
        fields.extend(self._tire2_fields)
        fields.extend(self._sctns_fields)
        for field in fields:
            field.textChanged.connect(self._handle_track_txt_fields_changed)
        self._qual_mode_field.currentIndexChanged.connect(
            self._handle_track_txt_fields_changed
        )
        self._ttype_field.currentIndexChanged.connect(
            self._handle_track_txt_fields_changed
        )

    def _collect_track_txt_metadata(self) -> TrackTxtMetadata:
        base = (
            self.controller.track_txt_result.metadata
            if self.controller.track_txt_result is not None
            else TrackTxtMetadata()
        )
        metadata = replace(base)
        metadata.tname = self._track_name_field.text().strip() or None
        metadata.sname = self._track_short_name_field.text().strip() or None
        metadata.cityn = self._track_city_field.text().strip() or None
        metadata.count = self._track_country_field.text().strip() or None
        metadata.spdwy_start = self._parse_optional_int(
            self._track_pit_window_start_field.text()
        )
        metadata.spdwy_end = self._parse_optional_int(
            self._track_pit_window_end_field.text()
        )
        if metadata.spdwy_flag is None:
            metadata.spdwy_flag = 0
        metadata.lengt = self._parse_optional_int(self._track_length_field.text())
        metadata.laps = self._parse_optional_int(self._track_laps_field.text())
        metadata.fname = self._track_full_name_field.text().strip() or None
        metadata.cars_min = self._parse_optional_int(self._cars_min_field.text())
        metadata.cars_max = self._parse_optional_int(self._cars_max_field.text())
        metadata.temp_avg = self._parse_optional_int(self._temp_avg_field.text())
        metadata.temp_dev = self._parse_optional_int(self._temp_dev_field.text())
        metadata.temp2_avg = self._parse_optional_int(self._temp2_avg_field.text())
        metadata.temp2_dev = self._parse_optional_int(self._temp2_dev_field.text())
        metadata.wind_dir = self._parse_optional_int(self._wind_dir_field.text())
        metadata.wind_var = self._parse_optional_int(self._wind_var_field.text())
        metadata.wind_speed = self._parse_optional_int(self._wind_speed_field.text())
        metadata.wind_speed_var = self._parse_optional_int(
            self._wind_speed_var_field.text()
        )
        metadata.wind_heading_adjust = self._parse_optional_int(
            self._wind_heading_adjust_field.text()
        )
        metadata.wind2_dir = self._parse_optional_int(self._wind2_dir_field.text())
        metadata.wind2_var = self._parse_optional_int(self._wind2_var_field.text())
        metadata.wind2_speed = self._parse_optional_int(self._wind2_speed_field.text())
        metadata.wind2_speed_var = self._parse_optional_int(
            self._wind2_speed_var_field.text()
        )
        metadata.wind2_heading_adjust = self._parse_optional_int(
            self._wind2_heading_adjust_field.text()
        )
        metadata.rain_level = self._parse_optional_int(self._rain_level_field.text())
        metadata.rain_variation = self._parse_optional_int(
            self._rain_variation_field.text()
        )
        metadata.blap = self._parse_optional_int(self._blap_field.text())
        metadata.rels = self._parse_optional_int(self._rels_field.text())
        metadata.theat = self._collect_int_sequence(self._theat_fields)
        metadata.tcff = self._collect_int_sequence(self._tcff_fields)
        metadata.tcfr = self._collect_int_sequence(self._tcfr_fields)
        metadata.tires = self._collect_int_sequence(self._tires_fields)
        metadata.tire2 = self._collect_int_sequence(self._tire2_fields)
        metadata.sctns = self._collect_int_sequence(self._sctns_fields)
        metadata.qual_session_mode = (
            self._qual_mode_field.currentData()
            if self._qual_mode_field.currentIndex() >= 0
            else None
        )
        metadata.qual_session_value = self._parse_optional_int(
            self._qual_value_field.text()
        )
        metadata.blimp_x = self._parse_optional_int(self._blimp_x_field.text())
        metadata.blimp_y = self._parse_optional_int(self._blimp_y_field.text())
        metadata.gflag = self._parse_optional_int(self._gflag_field.text())
        metadata.ttype = (
            self._ttype_field.currentData()
            if self._ttype_field.currentIndex() >= 0
            else None
        )
        metadata.pacea_cars_abreast = self._parse_optional_int(
            self._pacea_cars_abreast_field.text()
        )
        metadata.pacea_start_dlong = self._parse_optional_int(
            self._pacea_start_dlong_field.text()
        )
        metadata.pacea_right_dlat = self._parse_optional_int(
            self._pacea_right_dlat_field.text()
        )
        metadata.pacea_left_dlat = self._parse_optional_int(
            self._pacea_left_dlat_field.text()
        )
        metadata.pacea_unknown = self._parse_optional_int(
            self._pacea_unknown_field.text()
        )
        return metadata

    @staticmethod
    def _parse_optional_int(value: str) -> int | None:
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return int(stripped)
        except ValueError:
            return None

    def _collect_int_sequence(
        self, fields: Sequence[QtWidgets.QLineEdit]
    ) -> list[int] | None:
        parsed_values: list[int | None] = [
            self._parse_optional_int(field.text()) for field in fields
        ]
        if all(value is None for value in parsed_values):
            return None
        if any(value is None for value in parsed_values):
            return None
        return [value for value in parsed_values if value is not None]
