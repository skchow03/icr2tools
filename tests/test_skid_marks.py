import random

import pytest

from sg_viewer.services.skid_marks import (
    SkidMarkGenerationParameters,
    _interpolate_dlat_range,
    generate_skid_mark_lines,
    parse_colors_csv,
    parse_skid_sections_csv,
)


def test_generate_skid_mark_lines_from_csv_rows() -> None:
    sections = parse_skid_sections_csv(
        "Turn1,100000,120000,150000,3500,9000,2200,8,22000,16000,13000,7000,14000,5000"
    )
    parameters = SkidMarkGenerationParameters(colors=(45, 28), sections=sections)
    lines = generate_skid_mark_lines(parameters, rng=random.Random(7))

    assert len(lines) == 8
    assert all(line.command == "Detail" for line in lines)
    assert all(line.width_500ths == 2200 for line in lines)
    assert all(line.color_index in (45, 28) for line in lines)
    assert sections[0].turn_in_percent == 20
    assert sections[0].straighten_percent == 20


def test_parse_colors_csv_uses_defaults_for_blank() -> None:
    assert parse_colors_csv("   ") == (45, 28, 44, 29)


def test_skid_transition_percentages_hold_start_and_end_ranges() -> None:
    section = parse_skid_sections_csv(
        "Turn1,0,500,1000,10,20,100,1,0,100,200,300,400,500,20,20"
    )[0]
    kwargs = dict(
        entry_length=500,
        exit_length=500,
        start_min=0,
        start_max=100,
        apex_min=200,
        apex_max=300,
        end_min=400,
        end_max=500,
    )

    assert _interpolate_dlat_range(section, dlong=200, **kwargs) == (0, 100)
    assert _interpolate_dlat_range(section, dlong=350, **kwargs) == (100, 200)
    assert _interpolate_dlat_range(section, dlong=650, **kwargs) == (300, 400)
    assert _interpolate_dlat_range(section, dlong=800, **kwargs) == (400, 500)


def test_smooth_skid_transitions_use_gradual_s_curve() -> None:
    section = parse_skid_sections_csv(
        "Turn1,0,500,1000,10,20,100,1,0,100,200,300,400,500,20,20,1"
    )[0]
    kwargs = dict(
        entry_length=500,
        exit_length=500,
        start_min=0,
        start_max=100,
        apex_min=200,
        apex_max=300,
        end_min=400,
        end_max=500,
    )

    assert section.smooth_transitions is True
    # A smoothstep curve moves less than linear interpolation near each end.
    assert _interpolate_dlat_range(section, dlong=275, **kwargs) == (31, 131)
    assert _interpolate_dlat_range(section, dlong=425, **kwargs) == (168, 268)
    assert _interpolate_dlat_range(section, dlong=575, **kwargs) == (231, 331)
    assert _interpolate_dlat_range(section, dlong=725, **kwargs) == (368, 468)


def test_smooth_row_preserves_custom_transition_percentages() -> None:
    section = parse_skid_sections_csv(
        "Turn1,0,500,1000,10,20,100,1,0,100,200,300,400,500,25,15,1"
    )[0]

    assert section.turn_in_percent == 25
    assert section.straighten_percent == 15


@pytest.mark.parametrize("value", ["wat", "sometimes"])
def test_smooth_skid_transition_rejects_invalid_checkbox_values(value: str) -> None:
    with pytest.raises(ValueError, match="Smooth must be a checkbox value"):
        parse_skid_sections_csv(
            f"Turn1,0,500,1000,10,20,100,1,0,100,200,300,400,500,20,20,{value}"
        )


@pytest.mark.parametrize("percentages", ["60,40", "101,0", "60,20"])
def test_skid_transition_percentages_reject_incompatible_values(
    percentages: str,
) -> None:
    # The last case crosses a 50%-positioned apex even though the two values total under 99.
    with pytest.raises(ValueError):
        parse_skid_sections_csv(
            f"Turn1,0,500,1000,10,20,100,1,0,100,200,300,400,500,{percentages}"
        )
