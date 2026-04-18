from pathlib import Path

from sg_viewer.replacecolors import replace_colors_from_file


def test_replace_colors_from_file_updates_matching_color_symbols(tmp_path: Path) -> None:
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
