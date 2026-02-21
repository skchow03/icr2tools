from __future__ import annotations

from dataclasses import dataclass
import re

from sg_viewer.model.dlong_mapping import dlong_to_section_position
from sg_viewer.model.preview_fsection import PreviewFSection
from sg_viewer.model.sg_model import SectionPreview


_MARK_HEADER = "MARK_V1"
_POS_RE = re.compile(r"^(?P<section>-?\d+)\s+(?P<fraction>-?(?:\d+(?:\.\d*)?|\.\d+))$")
_ENTRY_RE = re.compile(
    r'^(?P<name>[^:]+):\s*Boundary\s+(?P<boundary>\d+)\s+"(?P<mip>[^"]+)"\s*<\s*(?P<u1>-?\d+)\s*,\s*(?P<v1>-?\d+)\s*>\s*-\s*<\s*(?P<u2>-?\d+)\s*,\s*(?P<v2>-?\d+)\s*>$'
)
_END_RE = re.compile(r"^End\s+(?P<name>.+)$")


@dataclass(frozen=True)
class MarkTrackPosition:
    section: int
    fraction: float


@dataclass(frozen=True)
class MarkUvRect:
    upper_left_u: int
    upper_left_v: int
    lower_right_u: int
    lower_right_v: int


@dataclass(frozen=True)
class MarkBoundaryEntry:
    pointer_name: str
    boundary_id: int
    mip_name: str
    uv_rect: MarkUvRect
    start: MarkTrackPosition
    end: MarkTrackPosition


@dataclass(frozen=True)
class MarkFile:
    entries: tuple[MarkBoundaryEntry, ...]
    version: str = _MARK_HEADER


@dataclass(frozen=True)
class MarkTextureSpec:
    mip_name: str
    uv_rect: MarkUvRect


def _strip_comment(line: str) -> str:
    return line.split("##", 1)[0].strip()


def _parse_position(line: str, *, line_number: int) -> MarkTrackPosition:
    match = _POS_RE.match(line)
    if not match:
        raise ValueError(f"Expected section/fraction at line {line_number}: {line!r}")
    section = int(match.group("section"))
    fraction = float(match.group("fraction"))
    if fraction < 0.0 or fraction > 1.0:
        raise ValueError(f"Track fraction must be in [0, 1] at line {line_number}, got {fraction}")
    return MarkTrackPosition(section=section, fraction=fraction)


