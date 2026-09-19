"""Build Papyrus text ``.3D`` track geometry from a parsed TRK file.

This is a clean-room replacement for the surface-generating part of the old
DOS ``trk23d`` utility.  It deliberately uses the parsed :class:`TRKFile`
model rather than reading the binary format a second time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Sequence

if TYPE_CHECKING:
    from .trk_classes import TRKFile


Point3D = tuple[float, float, float]


@dataclass(frozen=True)
class Track3DOptions:
    """Controls mesh density and texture coordinate generation."""

    high_segment_length: int = 360_000
    medium_segment_length: int = 720_000
    low_segment_length: int = 1_440_000
    texture_units_per_texel: float = 2_000.0
    texture_wrap: int = 1_024

    def __post_init__(self) -> None:
        if min(
            self.high_segment_length,
            self.medium_segment_length,
            self.low_segment_length,
        ) <= 0:
            raise ValueError("LOD segment lengths must be positive")
        if self.texture_units_per_texel <= 0:
            raise ValueError("texture_units_per_texel must be positive")
        if self.texture_wrap <= 0:
            raise ValueError("texture_wrap must be positive")


@dataclass(frozen=True)
class SurfaceMaterial:
    name: str
    mip: str | None
    color: int

    @property
    def symbol(self) -> str:
        return f"__{self.name}__"


MATERIALS: tuple[SurfaceMaterial, ...] = (
    SurfaceMaterial("Grass", "GRASS", 240),
    SurfaceMaterial("DryGrass", "DRYGRASS", 144),
    SurfaceMaterial("Dirt", "DIRT", 208),
    # The stock utility emits sand and painted curbing without a texture unless
    # additional mark/sand options are supplied.
    SurfaceMaterial("Sand", None, 224),
    SurfaceMaterial("Concrete", "CONCRETE", 224),
    SurfaceMaterial("Asphalt", "ASPHALT", 248),
    SurfaceMaterial("Paint", None, 17),
)


def material_for_ground_type(ground_type: int) -> SurfaceMaterial:
    """Map the seven TRK surface families to their stock material."""

    family = max(0, min(6, int(ground_type) // 8))
    return MATERIALS[family]


def _heading_radians(heading: float) -> float:
    return (heading / 2**31) * math.pi


def _centerline_positions(trk: "TRKFile") -> list[tuple[float, float]]:
    dlats = list(trk.xsect_dlats[: trk.num_xsects])
    pair = next(
        (
            (idx - 1, idx)
            for idx in range(1, len(dlats))
            if dlats[idx - 1] <= 0 <= dlats[idx]
        ),
        None,
    )
    if pair is None:
        raise ValueError("TRK cross sections do not bracket DLAT zero")
    right, left = pair
    span = dlats[left] - dlats[right]
    fraction = 0.0 if span == 0 else -dlats[right] / span

    result: list[tuple[float, float]] = []
    for section in trk.sects:
        x = section.pos1[right] + fraction * (
            section.pos1[left] - section.pos1[right]
        )
        y = section.pos2[right] + fraction * (
            section.pos2[left] - section.pos2[right]
        )
        result.append((float(x), float(y)))
    return result


def _altitude(trk: "TRKFile", section_index: int, fraction: float, dlat: float) -> float:
    dlats = list(trk.xsect_dlats[: trk.num_xsects])
    if dlat <= dlats[0]:
        right = left = 0
    elif dlat >= dlats[-1]:
        right = left = len(dlats) - 1
    else:
        right = next(i for i in range(len(dlats) - 1) if dlats[i] <= dlat < dlats[i + 1])
        left = right + 1

    def at(xsection: int) -> float:
        g1, g2, g3, base = trk.xsect_data[
            section_index * trk.num_xsects + xsection
        ][:4]
        return float(g1 * fraction**3 + g2 * fraction**2 + g3 * fraction + base)

    right_alt = at(right)
    if left == right:
        return right_alt
    lateral_fraction = (dlat - dlats[right]) / (dlats[left] - dlats[right])
    return right_alt + (at(left) - right_alt) * lateral_fraction


def _xyz(
    trk: "TRKFile",
    centerline: Sequence[tuple[float, float]],
    section_index: int,
    fraction: float,
    dlat: float,
) -> Point3D:
    section = trk.sects[section_index]
    fraction = max(0.0, min(1.0, fraction))
    if section.type == 1:
        start_x, start_y = centerline[section_index]
        end_x, end_y = centerline[(section_index + 1) % trk.num_sects]
        center_x = start_x + (end_x - start_x) * fraction
        center_y = start_y + (end_y - start_y) * fraction
        left_angle = _heading_radians(section.heading) + math.pi / 2
        x = center_x + dlat * math.cos(left_angle)
        y = center_y + dlat * math.sin(left_angle)
    elif section.type == 2:
        radius = centerline[section_index][0] - dlat
        start_angle = _heading_radians(section.heading) - math.pi / 2
        next_heading = trk.sects[(section_index + 1) % trk.num_sects].heading
        end_angle = _heading_radians(next_heading) - math.pi / 2
        sweep = (end_angle - start_angle + math.pi) % (2 * math.pi) - math.pi
        angle = start_angle + sweep * fraction
        x = section.ang1 + radius * math.cos(angle)
        y = section.ang2 + radius * math.sin(angle)
    else:
        raise ValueError(f"Unsupported TRK section type {section.type!r}")
    return x, y, _altitude(trk, section_index, fraction, dlat)


def _lerp(start: float, end: float, fraction: float) -> float:
    return start + (end - start) * fraction


def _wrapped_texture_coordinate(value: float, wrap: int) -> float:
    """Reflect a coordinate between zero and ``wrap``.

    The stock TRK23D output reverses texture direction when the next run would
    leave the valid texture-coordinate range.  The equivalent triangle wave
    keeps every generated value nonnegative without introducing a modulo seam.
    """

    period = 2 * wrap
    position = value % period
    return position if position <= wrap else period - position


def _lateral_texture_origin(trk: "TRKFile") -> float:
    """Return the rightmost DLAT used by any textured ground polygon."""

    values = []
    for section in trk.sects:
        values.extend(section.bound_dlat_start)
        values.extend(section.bound_dlat_end)
        values.extend(section.ground_dlat_start)
        values.extend(section.ground_dlat_end)
    if not values:
        return 0.0
    return float(min(values))


def _straight_vertical_divisions(
    trk: "TRKFile",
    section_index: int,
    start_fraction: float = 0.0,
    end_fraction: float = 1.0,
) -> int:
    """Match TRK23D's recursive elevation-error subdivision test."""

    span = end_fraction - start_fraction
    quarter = start_fraction + span * 0.25
    three_quarters = start_fraction + span * 0.75
    midpoint = start_fraction + span * 0.5

    for dlat in (150_000.0, -150_000.0):
        z0 = _altitude(trk, section_index, start_fraction, dlat)
        z1 = _altitude(trk, section_index, end_fraction, dlat)
        z25 = _altitude(trk, section_index, quarter, dlat)
        z75 = _altitude(trk, section_index, three_quarters, dlat)
        error = abs(z25 - _lerp(z0, z1, 0.25)) + abs(
            z75 - _lerp(z0, z1, 0.75)
        )
        if error >= 10_000:
            return _straight_vertical_divisions(
                trk, section_index, start_fraction, midpoint
            ) + _straight_vertical_divisions(
                trk, section_index, midpoint, end_fraction
            )
    return 1


