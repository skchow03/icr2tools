from __future__ import annotations

import logging
import math
from dataclasses import replace
from typing import Optional, Tuple

from sg_viewer.models.sg_model import SectionPreview
from sg_viewer.geometry.curve_solver import _solve_curve_with_fixed_heading
from sg_viewer.geometry.sg_geometry import update_section_geometry
from sg_viewer.geometry.sg_geometry import signed_radius_from_heading
from sg_viewer.geometry.connect_straight_to_curve import solve_straight_to_curve_free_end

DEBUG_CURVE_STRAIGHT = False
DEBUG_CURVE_STRAIGHT_VERBOSE = False

logger = logging.getLogger(__name__)


def _reverse_section_endpoints(section: SectionPreview) -> SectionPreview:
    """
    Return a copy of ``section`` with its start/end swapped for solving.

    Connectivity is preserved; callers remain responsible for updating
    previous/next IDs to reflect any new attachment.
    """

    reversed_polyline = list(reversed(section.polyline)) if section.polyline else []

    reversed_section = replace(
        section,
        start=section.end,
        end=section.start,
        start_heading=section.end_heading,
        end_heading=section.start_heading,
        sang1=section.eang1,
        sang2=section.eang2,
        eang1=section.sang1,
        eang2=section.sang2,
        polyline=reversed_polyline,
    )

    if section.type_name == "curve" and section.radius is not None:
        reversed_section = replace(reversed_section, radius=-section.radius)

    return reversed_section


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

    if DEBUG_CURVE_STRAIGHT and logger.isEnabledFor(logging.DEBUG):
        logger.debug("\n=== CURVE → STRAIGHT SOLVE ATTEMPT ===")
        logger.debug("Curve start: %s", curve.start)
        logger.debug("Curve end (original): %s", curve.end)
        logger.debug("Curve start heading: %s", curve.start_heading)
        logger.debug("Curve radius: %s", curve.radius)
        logger.debug("Straight start: %s", straight.start)
        logger.debug("Straight end: %s", straight.end)
        logger.debug("Straight length: %s", straight.length)
        logger.debug("Straight forward heading: %s", straight_heading)
        sh = straight_heading
        straight_angle = math.degrees(math.atan2(sh[1], sh[0]))
        logger.debug("Straight heading angle: %.2f°", straight_angle)
        ch = curve.start_heading
        curve_angle = math.degrees(math.atan2(ch[1], ch[0]))
        logger.debug("Curve start heading angle: %.2f°", curve_angle)


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
    orientation_hint = 1.0
    if curve.radius is not None and curve.radius != 0:
        orientation_hint = 1.0 if curve.radius > 0 else -1.0
    elif curve.center is not None:
        center_vec = (
            curve.center[0] - curve_start[0],
            curve.center[1] - curve_start[1],
        )
        cross = (
            curve_start_heading[0] * center_vec[1]
            - curve_start_heading[1] * center_vec[0]
        )
        if cross != 0:
            orientation_hint = 1.0 if cross > 0 else -1.0
    fallback_orientation_hint = -orientation_hint
    solve_cache: dict[float, Optional[tuple[SectionPreview, float]]] = {}

    def solve_candidates(curve_template: SectionPreview, end_point: tuple[float, float]):
        candidates = _solve_curve_with_fixed_heading(
            sect=curve_template,
            start=curve_start,
            end=end_point,
            fixed_point=curve_start,
            fixed_heading=curve_start_heading,
            fixed_point_is_start=True,
            orientation_hint=orientation_hint,
        )
        if not candidates and fallback_orientation_hint is not None:
            candidates = _solve_curve_with_fixed_heading(
                sect=curve_template,
                start=curve_start,
                end=end_point,
                fixed_point=curve_start,
                fixed_heading=curve_start_heading,
                fixed_point_is_start=True,
                orientation_hint=fallback_orientation_hint,
            )
        return candidates

    def solve_for_L(L: float) -> Optional[tuple[SectionPreview, float]]:
        nonlocal tries_candidates

        cached = solve_cache.get(L)
        if cached is not None or L in solve_cache:
            return cached

        if L <= 1.0:
            solve_cache[L] = None
            return None

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

        candidates = solve_candidates(curve_template, P)
        best_candidate = None
        best_delta = None
        best_abs = float("inf")

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
            if abs_delta < best_abs:
                best_abs = abs_delta
                best_candidate = cand
                best_delta = delta

        if best_candidate is None or best_delta is None:
            solve_cache[L] = None
            return None

        solve_cache[L] = (best_candidate, best_delta)
        return solve_cache[L]

    def try_L(L: float) -> Optional[tuple[SectionPreview, float]]:
        nonlocal best_solution, best_abs_delta, best_signed_delta, best_L, tries_total, tries_candidates


        tries_total += 1
        result = solve_for_L(L)
        if result is None:
            return None

        cand, delta = result
        abs_delta = abs(delta)
        if abs_delta < best_abs_delta:
            best_abs_delta = abs_delta
            best_signed_delta = delta
            best_solution = cand
            best_L = L

            if (
                DEBUG_CURVE_STRAIGHT_VERBOSE
                and logger.isEnabledFor(logging.DEBUG)
            ):
                logger.debug(
                    "  NEW BEST: L=%s orient=%+0.1f Δ=%.4f° radius=%s",
                    f"{L:,.1f}",
                    orientation_hint,
                    delta,
                    f"{cand.radius:,.1f}",
                )

        return result

    def delta_for_L(L: float) -> Optional[float]:
        result = solve_for_L(L)
        if result is None:
            return None
        return result[1]


    # ------------------------
    # Phase 1: adaptive scan
    # ------------------------
    bracket = None
    scan_min_mult = 0.01
    scan_max_mult = 20.0
    max_range_mult = 80.0
    samples = 150
    passes = 0

    while bracket is None and passes < 5:
        prev_L = None
        prev_delta = None
        step = (scan_max_mult - scan_min_mult) / samples

        for i in range(samples + 1):
            L = L0 * (scan_min_mult + step * i)
            if L <= 0:
                continue
            try_L(L)
            d = delta_for_L(L)
            if d is not None and prev_delta is not None:
                if d * prev_delta < 0:
                    bracket = (prev_L, L)
                    break
            prev_L = L
            prev_delta = d

        if bracket is not None:
            break

        if scan_max_mult < max_range_mult:
            scan_max_mult = min(max_range_mult, scan_max_mult * 2.0)
        else:
            samples *= 2
        passes += 1

    if best_L is None:
        if DEBUG_CURVE_STRAIGHT and logger.isEnabledFor(logging.DEBUG):
            logger.debug("\nSOLVE FAILED: no candidates at all")
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
        if DEBUG_CURVE_STRAIGHT and logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "\nSOLVE FAILED: best Δ=%.3f° (tolerance %.3f°)",
                best_signed_delta,
                heading_tol,
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

    new_straight_length = math.hypot(
        new_straight_end[0] - new_straight_start[0],
        new_straight_end[1] - new_straight_start[1],
    )

    new_straight = replace(
        straight,
        start=new_straight_start,
        end=new_straight_end,
        length=new_straight_length,
        polyline=[new_straight_start, new_straight_end],
    )

    if DEBUG_CURVE_STRAIGHT and logger.isEnabledFor(logging.DEBUG):
        logger.debug("\n=== CURVE → STRAIGHT SOLUTION ACCEPTED ===")

        # --- Straight changes ---
        old_start = straight.start
        new_start = best_solution.end

        h = straight_heading
        old_L = straight.length
        new_L = (
            (straight.end[0] - new_start[0]) * h[0]
            + (straight.end[1] - new_start[1]) * h[1]
        )

        logger.debug("Straight:")
        logger.debug("  start: %s → %s", _fmt(old_start), _fmt(new_start))
        logger.debug(
            "  length: %s → %s  (Δ %s)",
            f"{old_L:,.1f}",
            f"{new_L:,.1f}",
            f"{new_L - old_L:,.1f}",
        )

        # --- Curve changes ---
        logger.debug("Curve:")
        logger.debug(
            "  radius: %s → %s (Δ %s)",
            f"{curve.radius:,.1f}",
            f"{best_solution.radius:,.1f}",
            f"{best_solution.radius - curve.radius:,.1f}",
        )
        logger.debug(
            "  arc len: %s → %s (Δ %s)",
            f"{curve.length:,.1f}",
            f"{best_solution.length:,.1f}",
            f"{best_solution.length - curve.length:,.1f}",
        )

        # --- Join quality ---
        delta = _deg_between(
            _normalize(best_solution.end_heading),
            straight_heading,
        )

        logger.debug("Join quality:")
        logger.debug("  end heading delta: %.2f°", delta)

        logger.debug("\n=== CURVE → STRAIGHT SOLVE SUMMARY ===")
        logger.debug("Total L samples tested: %s", f"{tries_total:,}")
        logger.debug("Total curve candidates evaluated: %s", f"{tries_candidates:,}")
        logger.debug(
            "Best join Δ heading: %.6f° (abs %.6f°)",
            best_signed_delta,
            best_abs_delta,
        )

        logger.debug("Join L: %s", f"{best_L:,.2f}")
        logger.debug(
            "Curve radius: %s → %s",
            f"{curve.radius:,.1f}",
            f"{best_solution.radius:,.1f}",
        )
        logger.debug(
            "Curve arc: %s → %s",
            f"{curve.length:,.1f}",
            f"{best_solution.length:,.1f}",
        )


    new_straight = update_section_geometry(new_straight)

    return best_solution, new_straight


