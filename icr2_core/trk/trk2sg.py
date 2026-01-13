# trk2sg.py
#
# Approximate TRK -> SG converter.
# - Reconstructs SG XY geometry from TRK section geometry + xsect centerline reconstruction.
# - Reconstructs SG alt/grade at section *end* boundaries by sampling TRK cubic at subsect=1.0
# - Reconstructs SG fsects from TRK ground/boundary DLAT ranges.
#
# Notes:
# - SG header[0:4] are set to 0 because your current SG->TRK path only relies on header[4:6]
#   (num_sects, num_xsects). You can replace these with real constants later if needed.
#
# Depends on your modules:
#   - trk_classes.TRKFile.from_trk
#   - sg_classes.SGFile + SGFile.output_sg
#   - trk_utils.get_cline_pos, sect2xy, heading2rad
#
# Usage:
#   python trk2sg.py input.trk output.sg

import argparse
import math
from typing import List, Tuple

from trk_classes import TRKFile
from sg_classes import SGFile
from trk_utils import get_cline_pos, sect2xy, heading2rad

FP_SCALE = 32768.0
SENTINEL = -858993460


def _wrap_idx(i: int, n: int) -> int:
    return i % n


def _cos_sin_fp(theta: float) -> Tuple[int, int]:
    # SGFile.Section.recompute_curve_length() interprets (sang1,sang2) as (cos,sin). :contentReference[oaicite:0]{index=0}
    return (int(round(math.cos(theta) * FP_SCALE)), int(round(math.sin(theta) * FP_SCALE)))


def _eval_alt_at_subsect(xsect_row: List[int], subsect: float) -> float:
    # TRK cubic in trk_utils.get_alt:
    # alt = g1*s^3 + g2*s^2 + g3*s + g4, where s is fraction [0..1]. :contentReference[oaicite:1]{index=1}
    g1, g2, g3, g4 = xsect_row[0], xsect_row[1], xsect_row[2], xsect_row[3]
    s = subsect
    return g1 * (s ** 3) + g2 * (s ** 2) + g3 * s + g4


def _slope_at_subsect(xsect_row: List[int], subsect: float, sect_length: int) -> float:
    # d/ds alt(s) = 3*g1*s^2 + 2*g2*s + g3
    # Convert to slope per unit distance along section: d(alt)/d(distance) = (d/ds)/sect_length
    g1, g2, g3 = xsect_row[0], xsect_row[1], xsect_row[2]
    s = subsect
    d_alt_ds = 3.0 * g1 * (s ** 2) + 2.0 * g2 * s + 1.0 * g3
    if sect_length == 0:
        return 0.0
    return d_alt_ds / float(sect_length)


def _trk_ground_to_sg(trk_ground: int) -> int:
    # TRK ground types are typically even values grouped by surface. :contentReference[oaicite:2]{index=2}
    # Map to SG ground ftype1 0..6 (Grass..Paint) consistent with sg_ground_to_trk(). :contentReference[oaicite:3]{index=3}
    if trk_ground in (0, 2, 4, 6):
        return 0
    if trk_ground in (8, 10, 12, 14):
        return 1
    if trk_ground in (16, 18, 20, 22):
        return 2
    if trk_ground in (24, 26, 28, 30):
        return 3
    if trk_ground in (32, 34, 36, 38):
        return 4
    if trk_ground in (40, 42, 44, 46):
        return 5
    if trk_ground in (48, 50, 52, 54):
        return 6
    # Fallback: bucket by nearest known type
    if trk_ground < 8:
        return 0
    if trk_ground < 16:
        return 1
    if trk_ground < 24:
        return 2
    if trk_ground < 32:
        return 3
    if trk_ground < 40:
        return 4
    if trk_ground < 48:
        return 5
    return 6


def _trk_wall_to_sg(trk_wall_type: int) -> Tuple[int, int]:
    # TRK wall type produced by convert_wall_fsect_type(): wall*4 + fence*2 (0,2,4,6). :contentReference[oaicite:4]{index=4}
    wall_bit = 1 if (trk_wall_type & 4) else 0  # 0=Armco, 1=Wall
    fence_bit = 1 if (trk_wall_type & 2) else 0  # 0=No fence, 1=Fence

    sg_type1 = 7 if wall_bit == 1 else 8      # 7=Wall, 8=Armco (per your mapping logic). :contentReference[oaicite:5]{index=5}
    sg_type2 = 2 if fence_bit == 1 else 0     # choose simplest representative
    return sg_type1, sg_type2


