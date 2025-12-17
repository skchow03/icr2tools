from __future__ import annotations

import math
from dataclasses import replace
from typing import Optional, Tuple

from sg_viewer.models.sg_model import SectionPreview
from sg_viewer.geometry.curve_solver import _solve_curve_with_fixed_heading
from sg_viewer.geometry.sg_geometry import update_section_geometry

DEBUG_CURVE_STRAIGHT = True

def _deg_between(a, b):
    dot = max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1]))
    return math.degrees(math.acos(dot))


def _angle_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Return angle between two unit vectors in radians."""
    dot = max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1]))
    return math.acos(dot)


def _straight_forward_heading(straight: SectionPreview) -> Optional[tuple[float, float]]:
    heading = straight.start_heading
    if heading is None:
        heading = (
            straight.end[0] - straight.start[0],
            straight.end[1] - straight.start[1],
        )

    h_len = math.hypot(heading[0], heading[1])
    if h_len <= 0:
        return None

    return heading[0] / h_len, heading[1] / h_len


def solve_curve_end_to_straight_start(
    curve: SectionPreview,
    straight: SectionPreview,
    heading_tolerance_deg: float = 2.0,
) -> Optional[Tuple[SectionPreview, SectionPreview]]:
    """
    Attempt to refit a curve so that:
      - curve start + start heading are preserved
      - curve end meets straight start
      - curve end heading matches straight heading
      - straight slides along its heading (length preserved)

    Returns (new_curve, new_straight) or None on failure.
    """



    # ------------------------
    # Preconditions
    # ------------------------
    if curve.type_name != "curve":
        return None
    if straight.type_name != "straight":
        return None

    curve_start = curve.start
    curve_start_heading = curve.start_heading
    if curve_start_heading is None:
        return None

    straight_heading = _straight_forward_heading(straight)
    if straight_heading is None:
        return None

    # Normalize straight heading
    sh_len = math.hypot(straight_heading[0], straight_heading[1])
    if sh_len <= 0:
        return None
    straight_heading = (straight_heading[0] / sh_len, straight_heading[1] / sh_len)
    hx, hy = straight_heading

    if DEBUG_CURVE_STRAIGHT:
        print("\n=== CURVE → STRAIGHT SOLVE ATTEMPT ===")
        print("Curve start:", curve.start)
        print("Curve end (original):", curve.end)
        print("Curve start heading:", curve.start_heading)
        print("Curve radius:", curve.radius)
        print("Straight start:", straight.start)
        print("Straight end:", straight.end)
        print("Straight length:", straight.length)
        print("Straight forward heading:", straight_heading)
    if DEBUG_CURVE_STRAIGHT:
        sh = straight_heading
        angle = math.degrees(math.atan2(sh[1], sh[0]))
        print(f"Straight heading angle: {angle:.2f}°")
    if DEBUG_CURVE_STRAIGHT:
        ch = curve.start_heading
        angle = math.degrees(math.atan2(ch[1], ch[0]))
        print(f"Curve start heading angle: {angle:.2f}°")


    # ------------------------
    # Solve curve by scanning along straight heading
    # ------------------------
    heading_tol = math.radians(heading_tolerance_deg)

    # Prefer minimal radius change, then minimal arc length
    def score(c: SectionPreview) -> float:
        radius_delta = 0.0
        if curve.radius is not None and c.radius is not None:
            radius_delta = abs(abs(c.radius) - abs(curve.radius))
        return radius_delta * 10.0 + c.length

    offsets = [-100, -50, -25, 0, 25, 50, 100]

    best_solution: Optional[SectionPreview] = None

    for t in offsets:
        P = (
            straight.start[0] + hx * t,
            straight.start[1] + hy * t,
        )

        if DEBUG_CURVE_STRAIGHT:
            print(f"\nTrying join point P = {P}")


        curve_template = replace(
            curve,
            start=curve_start,
            end=P,
            polyline=[curve_start, P],
        )

        candidates = _solve_curve_with_fixed_heading(
            sect=curve_template,
            start=curve_start,
            end=P,
            fixed_point=curve_start,
            fixed_heading=curve_start_heading,
            fixed_point_is_start=True,
            orientation_hint=1.0,
        )
        if DEBUG_CURVE_STRAIGHT:
            print("  Candidates returned:", len(candidates))



        if not candidates:
            continue

        valid: list[SectionPreview] = []

        for cand in candidates:
            if cand.end_heading is None:
                if DEBUG_CURVE_STRAIGHT:
                    print("  Reject: no end heading")
                continue

            # normalize candidate end heading
            eh = cand.end_heading
            eh_len = math.hypot(eh[0], eh[1])
            if eh_len <= 0:
                if DEBUG_CURVE_STRAIGHT:
                    print("  Reject: zero end heading vector")
                continue
            eh = (eh[0] / eh_len, eh[1] / eh_len)
            delta = _deg_between(eh, straight_heading)

            if DEBUG_CURVE_STRAIGHT:
                print(
                    f"  Candidate: radius={cand.radius:.1f}, "
                    f"arc_len={cand.length:.1f}, "
                    f"end_heading_delta={delta:.2f}°"
                )
            if _angle_between(eh, straight_heading) <= heading_tol:
                valid.append(cand)

            if delta <= heading_tolerance_deg:
                valid.append(cand)
            else:
                if DEBUG_CURVE_STRAIGHT:
                    print("    Reject: heading tolerance")

        if valid:
            best_solution = update_section_geometry(min(valid, key=score))
            break

    if best_solution is None:
        if DEBUG_CURVE_STRAIGHT:
            print("\nSOLVE FAILED: no valid candidates found")
        return None

    # ------------------------
    # Rebuild straight
    # ------------------------
    new_straight_start = best_solution.end
    L = straight.length

    new_straight_end = (
        new_straight_start[0] + hx * L,
        new_straight_start[1] + hy * L,
    )

    new_straight = replace(
        straight,
        start=new_straight_start,
        end=new_straight_end,
        polyline=[new_straight_start, new_straight_end],
    )

    return best_solution, new_straight
