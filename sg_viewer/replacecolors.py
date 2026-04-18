from __future__ import annotations

import argparse
import re
from collections.abc import Mapping
from pathlib import Path

_COLOR_DEFINITION_PATTERN = re.compile(r"^\s*(__\w+__):\s*(\[[^\]]+\])\s*;\s*$")


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
