import math
from dataclasses import replace
from typing import Optional, Tuple

from sg_viewer.geometry.sg_geometry import signed_radius_from_heading, update_section_geometry
from sg_viewer.models.sg_model import SectionPreview


DEBUG_STRAIGHT_CURVE = True
DEBUG_STRAIGHT_CURVE_VERBOSE = False


def solve_straight_to_curve_free_end(
    straight: SectionPreview,
    curve: SectionPreview,
) -> Optional[Tuple[SectionPreview, SectionPreview]]:
    """
    Connect a straight to the *start* of a curve while:
      - preserving the straight's start position + heading
      - preserving the curve's end position + heading
      - adjusting only the straight's end position and the curve's start
        heading/radius
    """

    if straight.type_name != "straight":
        return None
    if curve.type_name != "curve":
        return None

    # Required headings
    straight_heading = straight.start_heading
    if straight_heading is None:
        straight_heading = (
            straight.end[0] - straight.start[0],
            straight.end[1] - straight.start[1],
        )

    hx, hy = straight_heading
    h_mag = math.hypot(hx, hy)
    if h_mag <= 0:
        return None
    hx /= h_mag
    hy /= h_mag
    straight_heading = (hx, hy)

    curve_end_heading = curve.end_heading
    if curve_end_heading is None:
        return None
    ex, ey = curve_end_heading
    eh_mag = math.hypot(ex, ey)
    if eh_mag <= 0:
        return None
    ex /= eh_mag
    ey /= eh_mag
    curve_end_heading = (ex, ey)

    straight_start = straight.start
    curve_end = curve.end

    if DEBUG_STRAIGHT_CURVE:
        print("\n=== STRAIGHT → CURVE SOLVE ATTEMPT ===")
        print("Straight start:", straight.start)
        print("Straight end (original):", straight.end)
        print("Straight heading:", straight_heading)
        print("Straight length:", straight.length)
        print("Curve start (original):", curve.start)
        print("Curve end:", curve.end)
        print("Curve end heading:", curve.end_heading)
        print("Curve radius:", curve.radius)

    # Orientation hint taken from existing curve radius if available
    orientation_hints = [1.0, -1.0]
    if curve.radius is not None and curve.radius < 0:
        orientation_hints = [-1.0, 1.0]

    def _solve_for_length(
        length: float, orientation: float
    ) -> tuple[Optional[SectionPreview], Optional[float]]:
        """
        Attempt to build a curve solution for a given straight length.
        Returns (candidate_curve, radius_delta) where radius_delta is the
        difference between start/end radii (should trend to zero for a valid
        circle).
        """

        if length <= 0:
            return None, None

        # Place the straight end along its heading
        sx, sy = straight_start
        start_point = (sx + hx * length, sy + hy * length)

        # Normals pointing toward the prospective centre
        ns = (-orientation * hy, orientation * hx)
        ne = (-orientation * ey, orientation * ex)

        dx = curve_end[0] - start_point[0]
        dy = curve_end[1] - start_point[1]

        # Solve for intersection of the two normals: start_point + ns * ts = curve_end + ne * te
        det = ns[0] * (-ne[1]) - ns[1] * (-ne[0])
        if abs(det) <= 1e-9:
            return None, None

        ts = (dx * (-ne[1]) - dy * (-ne[0])) / det
        te = (ns[0] * dy - ns[1] * dx) / det

        # Enforce a consistent orientation (centre should be to the chosen side)
        if ts <= 0 or te <= 0:
            return None, None

        radius_start = ts
        radius_end = te
        radius_delta = radius_start - radius_end

        center = (
            start_point[0] + ns[0] * ts,
            start_point[1] + ns[1] * ts,
        )

        # Validate orientation via the arc direction
        vs = (start_point[0] - center[0], start_point[1] - center[1])
        ve = (curve_end[0] - center[0], curve_end[1] - center[1])

        rs = math.hypot(vs[0], vs[1])
        re = math.hypot(ve[0], ve[1])
        if rs <= 0 or re <= 0:
            return None, None

        vs_unit = (vs[0] / rs, vs[1] / rs)
        ve_unit = (ve[0] / re, ve[1] / re)
        cross = vs_unit[0] * ve_unit[1] - vs_unit[1] * ve_unit[0]
        if cross == 0 or (cross > 0) != (orientation > 0):
            return None, None

        dot = max(-1.0, min(1.0, vs_unit[0] * ve_unit[0] + vs_unit[1] * ve_unit[1]))
        angle = math.acos(dot)
        arc_radius = 0.5 * (rs + re)
        arc_length = arc_radius * angle
        if arc_length <= 0:
            return None, None

        signed_radius = signed_radius_from_heading(straight_heading, start_point, center, arc_radius)

        candidate_curve = replace(
            curve,
            start=start_point,
            start_heading=straight_heading,
            end=curve_end,
            end_heading=curve_end_heading,
            center=center,
            radius=signed_radius,
            sang1=straight_heading[0],
            sang2=straight_heading[1],
            eang1=curve_end_heading[0],
            eang2=curve_end_heading[1],
            length=arc_length,
        )

        return candidate_curve, radius_delta

    best_curve: Optional[SectionPreview] = None
    best_abs_delta = float("inf")
    best_length: Optional[float] = None

    tries_total = 0
    tries_candidates = 0

    def evaluate_length(L: float, orientation: float):
        nonlocal tries_total, tries_candidates
        tries_total += 1
        candidate_curve, delta = _solve_for_length(L, orientation)
        if candidate_curve is not None:
            tries_candidates += 1
        return candidate_curve, delta

    base_length = max(straight.length, 1.0)
    min_length = max(base_length * 0.1, 0.5)
    max_length = base_length * 20.0

    for orientation in orientation_hints:
        prev_delta = None
        prev_length = None

        # Coarse scan
        for i in range(1, 201):
            L = min_length + (max_length - min_length) * (i / 200)
            candidate_curve, delta = evaluate_length(L, orientation)
            if delta is None:
                continue

            abs_delta = abs(delta)
            if candidate_curve is not None and abs_delta < best_abs_delta:
                best_abs_delta = abs_delta
                best_curve = candidate_curve
                best_length = L

            if prev_delta is not None and delta * prev_delta < 0:
                # Refine between prev_length and L
                lo, hi = prev_length, L
                for _ in range(50):
                    mid = 0.5 * (lo + hi)
                    candidate_curve, delta_mid = evaluate_length(mid, orientation)
                    if delta_mid is None:
                        break

                    if candidate_curve is not None and abs(delta_mid) < best_abs_delta:
                        best_abs_delta = abs(delta_mid)
                        best_curve = candidate_curve
                        best_length = mid

                    if delta_mid * prev_delta < 0:
                        hi = mid
                    else:
                        lo = mid
                        prev_delta = delta_mid
                break

            prev_delta = delta
            prev_length = L

    if best_curve is None or best_length is None:
        if DEBUG_STRAIGHT_CURVE:
            print("\nSOLVE FAILED: no candidates at all")
        return None

    radius_tolerance = max(1e-3, abs(best_curve.radius) * 1e-3 if best_curve.radius is not None else 0.0)
    if best_abs_delta > radius_tolerance:
        if DEBUG_STRAIGHT_CURVE:
            print(
                f"\nSOLVE FAILED: best Δ radius={best_abs_delta:.6f} "
                f"(tolerance {radius_tolerance:.6f})"
            )
        return None

    new_straight_end = best_curve.start
    new_straight = replace(
        straight,
        end=new_straight_end,
        length=best_length,
        polyline=[straight_start, new_straight_end],
    )

    best_curve = update_section_geometry(best_curve)
    new_straight = update_section_geometry(new_straight)

    if DEBUG_STRAIGHT_CURVE:
        print("\n=== STRAIGHT → CURVE SOLUTION ACCEPTED ===")

        # --- Straight changes ---
        old_end = straight.end
        new_end = new_straight.end

        h = straight_heading
        old_L = straight.length
        new_L = new_straight.length

        print("Straight:")
        print(f"  end: {old_end} → {new_end}")
        print(f"  length: {old_L:,.1f} → {new_L:,.1f}  (Δ {new_L - old_L:,.1f})")

        # --- Curve changes ---
        print("Curve:")
        print(
            f"  radius: {curve.radius:,.1f} → {best_curve.radius:,.1f} "
            f"(Δ {best_curve.radius - (curve.radius or 0.0):,.1f})"
        )
        print(
            f"  arc len: {curve.length:,.1f} → {best_curve.length:,.1f} "
            f"(Δ {best_curve.length - curve.length:,.1f})"
        )

        print("\n=== STRAIGHT → CURVE SOLVE SUMMARY ===")
        print(f"Total length samples tested: {tries_total:,}")
        print(f"Total curve candidates evaluated: {tries_candidates:,}")
        print(f"Best Δ radius: {best_abs_delta:.6f}")
        print(f"Solved straight length: {best_length:,.2f}")
        print(
            f"Curve radius: {curve.radius:,.1f} → {best_curve.radius:,.1f}"
        )
        print(
            f"Curve arc: {curve.length:,.1f} → {best_curve.length:,.1f}"
        )

    return new_straight, best_curve
