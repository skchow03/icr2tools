from __future__ import annotations

import argparse
import re
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path

_COLOR_DEFINITION_PATTERN = re.compile(r"^\s*(__\w+__):\s*(\[[^\]]+\])\s*;\s*$")

DEFAULT_TRACK3D_COLORS: "OrderedDict[str, int]" = OrderedDict(
    [
        ("__Asphalt1__", 239),
        ("__Asphalt2__", 238),
        ("__Asphalt3__", 237),
        ("__Asphalt4__", 236),
        ("__Concrete1__", 39),
        ("__Concrete2__", 38),
        ("__Concrete3__", 37),
        ("__Concrete4__", 36),
        ("__Grass1__", 108),
        ("__Grass2__", 107),
        ("__Grass3__", 108),
        ("__Grass4__", 107),
        ("__DryGrass1__", 148),
        ("__DryGrass2__", 147),
        ("__DryGrass3__", 148),
        ("__DryGrass4__", 147),
        ("__Dirt1__", 149),
        ("__Dirt2__", 148),
        ("__Dirt3__", 149),
        ("__Dirt4__", 148),
        ("__Paint__", 35),
        ("__YellowPaint__", 158),
        ("__Sand1__", 172),
        ("__Sand2__", 173),
        ("__Sand3__", 172),
        ("__Sand4__", 171),
        ("__walllite1__", 35),
        ("__walllite2__", 35),
        ("__walldark1__", 38),
        ("__walldark2__", 38),
        ("__wallltod1__", 37),
        ("__wallltod2__", 37),
        ("__walldtol1__", 37),
        ("__walldtol2__", 37),
        ("__wallreg1__", 36),
        ("__wallreg2__", 36),
        ("__armclite1__", 52),
        ("__armclite2__", 51),
        ("__armcdark1__", 54),
        ("__armcdark2__", 53),
        ("__armcltod1__", 52),
        ("__armcltod2__", 52),
        ("__armcdtol1__", 52),
        ("__armcdtol2__", 52),
        ("__armcreg1__", 52),
        ("__armcreg2__", 51),
        ("__fenceVert__", 46),
        ("__fenceHorz__", 46),
        ("__walldk__", 37),
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