def trk_to_sg(trk: TRKFile) -> SGFile:
    num_sects = trk.num_sects
    num_xsects = trk.num_xsects

    # TRK stores 10 dlats in-file; only first num_xsects are active.
    xsect_dlats = list(map(int, trk.xsect_dlats[:num_xsects]))

    # SG header: enforce magic and version bytes (first 16 bytes):
    # 00 00 47 53 01 00 00 00 01 00 00 00 00 00 00 00
    # which corresponds to int32 values [0x53470000, 1, 1, 0]. :contentReference[oaicite:6]{index=6} :contentReference[oaicite:7]{index=7}
    header = [0x53470000, 1, 1, 0, int(num_sects), int(num_xsects)]

    cline = get_cline_pos(trk)  # provides (x,y) for straights, and (radius, sentinel) for curves. :contentReference[oaicite:8]{index=8}

    sg_sects: List[SGFile.Section] = []

    for i in range(num_sects):
        sec = trk.sects[i]
        j = _wrap_idx(i + 1, num_sects)

        # Reconstruct section endpoints in XY.
        start_x, start_y = sect2xy(trk, i, cline)
        end_x, end_y = sect2xy(trk, j, cline)

        start_x_i = int(round(start_x))
        start_y_i = int(round(start_y))
        end_x_i = int(round(end_x))
        end_y_i = int(round(end_y))

        # Geometry for straights/curves.
        if sec.type == 2:
            center_x = int(round(sec.ang1))
            center_y = int(round(sec.ang2))
            # Centerline radius inferred from cline[sect][0] in trk_utils.sect2xy. :contentReference[oaicite:9]{index=9}
            radius = int(round(cline[i][0]))
        else:
            center_x = 0
            center_y = 0
            radius = 0

        # Headings: use TRK heading at section start; end heading = next section heading (tangent continuity).
        h0 = heading2rad(sec.heading)
        h1 = heading2rad(trk.sects[j].heading)
        sang1, sang2 = _cos_sin_fp(h0)
        eang1, eang2 = _cos_sin_fp(h1)

        # Elevation: SG stores "alt/grade at the end of the section" (inferred from SG->TRK logic). :contentReference[oaicite:10]{index=10}
        alt_list: List[int] = []
        grade_list: List[int] = []
        for x in range(num_xsects):
            row = trk.sects[i].xsect_counter + x
            xrow = trk.xsect_data[row].tolist()
            alt_end = _eval_alt_at_subsect(xrow, 1.0)
            slope_end = _slope_at_subsect(xrow, 1.0, int(sec.length))
            sg_grade = int(round(slope_end * 8192.0))  # inverse of sg->trk conversion scale. :contentReference[oaicite:11]{index=11}

            alt_list.append(int(round(alt_end)))
            grade_list.append(sg_grade)

        # Fsects: build SG fsect list (up to 10). Ground types are 0..6; boundaries are type1>=7. :contentReference[oaicite:12]{index=12}
        ftype1: List[int] = []
        ftype2: List[int] = []
        fstart: List[int] = []
        fend: List[int] = []

        # Ground fsects
        for k in range(sec.ground_fsects):
            sg_g = _trk_ground_to_sg(int(sec.ground_type[k]))
            ftype1.append(int(sg_g))
            ftype2.append(0)
            fstart.append(int(sec.ground_dlat_start[k]))
            fend.append(int(sec.ground_dlat_end[k]))

        # Boundary fsects
        for k in range(sec.num_bounds):
            sg_t1, sg_t2 = _trk_wall_to_sg(int(sec.bound_type[k]))
            ftype1.append(int(sg_t1))
            ftype2.append(int(sg_t2))
            fstart.append(int(sec.bound_dlat_start[k]))
            fend.append(int(sec.bound_dlat_end[k]))

        # Clamp to SG limit.
        if len(ftype1) > 10:
            # Prefer keeping innermost ground transitions and all boundaries if possible; simplest: hard cut.
            ftype1 = ftype1[:10]
            ftype2 = ftype2[:10]
            fstart = fstart[:10]
            fend = fend[:10]

        # Build raw SG section int list to feed SGFile.Section(sec_data, num_xsects). :contentReference[oaicite:13]{index=13}
        # Layout:
        # [type, next, prev, start_x, start_y, end_x, end_y, start_dlong, length,
        #  center_x, center_y, sang1, sang2, eang1, eang2, radius, num1,
        #  (alt0,grade0)..., num_fsects, (ftype1,ftype2,fstart,fend)*, pad...]
        sec_next = j
        sec_prev = _wrap_idx(i - 1, num_sects)

        sec_data: List[int] = [
            int(sec.type),
            int(sec_next),
            int(sec_prev),
            int(start_x_i),
            int(start_y_i),
            int(end_x_i),
            int(end_y_i),
            int(sec.start_dlong),
            int(sec.length),
            int(center_x),
            int(center_y),
            int(sang1),
            int(sang2),
            int(eang1),
            int(eang2),
            int(radius),
            0,  # num1 unknown
        ]

        for x in range(num_xsects):
            sec_data.append(int(alt_list[x]))
            sec_data.append(int(grade_list[x]))

        sec_data.append(int(len(ftype1)))
        for k in range(len(ftype1)):
            sec_data.extend([int(ftype1[k]), int(ftype2[k]), int(fstart[k]), int(fend[k])])

        # Pad unused fsects to 10 entries (4 ints each)
        for _ in range(10 - len(ftype1)):
            sec_data.extend([0, 0, 0, 0])

        sg_sects.append(SGFile.Section(sec_data, num_xsects))

    return SGFile(header=header, num_sects=num_sects, num_xsects=num_xsects, xsect_dlats=xsect_dlats, sects=sg_sects)


def main():
    ap = argparse.ArgumentParser(description="Approximate TRK -> SG converter (with elevation).")
    ap.add_argument("trk", help="Input .trk file")
    ap.add_argument("sg", help="Output .sg file")
    args = ap.parse_args()

    trk = TRKFile.from_trk(args.trk)
    sg = trk_to_sg(trk)

    # Optional: rebuild DLONGs from 0, recomputing curve lengths geometrically
    # (useful if TRK has odd length rounding). :contentReference[oaicite:14]{index=14}
    sg.rebuild_dlongs(start_index=0, start_dlong=0)

    sg.output_sg(args.sg)


if __name__ == "__main__":
    main()
