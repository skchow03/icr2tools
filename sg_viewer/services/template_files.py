from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

TRACKNAME_PLACEHOLDER = "<<trackname>>"


@dataclass(frozen=True)
class TemplateCopyResult:
    copied_files: list[Path]
    skipped_files: list[Path]
    directory_count: int


def parse_template_trackname_files(files_text: str) -> list[Path]:
    return [Path(part.strip()) for part in files_text.split(",") if part.strip()]


def copy_template_files_without_overwrite(
    template_folder: Path, project_folder: Path
) -> TemplateCopyResult:
    copied_files: list[Path] = []
    skipped_files: list[Path] = []
    directory_count = 0

    for source in template_folder.rglob("*"):
        relative_path = source.relative_to(template_folder)
        destination = project_folder / relative_path
        if source.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            directory_count += 1
            continue
        if not source.is_file():
            continue
        if destination.exists():
            skipped_files.append(relative_path)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied_files.append(relative_path)

    return TemplateCopyResult(copied_files, skipped_files, directory_count)


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
