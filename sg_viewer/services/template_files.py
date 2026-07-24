from __future__ import annotations

from pathlib import Path

TRACKNAME_PLACEHOLDER = "<<trackname>>"


def parse_template_trackname_files(files_text: str) -> list[Path]:
    return [Path(part.strip()) for part in files_text.split(",") if part.strip()]


def replace_template_trackname_placeholders(
    project_folder: Path, files: list[Path], track_name: str
) -> int:
    replaced_count = 0
    for relative_path in files:
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise OSError(
                f"Replacement file must stay inside the project folder: {relative_path}"
            )
        destination = project_folder / relative_path
        text = destination.read_text(encoding="utf-8")
        updated = text.replace(TRACKNAME_PLACEHOLDER, track_name)
        if updated != text:
            destination.write_text(updated, encoding="utf-8")
            replaced_count += 1
    return replaced_count
