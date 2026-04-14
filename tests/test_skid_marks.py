import random

from sg_viewer.services.skid_marks import (
    SkidMarkGenerationParameters,
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


def test_parse_colors_csv_uses_defaults_for_blank() -> None:
    assert parse_colors_csv("   ") == (45, 28, 44, 29)
