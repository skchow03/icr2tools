from __future__ import annotations

import math
from dataclasses import replace
from typing import Optional, Tuple

from icr2_core.trk.sg_classes import FP_SCALE, SGFile
from sg_viewer.models.sg_model import SectionPreview
from sg_viewer.geometry.curve_solver import _solve_curve_with_fixed_heading
from sg_viewer.geometry.sg_geometry import update_section_geometry
from sg_viewer.geometry.sg_geometry import signed_radius_from_heading

DEBUG_CURVE_STRAIGHT = True
DEBUG_CURVE_STRAIGHT_VERBOSE = False

def _signed_angle_deg(a: tuple[float, float], b: tuple[float, float]) -> float:
    """
    Signed angle from a → b in degrees.
    Positive = CCW, negative = CW.
    """
    dot = max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1]))
    cross = a[0] * b[1] - a[1] * b[0]
    return math.degrees(math.atan2(cross, dot))

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
    heading_tolerance_deg: float = 1e-4,
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
    best_abs_delta = float("inf")   # absolute degrees
    best_signed_delta = 0.0         # signed degrees (for debugging)
    best_L: Optional[float] = None

    tries_total = 0
    tries_candidates = 0

    E = straight.end
    L0 = straight.length

    def try_L(L: float):
        nonlocal best_solution, best_abs_delta, best_signed_delta, best_L, tries_total, tries_candidates


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

                delta = _signed_angle_deg(eh, straight_heading)

                abs_delta = abs(delta)
                if abs_delta < best_abs_delta:
                    best_abs_delta = abs_delta
                    best_signed_delta = delta
                    best_solution = cand
                    best_L = L


                    if DEBUG_CURVE_STRAIGHT_VERBOSE:
                        print(
                            f"  NEW BEST: L={L:,.1f} "
                            f"orient={orient:+} "
                            f"Δ={delta:.4f}° "
                            f"radius={cand.radius:,.1f}"
                        )

    def delta_for_L(L: float) -> Optional[float]:
        if L <= 1.0:
            return None

        P = (E[0] - hx * L, E[1] - hy * L)

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
                if cand.end_heading is None:
                    continue

                eh = cand.end_heading
                l = math.hypot(eh[0], eh[1])
                if l <= 0:
                    continue

                eh = (eh[0] / l, eh[1] / l)
                return _signed_angle_deg(eh, straight_heading)

        return None


    # ------------------------
    # Phase 1: coarse scan
    # ------------------------
    bracket = None
    prev_L = None
    prev_delta = None

    for i in range(1, 2000):   # 0.01 → 20x straight length
        L = L0 * (i * 0.01)
        try_L(L)
        d = delta_for_L(L)
        if d is not None and prev_delta is not None:
            if d * prev_delta < 0:
                bracket = (prev_L, L)
                break
        prev_L = L
        prev_delta = d

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

    if bracket is not None:
        lo, hi = bracket
        dlo = delta_for_L(lo)

        for _ in range(40):  # 40 iters = extreme precision
            mid = 0.5 * (lo + hi)
            dmid = delta_for_L(mid)

            if dmid is None:
                break

            if abs(dmid) < 1e-4:
                best_L = mid
                break

            if dmid * dlo < 0:
                hi = mid
            else:
                lo = mid
                dlo = dmid

        best_L = 0.5 * (lo + hi)
        try_L(best_L)

    # ------------------------
    # Final Newton-style micro refinement
    # ------------------------
    if best_L is not None:
        eps = max(1.0, best_L * 1e-6)

        d0 = delta_for_L(best_L)
        d1 = delta_for_L(best_L + eps)

        if d0 is not None and d1 is not None:
            deriv = (d1 - d0) / eps
            if abs(deriv) > 1e-9:
                L_new = best_L - d0 / deriv
                try_L(L_new)

    # ------------------------
    # Accept or reject
    # ------------------------

    if best_solution is None or best_abs_delta > heading_tol:

        if DEBUG_CURVE_STRAIGHT:
            print(
                f"\nSOLVE FAILED: best Δ={best_delta:.3f}° "
                f"(tolerance {heading_tol:.3f}°)"
            )
        return None

    best_solution = update_section_geometry(best_solution)

    # after you decide best_solution is the curve you will use:
    signed_r = signed_radius_from_heading(
        curve_start_heading,      # (hx, hy) at curve start
        curve_start,              # curve start point
        best_solution.center,     # solved center
        best_solution.radius,     # solved (unsigned) radius
    )
    if signed_r != best_solution.radius:
        best_solution = replace(best_solution, radius=signed_r)

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
        print(f"Best join Δ heading: {best_signed_delta:.6f}° (abs {best_abs_delta:.6f}°)")

        print(f"Join L: {best_L:,.2f}")
        print(
            f"Curve radius: {curve.radius:,.1f} → {best_solution.radius:,.1f}"
        )
        print(
            f"Curve arc: {curve.length:,.1f} → {best_solution.length:,.1f}"
        )


    return best_solution, new_straight


def connect_straight_to_curve(
    straight: SGFile.Section,
    curve: SGFile.Section,
    radius: float,
    sweep: float,
    turn: int,  # +1 = left, -1 = right
) -> None:

    px = straight.end_x
    py = straight.end_y

    theta = straight.heading_angle()

    tx = math.cos(theta)
    ty = math.sin(theta)

    nx = -ty
    ny = tx

    cx = px + turn * radius * nx
    cy = py + turn * radius * ny

    # Curve start
    curve.start_x = int(px)
    curve.start_y = int(py)
    curve.center_x = int(cx)
    curve.center_y = int(cy)
    curve.radius = int(radius)

    # Start vector
    vx = px - cx
    vy = py - cy

    ang0 = math.atan2(vy, vx)
    ang1 = ang0 + sweep * turn

    # Compute curve end
    ex = cx + radius * math.cos(ang1)
    ey = cy + radius * math.sin(ang1)

    curve.end_x = int(ex)
    curve.end_y = int(ey)

    # Set SG heading fields
    curve.sang1 = int(math.cos(theta) * FP_SCALE)
    curve.sang2 = int(math.sin(theta) * FP_SCALE)

    end_heading = theta + sweep * turn
    curve.eang1 = int(math.cos(end_heading) * FP_SCALE)
    curve.eang2 = int(math.sin(end_heading) * FP_SCALE)

    # Finalize
    curve.type = 2
    curve.recompute_curve_length()
