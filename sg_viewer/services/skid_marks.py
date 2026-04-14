from __future__ import annotations

from dataclasses import dataclass
import random

from sg_viewer.services.tsd_io import TrackSurfaceDetailLine

DEFAULT_SKID_COLORS: tuple[int, ...] = (45, 28, 44, 29)


@dataclass(frozen=True)
class SkidMarkSectionParameters:
    section_name: str
    start_dlong: int
    apex_dlong: int
    end_dlong: int
    min_length: int
    max_length: int
    width_500ths: int
    num_skids: int
    start_dlat_a: int
    start_dlat_b: int
    apex_dlat_a: int
    apex_dlat_b: int
    end_dlat_a: int
    end_dlat_b: int


@dataclass(frozen=True)
class SkidMarkGenerationParameters:
    colors: tuple[int, ...]
    sections: tuple[SkidMarkSectionParameters, ...]


def parse_skid_sections_csv(csv_text: str) -> tuple[SkidMarkSectionParameters, ...]:
    rows: list[SkidMarkSectionParameters] = []
    for line in csv_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        columns = [part.strip() for part in stripped.split(",")]
        if len(columns) != 14:
            raise ValueError("Each row must contain exactly 14 comma-separated values.")
        rows.append(
            SkidMarkSectionParameters(
                section_name=columns[0],
                start_dlong=int(columns[1]),
                apex_dlong=int(columns[2]),
                end_dlong=int(columns[3]),
                min_length=int(columns[4]),
                max_length=int(columns[5]),
                width_500ths=max(1, int(columns[6])),
                num_skids=max(0, int(columns[7])),
                start_dlat_a=int(columns[8]),
                start_dlat_b=int(columns[9]),
                apex_dlat_a=int(columns[10]),
                apex_dlat_b=int(columns[11]),
                end_dlat_a=int(columns[12]),
                end_dlat_b=int(columns[13]),
            )
        )
    return tuple(rows)


def parse_colors_csv(colors_text: str) -> tuple[int, ...]:
    values = [part.strip() for part in colors_text.split(",") if part.strip()]
    if not values:
        return DEFAULT_SKID_COLORS
    return tuple(int(value) for value in values)


def generate_skid_mark_lines(
    parameters: SkidMarkGenerationParameters,
    *,
    rng: random.Random | None = None,
) -> tuple[TrackSurfaceDetailLine, ...]:
    generator = rng or random.Random()
    lines: list[TrackSurfaceDetailLine] = []
    for section in parameters.sections:
        start_dlat_min = min(section.start_dlat_a, section.start_dlat_b)
        start_dlat_max = max(section.start_dlat_a, section.start_dlat_b)
        apex_dlat_min = min(section.apex_dlat_a, section.apex_dlat_b)
        apex_dlat_max = max(section.apex_dlat_a, section.apex_dlat_b)
        end_dlat_min = min(section.end_dlat_a, section.end_dlat_b)
        end_dlat_max = max(section.end_dlat_a, section.end_dlat_b)
        entry_length = section.apex_dlong - section.start_dlong
        exit_length = section.end_dlong - section.apex_dlong

        min_length = min(section.min_length, section.max_length)
        max_length = max(section.min_length, section.max_length)
        for _index in range(section.num_skids):
            length_upper = max(min_length + 1, max_length)
            length = generator.randrange(min_length, length_upper)
            start_upper = section.end_dlong - length
            if start_upper <= section.start_dlong:
                continue
            start_skid = generator.randrange(section.start_dlong, start_upper)
            end_skid = start_skid + length

            start_low, start_high = _interpolate_dlat_range(
                section,
                dlong=start_skid,
                entry_length=entry_length,
                exit_length=exit_length,
                start_min=start_dlat_min,
                start_max=start_dlat_max,
                apex_min=apex_dlat_min,
                apex_max=apex_dlat_max,
                end_min=end_dlat_min,
                end_max=end_dlat_max,
            )
            end_low, end_high = _interpolate_dlat_range(
                section,
                dlong=end_skid,
                entry_length=entry_length,
                exit_length=exit_length,
                start_min=start_dlat_min,
                start_max=start_dlat_max,
                apex_min=apex_dlat_min,
                apex_max=apex_dlat_max,
                end_min=end_dlat_min,
                end_max=end_dlat_max,
            )
            if start_high <= start_low:
                dlat = start_low
                ratio = 0.5
            else:
                dlat = generator.randrange(start_low, start_high)
                ratio = (dlat - start_low) / (start_high - start_low)
            dlat2 = int(end_low + (end_high - end_low) * ratio)
            lines.append(
                TrackSurfaceDetailLine(
                    color_index=generator.choice(parameters.colors or DEFAULT_SKID_COLORS),
                    width_500ths=max(1, int(section.width_500ths)),
                    start_dlong=int(start_skid),
                    start_dlat=int(dlat),
                    end_dlong=int(end_skid),
                    end_dlat=int(dlat2),
                    command="Detail",
                )
            )
    return tuple(lines)


def _interpolate_dlat_range(
    section: SkidMarkSectionParameters,
    *,
    dlong: int,
    entry_length: int,
    exit_length: int,
    start_min: int,
    start_max: int,
    apex_min: int,
    apex_max: int,
    end_min: int,
    end_max: int,
) -> tuple[int, int]:
    if dlong <= section.apex_dlong and entry_length != 0:
        position = (dlong - section.start_dlong) / entry_length
        low = start_min + (apex_min - start_min) * position
        high = start_max + (apex_max - start_max) * position
        return int(low), int(high)
    if exit_length == 0:
        return int(apex_min), int(apex_max)
    position = (dlong - section.apex_dlong) / exit_length
    low = apex_min + (end_min - apex_min) * position
    high = apex_max + (end_max - apex_max) * position
    return int(low), int(high)
