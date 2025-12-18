from __future__ import annotations

import math
from dataclasses import replace
from typing import Optional, Tuple

from sg_viewer.models.sg_model import SectionPreview
from sg_viewer.geometry.curve_solver import _solve_curve_with_fixed_heading
from sg_viewer.geometry.sg_geometry import update_section_geometry

DEBUG_CURVE_STRAIGHT = True
DEBUG_CURVE_STRAIGHT_VERBOSE = False

def _deg_between(a, b):
    dot = max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1]))
    return math.degrees(math.acos(dot))

def _fmt(v):
    return f"({v[0]:.1f}, {v[1]:.1f})"

def _angle_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Return angle between two unit vectors in radians."""
    dot = max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1]))
    return math.acos(dot)

def _normalize(v):
    l = math.hypot(v[0], v[1])
    if l == 0:
        return (0.0, 0.0)
    return (v[0] / l, v[1] / l)


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
      - straight end is fixed
      - straight start slides along heading (length changes as needed)


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
    # Scan + refine along straight heading
    # ------------------------

    heading_tol = heading_tolerance_deg

    best_solution: Optional[SectionPreview] = None
    best_delta = float("inf")
    best_L: Optional[float] = None
    tries_total = 0
    tries_candidates = 0

    E = straight.end
    L0 = straight.length

    def try_L(L: float):
        nonlocal best_solution, best_delta, best_L, tries_total, tries_candidates
        tries_total += 1
        if L <= 1.0:
            return

        P = (
            E[0] - hx * L,
            E[1] - hy * L,
        )

        curve_template = replace(
            curve,
            start=curve_start,
            end=P,
            polyline=[curve_start, P],
        )

        for orient in (+1.0, -1.0):
            candidates = _solve_curve_with_fixed_heading(
                sect=curve_template,
                start=curve_start,
                end=P,
                fixed_point=curve_start,
                fixed_heading=curve_start_heading,
                fixed_point_is_start=True,
                orientation_hint=orient,
            )

            for cand in candidates:
                tries_candidates += 1
                if cand.end_heading is None:
                    continue

                eh = cand.end_heading
                eh_len = math.hypot(eh[0], eh[1])
                if eh_len <= 0:
                    continue
                eh = (eh[0] / eh_len, eh[1] / eh_len)

                delta = _deg_between(eh, straight_heading)

                if delta < best_delta:
                    best_delta = delta
                    best_solution = cand
                    best_L = L

                    if DEBUG_CURVE_STRAIGHT_VERBOSE:
                        print(
                            f"  NEW BEST: L={L:,.1f} "
                            f"orient={orient:+} "
                            f"Δ={delta:.4f}° "
                            f"radius={cand.radius:,.1f}"
                        )



    # ------------------------
    # Phase 1: coarse scan
    # ------------------------

    for i in range(1, 2000):   # 0.01 → 20x straight length
        L = L0 * (i * 0.01)
        try_L(L)

    if best_L is None:
        if DEBUG_CURVE_STRAIGHT:
            print("\nSOLVE FAILED: no candidates at all")
        return None


    # ------------------------
    # Phase 2: local refinement
    # ------------------------

    span = L0 * 0.05   # refine ±5% of straight length
    steps = 80

    for i in range(-steps, steps + 1):
        L = best_L + (i * span / steps)
        try_L(L)


    # ------------------------
    # Accept or reject
    # ------------------------

    if best_solution is None or best_delta > heading_tol:
        if DEBUG_CURVE_STRAIGHT:
            print(
                f"\nSOLVE FAILED: best Δ={best_delta:.3f}° "
                f"(tolerance {heading_tol:.3f}°)"
            )
        return None

    best_solution = update_section_geometry(best_solution)


    # ------------------------
    # Rebuild straight
    # ------------------------
    new_straight_start = best_solution.end
    new_straight_end = straight.end


    new_straight = replace(
        straight,
        start=new_straight_start,
        end=new_straight_end,
        polyline=[new_straight_start, new_straight_end],
    )

    if DEBUG_CURVE_STRAIGHT:
        print("\n=== CURVE → STRAIGHT SOLUTION ACCEPTED ===")

        # --- Straight changes ---
        old_start = straight.start
        new_start = best_solution.end

        h = straight_heading
        old_L = straight.length
        new_L = (
            (straight.end[0] - new_start[0]) * h[0]
            + (straight.end[1] - new_start[1]) * h[1]
        )

        print("Straight:")
        print(f"  start: {_fmt(old_start)} → {_fmt(new_start)}")
        print(f"  length: {old_L:,.1f} → {new_L:,.1f}  (Δ {new_L - old_L:,.1f})")

        # --- Curve changes ---
        print("Curve:")
        print(
            f"  radius: {curve.radius:,.1f} → {best_solution.radius:,.1f} "
            f"(Δ {best_solution.radius - curve.radius:,.1f})"
        )
        print(
            f"  arc len: {curve.length:,.1f} → {best_solution.length:,.1f} "
            f"(Δ {best_solution.length - curve.length:,.1f})"
        )

        # --- Join quality ---
        delta = _deg_between(
            _normalize(best_solution.end_heading),
            straight_heading,
        )

        print(f"Join quality:")
        print(f"  end heading delta: {delta:.2f}°")

    if DEBUG_CURVE_STRAIGHT:
        print("\n=== CURVE → STRAIGHT SOLVE SUMMARY ===")
        print(f"Total L samples tested: {tries_total:,}")
        print(f"Total curve candidates evaluated: {tries_candidates:,}")
        print(f"Best join Δ heading: {best_delta:.4f}°")
        print(f"Join L: {best_L:,.2f}")
        print(
            f"Curve radius: {curve.radius:,.1f} → {best_solution.radius:,.1f}"
        )
        print(
            f"Curve arc: {curve.length:,.1f} → {best_solution.length:,.1f}"
        )


    return best_solution, new_straight
