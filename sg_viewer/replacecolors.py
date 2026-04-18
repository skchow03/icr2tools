from __future__ import annotations

import argparse
import re
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path

_COLOR_DEFINITION_PATTERN = re.compile(r"^\s*(__\w+__):\s*(\[[^\]]+\])\s*;\s*$")

DEFAULT_TRACK3D_COLORS: "OrderedDict[str, int]" = OrderedDict(
    [
        ("__Asphalt1__", 192),
        ("__Asphalt2__", 191),
        ("__Asphalt3__", 192),
        ("__Asphalt4__", 191),
        ("__Concrete1__", 195),
        ("__Concrete2__", 194),
        ("__Concrete3__", 195),
        ("__Concrete4__", 194),
        ("__Grass1__", 213),
        ("__Grass2__", 214),
        ("__Grass3__", 212),
        ("__Grass4__", 211),
        ("__DryGrass1__", 213),
        ("__DryGrass2__", 214),
        ("__DryGrass3__", 212),
        ("__DryGrass4__", 211),
        ("__Dirt1__", 208),
        ("__Dirt2__", 208),
        ("__Dirt3__", 208),
        ("__Dirt4__", 208),
        ("__Paint__", 35),
        ("__YellowPaint__", 158),
        ("__Sand1__", 224),
        ("__Sand2__", 224),
        ("__Sand3__", 224),
        ("__Sand4__", 224),
        ("__walllite1__", 161),
        ("__walllite2__", 161),
        ("__walldark1__", 161),
        ("__walldark2__", 161),
        ("__wallltod1__", 161),
        ("__wallltod2__", 161),
        ("__walldtol1__", 161),
        ("__walldtol2__", 161),
        ("__wallreg1__", 161),
        ("__wallreg2__", 161),
        ("__armclite1__", 248),
        ("__armclite2__", 248),
        ("__armcdark1__", 248),
        ("__armcdark2__", 248),
        ("__armcltod1__", 248),
        ("__armcltod2__", 248),
        ("__armcdtol1__", 248),
        ("__armcdtol2__", 248),
        ("__armcreg1__", 248),
        ("__armcreg2__", 248),
        ("__fenceVert__", 46),
        ("__fenceHorz__", 46),
        ("__walldk__", 27),
        ("__wallbr__", 35),
    ]
)


def build_color_value_from_index(index: int) -> str:
    return f"[<0, 0, 0>, c= <{int(index)}>]"


def color_definition_lines(colors: Mapping[str, int]) -> list[str]:
    lines: list[str] = []
    for name, default_index in DEFAULT_TRACK3D_COLORS.items():
        index = int(colors.get(name, default_index))
        lines.append(f"{name}: {build_color_value_from_index(index)};\n")
    return lines


def read_color_definitions(colors_file: str | Path) -> dict[str, str]:
    """Return color definitions keyed by color symbol name."""
    path = Path(colors_file)
    colors: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = _COLOR_DEFINITION_PATTERN.match(raw_line)
        if match:
            color_name, color_value = match.groups()
            colors[color_name] = color_value
    return colors


def replace_color_definitions(track_file: str | Path, colors: Mapping[str, str]) -> int:
    """Replace matching color lines in ``track_file`` and return replacement count."""
    path = Path(track_file)
    updated_content: list[str] = []
    replacements = 0

    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True):
        match = _COLOR_DEFINITION_PATTERN.match(line.rstrip("\r\n"))
        if match:
            color_name = match.group(1)
            updated_value = colors.get(color_name)
            if updated_value is not None:
                line = f"{color_name}: {updated_value};\n"
                replacements += 1
        updated_content.append(line)

    path.write_text("".join(updated_content), encoding="utf-8")
    return replacements


def replace_color_section_from_indices(track_file: str | Path, colors: Mapping[str, int]) -> int:
    """Replace the track color section in ``track_file`` using palette indices."""
    path = Path(track_file)
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
    supported_names = set(DEFAULT_TRACK3D_COLORS.keys())

    section_indexes: list[int] = []
    for index, line in enumerate(lines):
        match = _COLOR_DEFINITION_PATTERN.match(line.rstrip("\r\n"))
        if match and match.group(1) in supported_names:
            section_indexes.append(index)

    replacement_lines = color_definition_lines(colors)
    if section_indexes:
        start = min(section_indexes)
        end = max(section_indexes) + 1
        lines[start:end] = replacement_lines
    else:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        if lines and lines[-1].strip():
            lines.append("\n")
        lines.extend(replacement_lines)

    path.write_text("".join(lines), encoding="utf-8")
    return len(replacement_lines)


def replace_colors_from_file(track_file: str | Path, colors_file: str | Path) -> int:
    """Load color definitions from ``colors_file`` and apply them to ``track_file``."""
    colors = read_color_definitions(colors_file)
    return replace_color_definitions(track_file, colors)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replace __Color__ definitions in a .3D file using values from a colors file."
    )
    parser.add_argument("track_file", help="Path to the source track .3D file to update.")
    parser.add_argument("colors_file", help="Path to the file containing replacement color definitions.")
    args = parser.parse_args()

    replacements = replace_colors_from_file(args.track_file, args.colors_file)
    print(f"Updated {replacements} color definition(s) in {args.track_file}.")


if __name__ == "__main__":
    main()
