from pathlib import Path

import pytest

from sg_viewer.replacecolors import (
    read_mark_colors,
    replace_color_section_from_indices,
    replace_colors_from_file,
)


def test_replace_colors_from_file_updates_matching_color_symbols(
    tmp_path: Path,
) -> None:
    track_path = tmp_path / "track.3d"
    colors_path = tmp_path / "colors.txt"
    track_path.write_text(
        "__Road__: [<0, 0, 0>, c= 1];\n"
        "__Grass__: [<1, 1, 1>, c= 2];\n"
        "__NOT_COLOR__: DYNAMIC;\n",
        encoding="utf-8",
    )
    colors_path.write_text(
        "__Road__: [<9, 9, 9>, c= 11];\n"
        "__Grass__: [<3, 3, 3>, c= 22];\n"
        "__Unused__: [<4, 4, 4>, c= 33];\n",
        encoding="utf-8",
    )

    replacements = replace_colors_from_file(track_path, colors_path)

    assert replacements == 2
    assert track_path.read_text(encoding="utf-8") == (
        "__Road__: [<9, 9, 9>, c= 11];\n"
        "__Grass__: [<3, 3, 3>, c= 22];\n"
        "__NOT_COLOR__: DYNAMIC;\n"
    )


def test_read_mark_colors_stops_at_next_comment(tmp_path: Path) -> None:
    track_path = tmp_path / "track.3D"
    track_path.write_text(
        "%%Mark Colors\n"
        "__grass__: [<0, 0, 0>, c= <248>];\n"
        "__armco256__: [<0, 0, 0>, c= <17>];\n"
        "%%Object Definitions\n"
        "__not_a_mark__: [<0, 0, 0>, c= <99>];\n",
        encoding="utf-8",
    )

    assert read_mark_colors(track_path) == {
        "__grass__": 248,
        "__armco256__": 17,
    }


def test_apply_colors_updates_imported_mark_colors(tmp_path: Path) -> None:
    track_path = tmp_path / "track.3D"
    track_path.write_text(
        "%%Standard Colors\n"
        "__Asphalt1__: [<0, 0, 0>, c= <1>];\n"
        "%%Mark Colors\n"
        "__grass__: [<0, 0, 0>, c= <248>];\n"
        "%%Objects\n",
        encoding="utf-8",
    )

    count = replace_color_section_from_indices(
        track_path, {"__Asphalt1__": 42, "__grass__": 123}
    )

    text = track_path.read_text(encoding="utf-8")
    assert "__Asphalt1__: [<0, 0, 0>, c= <42>];" in text
    assert "__grass__: [<0, 0, 0>, c= <123>];" in text
    assert count == 51


def test_apply_colors_raises_when_imported_mark_is_missing(tmp_path: Path) -> None:
    track_path = tmp_path / "track.3D"
    track_path.write_text(
        "%%Mark Colors\n__grass__: [<0, 0, 0>, c= <248>];\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="__armco256__"):
        replace_color_section_from_indices(track_path, {"__armco256__": 12})