def solve_straight_end_to_curve_endpoint(
    straight: SectionPreview,
    straight_end: str,
    curve: SectionPreview,
    curve_end: str,
    *,
    min_straight_length: float = 1.0,
) -> Optional[Tuple[SectionPreview, SectionPreview]]:
    """
    Connect a straight's ``straight_end`` to a curve's ``curve_end``.

    Special cases:
      - straight_end == "end" and curve_end == "start":
        * preserve straight start position + heading
        * preserve curve end position + heading
        * slide straight end along its heading and refit curve radius/start
          heading to meet tangentially
      - all other combinations preserve curve geometry and slide the straight
        endpoint along the curve tangent (maintaining straight length)

    Returns (new_straight, new_curve) or None on failure.
    """

    if curve.type_name != "curve":
        return None
    if straight.type_name != "straight":
        return None
    if curve_end not in {"start", "end"}:
        return None
    if straight_end not in {"start", "end"}:
        return None

    if straight_end == "end" and curve_end == "start":
        solved = solve_straight_to_curve_free_end(straight, curve)
        if solved is None:
            return None
        solved_straight, solved_curve = solved
    else:
        if curve_end == "start":
            target_point = curve.start
            heading = curve.start_heading
        else:
            target_point = curve.end
            heading = curve.end_heading

        if heading is None:
            return None

        hx, hy = heading
        mag = math.hypot(hx, hy)
        if mag <= 0:
            return None
        hx /= mag
        hy /= mag

        L = straight.length
        if L <= 0:
            return None

        if straight_end == "end":
            new_start = (target_point[0] - hx * L, target_point[1] - hy * L)
            new_end = target_point
        else:
            new_start = target_point
            new_end = (target_point[0] + hx * L, target_point[1] + hy * L)

        solved_straight = replace(
            straight,
            start=new_start,
            end=new_end,
        )
        solved_curve = curve

    solved_curve = update_section_geometry(solved_curve)
    solved_straight = update_section_geometry(solved_straight)

    if solved_straight.length < min_straight_length:
        return None

    return solved_straight, solved_curve