def parse_mrk_text(text: str) -> MarkFile:
    lines = [_strip_comment(raw) for raw in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        raise ValueError("MRK file is empty")
    if lines[0] != _MARK_HEADER:
        raise ValueError(f"Expected MRK header {_MARK_HEADER!r}, got {lines[0]!r}")

    entries: list[MarkBoundaryEntry] = []
    seen_names: set[str] = set()
    index = 1

    while index < len(lines):
        start = _parse_position(lines[index], line_number=index + 1)
        if index + 1 >= len(lines):
            raise ValueError("Unexpected end of file after start position")
        entry_line = lines[index + 1]
        entry_match = _ENTRY_RE.match(entry_line)
        if not entry_match:
            raise ValueError(f"Expected boundary entry at line {index + 2}: {entry_line!r}")

        pointer_name = entry_match.group("name").strip()
        if pointer_name in seen_names:
            raise ValueError(f"Duplicate pointer name {pointer_name!r}")
        seen_names.add(pointer_name)

        if index + 3 >= len(lines):
            raise ValueError(f"Unexpected end of file while parsing entry {pointer_name!r}")
        end = _parse_position(lines[index + 2], line_number=index + 3)
        end_match = _END_RE.match(lines[index + 3])
        if not end_match:
            raise ValueError(f"Expected entry terminator at line {index + 4}: {lines[index + 3]!r}")
        end_name = end_match.group("name").strip()
        if end_name != pointer_name:
            raise ValueError(
                f"Entry terminator mismatch at line {index + 4}: expected {pointer_name!r}, got {end_name!r}"
            )

        entries.append(
            MarkBoundaryEntry(
                pointer_name=pointer_name,
                boundary_id=int(entry_match.group("boundary")),
                mip_name=entry_match.group("mip"),
                uv_rect=MarkUvRect(
                    upper_left_u=int(entry_match.group("u1")),
                    upper_left_v=int(entry_match.group("v1")),
                    lower_right_u=int(entry_match.group("u2")),
                    lower_right_v=int(entry_match.group("v2")),
                ),
                start=start,
                end=end,
            )
        )

        index += 4

    return MarkFile(entries=tuple(entries))


def _format_fraction(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def serialize_mrk(mark_file: MarkFile) -> str:
    lines = [mark_file.version]
    for entry in mark_file.entries:
        lines.append(f"{entry.start.section} {_format_fraction(entry.start.fraction)}")
        lines.append(
            f'{entry.pointer_name}: Boundary {entry.boundary_id} "{entry.mip_name}" '
            f"<{entry.uv_rect.upper_left_u},{entry.uv_rect.upper_left_v}> - "
            f"<{entry.uv_rect.lower_right_u},{entry.uv_rect.lower_right_v}>"
        )
        lines.append(f"{entry.end.section} {_format_fraction(entry.end.fraction)}")
        lines.append(f"End {entry.pointer_name}")
    return "\n".join(lines) + "\n"


_BOUNDARY_TYPES = {7, 8}
_DEFAULT_MARK_WALL_LENGTH = 14.0 * 6000.0


def _boundary_rows_for_section(fsects: list[PreviewFSection]) -> list[PreviewFSection]:
    rows = [fsect for fsect in fsects if int(fsect.surface_type) in _BOUNDARY_TYPES]
    rows.sort(
        key=lambda fsect: (
            min(float(fsect.start_dlat), float(fsect.end_dlat)),
            max(float(fsect.start_dlat), float(fsect.end_dlat)),
        )
    )
    return rows


def generate_wall_mark_file(
    *,
    sections: list[SectionPreview],
    fsects_by_section: list[list[PreviewFSection]],
    mip_name: str,
    uv_rect: MarkUvRect,
    texture_pattern: tuple[MarkTextureSpec, ...] | None = None,
    target_wall_length: float = _DEFAULT_MARK_WALL_LENGTH,
) -> MarkFile:
    if not sections:
        return MarkFile(entries=())
    if len(sections) != len(fsects_by_section):
        raise ValueError("Section count does not match fsection count")

    track_length = sum(max(0.0, float(section.length)) for section in sections)
    if track_length <= 0.0:
        return MarkFile(entries=())

    textures = texture_pattern
    if textures is None:
        textures = (MarkTextureSpec(mip_name=mip_name, uv_rect=uv_rect),)
    if not textures:
        raise ValueError("At least one texture specification is required")
    if any(not texture.mip_name.strip() for texture in textures):
        raise ValueError("Texture MIP file names cannot be empty")

    boundaries: dict[int, list[tuple[float, float]]] = {}
    for section, fsects in zip(sections, fsects_by_section):
        section_start = float(section.start_dlong)
        section_end = section_start + max(0.0, float(section.length))
        if section_end <= section_start:
            continue
        for boundary_id, _boundary in enumerate(_boundary_rows_for_section(fsects)):
            boundaries.setdefault(boundary_id, []).append((section_start, section_end))

    entries: list[MarkBoundaryEntry] = []
    for boundary_id, spans in sorted(boundaries.items()):
        wall_index = 0
        for span_start, span_end in sorted(spans, key=lambda span: span[0]):
            span_length = span_end - span_start
            segment_count = max(1, int(round(span_length / target_wall_length)))
            spacing = span_length / float(segment_count)
            for index in range(segment_count):
                start_dlong = span_start + spacing * index
                end_dlong = span_start + spacing * (index + 1)
                start = dlong_to_section_position(sections, start_dlong, track_length)
                end = dlong_to_section_position(sections, end_dlong, track_length)
                if start is None or end is None:
                    continue
                texture = textures[wall_index % len(textures)]
                entries.append(
                    MarkBoundaryEntry(
                        pointer_name=f"b{boundary_id}_wall{wall_index:04d}",
                        boundary_id=boundary_id,
                        mip_name=texture.mip_name,
                        uv_rect=texture.uv_rect,
                        start=MarkTrackPosition(
                            section=start.section_index,
                            fraction=start.fraction,
                        ),
                        end=MarkTrackPosition(
                            section=end.section_index,
                            fraction=end.fraction,
                        ),
                    )
                )
                wall_index += 1

    return MarkFile(entries=tuple(entries))
