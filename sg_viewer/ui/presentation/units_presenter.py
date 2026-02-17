from __future__ import annotations

from sg_viewer.ui.altitude_units import feet_from_500ths

from sg_viewer.ui.altitude_units import units_from_500ths, units_to_500ths


UNIT_LABELS = {"feet": "ft", "meter": "m", "inch": "in", "500ths": "500ths"}
UNIT_DECIMALS = {"feet": 1, "meter": 3, "inch": 1, "500ths": 0}
UNIT_STEPS = {"feet": 0.1, "meter": 0.05, "inch": 1.0, "500ths": 50.0}


def measurement_unit_label(unit: str) -> str:
    return UNIT_LABELS.get(unit, "500ths")


def measurement_unit_decimals(unit: str) -> int:
    return UNIT_DECIMALS.get(unit, 0)


def measurement_unit_step(unit: str) -> float:
    return UNIT_STEPS.get(unit, 50.0)


def format_length(value: float | int | None, *, unit: str) -> str:
    if value is None:
        return "–"
    display = units_from_500ths(value, unit)
    decimals = measurement_unit_decimals(unit)
    label = measurement_unit_label(unit)
    if decimals == 0:
        return f"{int(round(display))} {label}"
    return f"{display:.{decimals}f} {label}"


def format_length_with_secondary(value: float | int | None, *, unit: str) -> str:
    primary = format_length(value, unit=unit)
    if value is None:
        return primary
    feet_value = units_from_500ths(value, "feet")
    if unit == "feet":
        return f"{primary} ({feet_value / 5280.0:.3f} miles)"
    if unit == "meter":
        return f"{primary} ({(feet_value * 0.3048) / 1000.0:.3f} km)"
    return primary


def xsect_altitude_to_display_units(value: int, *, unit: str) -> float:
    return units_from_500ths(value, unit)


def xsect_altitude_from_display_units(value: float, *, unit: str) -> int:
    return units_to_500ths(value, unit)


def format_xsect_altitude(value: int, *, unit: str) -> str:
    display = xsect_altitude_to_display_units(value, unit=unit)
    decimals = measurement_unit_decimals(unit)
    if decimals == 0:
        return f"{int(round(display))}"
    return f"{display:.{decimals}f}"


def fsect_dlat_to_display_units(value: float, *, unit: str) -> float:
    return units_from_500ths(value, unit)


def fsect_dlat_from_display_units(value: float, *, unit: str) -> float:
    return float(units_to_500ths(value, unit))


def fsect_dlat_units_label(*, unit: str) -> str:
    return measurement_unit_label(unit)


def format_fsect_dlat(value: float, *, unit: str) -> str:
    display = fsect_dlat_to_display_units(value, unit=unit)
    decimals = measurement_unit_decimals(unit)
    if decimals == 0:
        return f"{int(round(display))}"
    return f"{display:.{decimals}f}".rstrip("0").rstrip(".")


def altitude_display_to_feet(value: float, *, unit: str) -> float:
    altitude_500ths = units_to_500ths(value, unit)
    return feet_from_500ths(altitude_500ths)


def feet_to_altitude_display(value_feet: float, *, unit: str) -> float:
    altitude_500ths = units_to_500ths(value_feet, "feet")
    return units_from_500ths(altitude_500ths, unit)


def format_altitude_for_units(altitude_500ths: int, *, unit: str) -> str:
    value = units_from_500ths(altitude_500ths, unit)
    decimals = measurement_unit_decimals(unit)
    if decimals == 0:
        return f"{int(round(value))}"
    return f"{value:.{decimals}f}"
