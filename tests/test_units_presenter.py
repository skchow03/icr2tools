from sg_viewer.ui.presentation.units_presenter import (
    format_length,
    format_length_with_secondary,
    fsect_dlat_from_display_units,
    fsect_dlat_to_display_units,
)


def test_length_formatting_with_secondary() -> None:
    assert format_length(500, unit="500ths") == "500 500ths"
    assert "miles" in format_length_with_secondary(2640000, unit="feet")


def test_fsect_display_round_trip() -> None:
    value = 12345.0
    display = fsect_dlat_to_display_units(value, unit="feet")
    round_trip = fsect_dlat_from_display_units(display, unit="feet")
    assert round_trip == value