def _high_detail_divisions(
    trk: "TRKFile",
    section_index: int,
    nominal_length: int,
) -> int:
    """Return the stock TRK23D HI FACE count for one TRK section."""

    section = trk.sects[section_index]
    divisions = (int(section.length) + nominal_length // 2) // nominal_length
    if section.type == 1:
        divisions = max(
            divisions,
            _straight_vertical_divisions(trk, section_index),
        )
    elif section.type == 2:
        # CurveSection::numSegments derives the centerline radius from the
        # first cross section, then truncates this value before applying the
        # common multiple-of-four rule below.
        radius = float(section.pos1[0] + trk.xsect_dlats[0])
        curve_divisions = int(
            math.sqrt(abs(radius))
            / 40.0
            * abs(float(section.ang3))
            / float(2**30)
        )
        divisions = max(divisions, curve_divisions)
    divisions = max(1, divisions)
    if divisions > 2:
        divisions = ((divisions + 3) // 4) * 4
    return divisions


def _section_polygons(
    trk: "TRKFile",
    centerline: Sequence[tuple[float, float]],
    section_index: int,
    start_fraction: float,
    end_fraction: float,
    texture_units_per_texel: float,
    texture_wrap: int,
) -> list[
    tuple[
        tuple[Point3D, Point3D, Point3D, Point3D],
        int,
        tuple[float, float, float, float, float, float],
    ]
]:
    section = trk.sects[section_index]
    if section.ground_fsects <= 0 or section.num_bounds <= 0:
        return []
    fractions = {start_fraction, end_fraction}

    # Add vertices exactly where the reflected longitudinal texture coordinate
    # changes direction.  Without these splits, a polygon spanning a turning
    # point would interpolate across the texture instead of reaching its edge.
    wrap_distance = texture_units_per_texel * texture_wrap
    start_dlong = section.start_dlong + section.length * start_fraction
    end_dlong = section.start_dlong + section.length * end_fraction
    first_turn = math.floor(start_dlong / wrap_distance) + 1
    turn_dlong = first_turn * wrap_distance
    while turn_dlong < end_dlong:
        fractions.add((turn_dlong - section.start_dlong) / section.length)
        turn_dlong += wrap_distance
    ordered_fractions = sorted(fractions)
    polygons = []
    for f0, f1 in zip(ordered_fractions, ordered_fractions[1:]):
        left0 = _lerp(section.bound_dlat_start[-1], section.bound_dlat_end[-1], f0)
        left1 = _lerp(section.bound_dlat_start[-1], section.bound_dlat_end[-1], f1)
        for ground in range(section.ground_fsects - 1, -1, -1):
            right0 = _lerp(
                section.ground_dlat_start[ground],
                section.ground_dlat_end[ground],
                f0,
            )
            right1 = _lerp(
                section.ground_dlat_start[ground],
                section.ground_dlat_end[ground],
                f1,
            )
            points = (
                _xyz(trk, centerline, section_index, f0, left0),
                _xyz(trk, centerline, section_index, f1, left1),
                _xyz(trk, centerline, section_index, f1, right1),
                _xyz(trk, centerline, section_index, f0, right0),
            )
            polygons.append(
                (
                    points,
                    int(section.ground_type[ground]),
                    (f0, f1, left0, left1, right0, right1),
                )
            )
            left0, left1 = right0, right1
    return polygons


def _number(value: float) -> str:
    return str(int(round(value)))


def _point(point: Point3D) -> str:
    return f"[<{_number(point[0])}, {_number(point[1])}, {_number(point[2])}>]"


def _textured_point(point: Point3D, u: float, v: float) -> str:
    return (
        f"[<{_number(point[0])}, {_number(point[1])}, {_number(point[2])}>, "
        f"t= <{_number(u)}, {_number(v)}>]"
    )


def _nondegenerate_plane(polygons: Iterable[tuple]) -> tuple[Point3D, Point3D, Point3D]:
    for points, _ground_type, _texture_data in polygons:
        a, b, c = points[:3]
        cross = (
            (b[1] - a[1]) * (c[2] - a[2]) - (b[2] - a[2]) * (c[1] - a[1]),
            (b[2] - a[2]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[2] - a[2]),
            (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]),
        )
        if any(abs(value) > 0.01 for value in cross):
            return a, b, c
    raise ValueError("Section has no non-degenerate surface polygons")


def _face_block(
    trk: "TRKFile",
    centerline: Sequence[tuple[float, float]],
    section_index: int,
    segment_index: int,
    segment_count: int,
    lod: str,
    options: Track3DOptions,
    lateral_origin: float,
) -> list[str]:
    section = trk.sects[section_index]
    start_fraction = segment_index / segment_count
    end_fraction = (segment_index + 1) / segment_count
    polygons = _section_polygons(
        trk,
        centerline,
        section_index,
        start_fraction,
        end_fraction,
        options.texture_units_per_texel,
        options.texture_wrap,
    )
    if not polygons:
        return [f"sec{section_index}_s{segment_index}_{lod}: NIL;"]
    plane = _nondegenerate_plane(polygons)
    start = int(section.start_dlong + section.length * start_fraction)
    end = int(section.start_dlong + section.length * end_fraction)
    topo_left = f"TOPO_sec{section_index}_s{segment_index}_L_{lod}"
    topo_right = f"TOPO_sec{section_index}_s{segment_index}_R_{lod}"
    tso_left = f"TSO_sec{section_index}_s{segment_index}_L"
    tso_right = f"TSO_sec{section_index}_s{segment_index}_R"
    plane_text = ", ".join(_point(point) for point in plane)
    lines = [
        f"{topo_left}: NIL;",
        f"{topo_right}: NIL;",
    ]
    if lod == "HI":
        lines.extend(
            [
                f"{tso_left}: NIL;",
                f"{tso_right}: NIL;",
            ]
        )
    lines.extend(
        [
        f"% Outputing section from dlong = {start} to dlong = {end}",
        f"sec{section_index}_s{segment_index}_{lod}: FACE ({plane_text}),",
        "LIST {",
        # BSPA has three child slots. SegmentTsoInfo expects the inner node's
        # first child and the outer node's third child to be the left/right TSO
        # lists respectively. Keep explicit NIL placeholders for both wall
        # branches and the unused third inner branch so later materials cannot
        # slide into one of those fixed slots.
        f"  BSPA ({plane_text}),",
        f"    BSPA ({plane_text}),",
        f"      LIST {{ {topo_left}, {tso_left} }},",
        "      nil,",
        "      nil,",
        "    nil,",
        f"    LIST {{ {topo_right}, {tso_right} }},",
        ]
    )
    scale = options.texture_units_per_texel
    for points, ground_type, texture_data in polygons:
        f0, f1, left0, left1, right0, right1 = texture_data
        material = material_for_ground_type(ground_type)
        # Stock TRK23D maps lateral position to U and longitudinal distance to
        # V.  DLAT is signed, so shift it by the track's rightmost extent before
        # scaling.  V is reflected into the legal nonnegative texture span.
        u_left0 = (left0 - lateral_origin) / scale
        u_left1 = (left1 - lateral_origin) / scale
        u_right0 = (right0 - lateral_origin) / scale
        u_right1 = (right1 - lateral_origin) / scale
        v0 = _wrapped_texture_coordinate(
            (section.start_dlong + section.length * f0) / scale,
            options.texture_wrap,
        )
        v1 = _wrapped_texture_coordinate(
            (section.start_dlong + section.length * f1) / scale,
            options.texture_wrap,
        )
        texture_points = (
            _textured_point(points[0], u_left0, v0),
            _textured_point(points[1], u_left1, v1),
            _textured_point(points[2], u_right1, v1),
            _textured_point(points[3], u_right0, v0),
        )
        if material.mip is None:
            lines.extend(
                [
                    f"  POLY {material.symbol}.c {{",
                    "    " + ",\n    ".join(_point(point) for point in points),
                    "  },",
                ]
            )
        else:
            lines.extend(
                [
                    f'  MATERIAL GROUP = 2, MIP = "{material.mip}",',
                    f"  POLY [T] {material.symbol}.c {{",
                    "    " + ",\n    ".join(texture_points),
                    "  },",
                ]
            )
    lines.extend(["  nil", "};", ""])
    return lines


def _validate_trk(trk: "TRKFile") -> None:
    if trk.num_sects <= 0 or len(trk.sects) != trk.num_sects:
        raise ValueError("TRK contains no usable sections")
    if trk.num_xsects < 2:
        raise ValueError("TRK needs at least two cross sections")
    if any(section.length <= 0 for section in trk.sects):
        raise ValueError("TRK section lengths must be positive")


def build_track3d_text(
    trk: "TRKFile",
    *,
    track_name: str = "track",
    options: Track3DOptions | None = None,
) -> str:
    """Return a complete Papyrus text ``.3D`` surface for ``trk``."""

    _validate_trk(trk)
    options = options or Track3DOptions()
    centerline = _centerline_positions(trk)
    lateral_origin = _lateral_texture_origin(trk)
    lines = [
        "3D VERSION 3.0;",
        f"% Track {track_name} (generated by icr2tools trk23d)",
        f"% Sections {trk.num_sects}",
        "nil: NIL;",
        "",
    ]
    lines.extend(f"{m.symbol}: [<0, 0, 0>, c= <{m.color}>];" for m in MATERIALS)
    lines.append("")

    layout_entries: list[tuple[str, int]] = []
    for section_index in range(trk.num_sects):
        high_count = _high_detail_divisions(
            trk, section_index, options.high_segment_length
        )
        lod_counts = (
            ("HI", high_count),
            ("MED", (high_count + 1) // 2),
            ("LO", (high_count + 3) // 4),
        )
        for lod, segment_count in lod_counts:
            for segment_index in range(segment_count):
                lines.extend(
                    _face_block(
                        trk,
                        centerline,
                        section_index,
                        segment_index,
                        segment_count,
                        lod,
                        options,
                        lateral_origin,
                    )
                )
        section = trk.sects[section_index]
        layout_count = (high_count + 3) // 4
        medium_count = (high_count + 1) // 2
        low_count = (high_count + 3) // 4
        for layout_index in range(layout_count):
            high_start = layout_index * 4
            medium_start = layout_index * 2
            high_refs = [
                f"sec{section_index}_s{segment}_HI" if segment < high_count else "nil"
                for segment in range(high_start, high_start + 4)
            ]
            medium_refs = [
                f"sec{section_index}_s{segment}_MED"
                if segment < medium_count
                else "nil"
                for segment in range(medium_start, medium_start + 2)
            ]
            low_ref = (
                f"sec{section_index}_s{layout_index}_LO"
                if layout_index < low_count
                else "nil"
            )
            valid_high = min(high_count - 1, high_start + 3)
            dlongs = [
                int(
                    section.start_dlong
                    + section.length * min(segment, valid_high) / high_count
                )
                for segment in range(high_start, high_start + 4)
            ]
            layout_name = f"sec{section_index}_l{layout_index}"
            layout_entries.append((layout_name, dlongs[0]))
            lines.extend(
                [
                    f"{layout_name}: LIST {{ {', '.join(high_refs)}, "
                    f"{', '.join(medium_refs)}, {low_ref}, "
                    f"DATA {{ {', '.join(map(str, dlongs))} }} }};",
                    "",
                ]
            )

    hash_values = []
    dlong = 0
    while dlong < int(trk.trklength):
        layout_index = max(
            i for i, (_name, start) in enumerate(layout_entries) if start <= dlong
        )
        # The hash contains the global layout index for each 0x40000-DLONG
        # bucket. Sections with multiple layouts therefore consume multiple
        # consecutive index values.
        hash_values.append(layout_index)
        dlong += 0x40000
    lines.append("hash: DATA { " + ", ".join(map(str, hash_values)) + " };")
    index_entries = ["hash"] + [name for name, _start in layout_entries]
    lines.append("index: LIST { " + ", ".join(index_entries) + " };")
    return "\n".join(lines) + "\n"


def write_track3d(
    trk: "TRKFile",
    output_path: str | Path,
    *,
    track_name: str | None = None,
    options: Track3DOptions | None = None,
) -> Path:
    """Generate a text ``.3D`` file and return its path."""

    path = Path(output_path)
    text = build_track3d_text(
        trk,
        track_name=track_name or path.stem,
        options=options,
    )
    path.write_text(text, encoding="latin-1", newline="\n")
    return path
