"""World-space arc-casting racing-line constructor.

Pathfinder deliberately does not optimize DLAT directly. It casts true
straight/circular paths in XY space, projects them back onto the local
centerline only for track progress and boundary checks, and replans after
every LP record.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import numpy as np


@dataclass
class State:
    x: float
    y: float
    heading: float
    curvature: float
    seg_abs: int
    dlong: float
    dlat: float


@dataclass
class Projection:
    seg_abs: int
    dlong: float
    dlat: float
    legal: bool


def _arc_point(state: State, curvature: float, distance: float) -> tuple[float, float, float]:
    """Return the exact XY/heading reached along a constant-curvature arc."""
    h0 = state.heading
    if abs(curvature) < 1.0e-12:
        x = state.x + distance * math.cos(h0)
        y = state.y + distance * math.sin(h0)
        return x, y, h0
    h1 = h0 + curvature * distance
    x = state.x + (math.sin(h1) - math.sin(h0)) / curvature
    y = state.y - (math.cos(h1) - math.cos(h0)) / curvature
    return x, y, h1


def _project_local(
    x: float,
    y: float,
    last_seg_abs: int,
    center: np.ndarray,
    dlongs: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    track_length: float,
    dlat_sign: float,
) -> Projection | None:
    """Project onto nearby centerline segments without allowing switchback jumps."""
    n = len(center)
    best = None
    best_dist2 = float("inf")

    # Arc samples are close together. Restricting projection to the local
    # sequence of track segments prevents a nearby switchback from being
    # mistaken for a huge leap forward.
    for seg_abs in range(last_seg_abs - 2, last_seg_abs + 9):
        j = seg_abs % n
        lap = seg_abs // n
        p0 = center[j]
        p1 = center[(j + 1) % n]
        vx = float(p1[0] - p0[0])
        vy = float(p1[1] - p0[1])
        vv = vx * vx + vy * vy
        if vv <= 1.0e-12:
            continue
        t = ((x - float(p0[0])) * vx + (y - float(p0[1])) * vy) / vv
        t = max(0.0, min(1.0, t))
        px = float(p0[0]) + vx * t
        py = float(p0[1]) + vy * t
        dx = x - px
        dy = y - py
        dist2 = dx * dx + dy * dy
        if dist2 >= best_dist2:
            continue

        seg_len = math.sqrt(vv)
        # Signed left-of-centerline offset, converted to ICR2's DLAT sign.
        left_offset = (vx * dy - vy * dx) / seg_len
        dlat = dlat_sign * left_offset

        d0 = float(dlongs[j]) + lap * track_length
        if j == n - 1:
            d1 = (lap + 1) * track_length
        else:
            d1 = float(dlongs[j + 1]) + lap * track_length
        projected_dlong = d0 + (d1 - d0) * t

        next_j = (j + 1) % n
        low = float(lower[j]) + (float(lower[next_j]) - float(lower[j])) * t
        high = float(upper[j]) + (float(upper[next_j]) - float(upper[j])) * t
        legal = low - 0.02 <= dlat <= high + 0.02

        best_dist2 = dist2
        best = Projection(seg_abs, projected_dlong, dlat, legal)

    return best


def _advance_checked(
    state: State,
    curvature: float,
    distance: float,
    center: np.ndarray,
    dlongs: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    track_length: float,
    dlat_sign: float,
    *,
    sample_feet: float = 12.0,
) -> State | None:
    """Advance a true XY arc while checking the legal corridor along it."""
    samples = max(1, int(math.ceil(distance / sample_feet)))
    seg_abs = state.seg_abs
    prev_dlong = state.dlong
    final_proj = None
    final_x = state.x
    final_y = state.y
    final_h = state.heading

    for sample in range(1, samples + 1):
        travelled = distance * sample / samples
        x, y, heading = _arc_point(state, curvature, travelled)
        proj = _project_local(
            x, y, seg_abs, center, dlongs, lower, upper,
            track_length, dlat_sign,
        )
        if proj is None or not proj.legal:
            return None

        # A real 12 ft arc sample cannot legitimately jump hundreds of feet
        # around the track or run materially backward. Reject such projections.
        delta = proj.dlong - prev_dlong
        if delta < -3.0 or delta > max(45.0, sample_feet * 3.5):
            return None

        seg_abs = proj.seg_abs
        prev_dlong = proj.dlong
        final_proj = proj
        final_x, final_y, final_h = x, y, heading

    if final_proj is None:
        return None
    return State(
        final_x, final_y, final_h, float(curvature),
        final_proj.seg_abs, final_proj.dlong, final_proj.dlat,
    )


def _cast_clearance(
    state: State,
    curvature: float,
    max_distance: float,
    center: np.ndarray,
    dlongs: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    track_length: float,
    dlat_sign: float,
    *,
    sample_feet: float = 24.0,
) -> tuple[float, State]:
    """Cast one constant-radius arc until it becomes illegal or reaches horizon."""
    travelled = 0.0
    current = state
    while travelled < max_distance - 1.0e-9:
        step = min(sample_feet, max_distance - travelled)
        nxt = _advance_checked(
            current, curvature, step, center, dlongs, lower, upper,
            track_length, dlat_sign, sample_feet=step,
        )
        if nxt is None:
            break
        current = nxt
        travelled += step
    return travelled, current


def _advance_to_target_dlong(
    state: State,
    curvature: float,
    target_dlong: float,
    center: np.ndarray,
    dlongs: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    track_length: float,
    dlat_sign: float,
) -> State | None:
    """Commit one arc continuously to the requested LP station.

    The earlier implementation returned the nearest coarse 2 ft sample. More
    importantly, if that sample could not be reached it snapped the state to
    the centerline. Those resets showed up as the large triangular jumps in
    the generated LP. This version requires a legal bracket around the target
    DLONG and refines the crossing by bisection so the committed state really
    belongs to this LP station.
    """
    if target_dlong <= state.dlong + 1.0e-6:
        return state

    remaining = target_dlong - state.dlong
    max_travel = max(30.0, remaining * 2.75 + 12.0)
    previous = state
    travelled = 0.0

    while travelled < max_travel - 1.0e-9:
        step = min(2.0, max_travel - travelled)
        nxt = _advance_checked(
            previous, curvature, step, center, dlongs, lower, upper,
            track_length, dlat_sign, sample_feet=step,
        )
        if nxt is None:
            return None

        if nxt.dlong >= target_dlong:
            # Refine the arc distance from previous -> nxt until its projected
            # DLONG is essentially the requested LP station.
            lo_dist = 0.0
            hi_dist = step
            best = nxt
            best_error = abs(nxt.dlong - target_dlong)
            for _ in range(12):
                mid_dist = 0.5 * (lo_dist + hi_dist)
                mid = _advance_checked(
                    previous, curvature, mid_dist,
                    center, dlongs, lower, upper,
                    track_length, dlat_sign,
                    sample_feet=max(mid_dist, 0.05),
                )
                if mid is None:
                    hi_dist = mid_dist
                    continue
                error = abs(mid.dlong - target_dlong)
                if error < best_error:
                    best = mid
                    best_error = error
                if mid.dlong < target_dlong:
                    lo_dist = mid_dist
                else:
                    hi_dist = mid_dist
            return best

        previous = nxt
        travelled += step

    return None


def _fallback_station_state(
    state: State,
    target_index: int,
    target_dlong: float,
    center: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    dlat_sign: float,
) -> State:
    """Advance to the next station without a lateral teleport.

    This is only a last-resort recovery if no tested arc can reach the next LP
    station. It preserves the previous lateral offset as much as the legal
    corridor permits instead of snapping to DLAT=0.
    """
    n = len(center)
    j = target_index % n
    prev_j = (j - 1) % n
    next_j = (j + 1) % n

    # Preserve the existing offset; only clip if the corridor itself narrows.
    dlat = float(np.clip(state.dlat, lower[j], upper[j]))

    # Use a centered tangent for a stable local normal at this LP station.
    tx = float(center[next_j, 0] - center[prev_j, 0])
    ty = float(center[next_j, 1] - center[prev_j, 1])
    tlen = max(math.hypot(tx, ty), 1.0e-9)
    tx /= tlen
    ty /= tlen
    nx = -ty * dlat_sign
    ny = tx * dlat_sign
    x = float(center[j, 0]) + nx * dlat
    y = float(center[j, 1]) + ny * dlat

    return State(
        x, y, state.heading, state.curvature, j,
        float(target_dlong), dlat,
    )

def generate_pathfinder(
    dlongs,
    lower,
    upper,
    seed,
    center_xy,
    start_xy,
    track_length_feet,
    dlat_sign,
    *,
    progress_callback=None,
    beam_width=16,
    horizon_feet=1000.0,
    branch_feet=120.0,
):
    """Build a line by receding-horizon world-space arc casting.

    At each LP interval Pathfinder:
      1. casts many true circular arcs far forward in XY;
      2. retains the best first arcs as a beam;
      3. from a point 120 ft down each surviving first arc, casts all possible
         continuation arcs;
      4. selects the first arc whose two-stage future reaches furthest around
         the actual track;
      5. commits only to the next LP interval and replans.

    Physics is not used to choose the path.
    """
    n = len(seed)
    if n < 8:
        return list(seed), 0, 0, 0, 0

    center = np.asarray(center_xy, dtype=float)
    dl = np.asarray(dlongs, dtype=float) / 6000.0
    lo = np.asarray(lower, dtype=float) / 6000.0
    hi = np.asarray(upper, dtype=float) / 6000.0
    track_length = float(track_length_feet)

    # True world-space curvatures (1/ft), represented here by useful radii.
    # The very large radii are important: they allow early, extremely shallow
    # setup arcs that would look almost straight over a short distance.
    radii = (3200.0, 1800.0, 1100.0, 750.0, 520.0, 360.0,
             250.0, 175.0, 120.0, 85.0, 60.0, 42.0)
    positive = [1.0 / r for r in radii]
    curvatures = np.asarray([-k for k in reversed(positive)] + [0.0] + positive)

    # Start independently of the existing racing-line shape: use centerline
    # when legal, otherwise the nearest legal point. The seed is only used by
    # the caller to establish the legal corridor.
    start_dlat = float(np.clip(0.0, lo[0], hi[0]))
    cx0, cy0 = float(center[0, 0]), float(center[0, 1])
    cx1, cy1 = float(center[1, 0]), float(center[1, 1])
    cxm, cym = float(center[-1, 0]), float(center[-1, 1])
    tx = cx1 - cxm
    ty = cy1 - cym
    tangent_len = max(math.hypot(tx, ty), 1.0e-9)
    tx /= tangent_len
    ty /= tangent_len
    # left normal times DLAT orientation
    nx = -ty * dlat_sign
    ny = tx * dlat_sign
    sx = cx0 + nx * start_dlat
    sy = cy0 + ny * start_dlat
    if start_xy is not None and abs(start_dlat) > 1.0e-9:
        sx, sy = start_xy

    current = State(
        float(sx), float(sy), math.atan2(ty, tx), 0.0,
        0, float(dl[0]), start_dlat,
    )
    result = [start_dlat]
    tested = 0

    continuity_recoveries = 0
    commit_retries = 0

    for i in range(1, n):
        target_dlong = float(dl[i])
        direct = []
        for k in curvatures:
            travelled, end_state = _cast_clearance(
                current, float(k), horizon_feet,
                center, dl, lo, hi, track_length, dlat_sign,
            )
            tested += 1
            direct.append((
                end_state.dlong, travelled,
                abs(k - current.curvature), float(k), end_state,
            ))

        # Keep a broad set of genuinely different first arcs. Direct reach is
        # the primary criterion; steering change is only a tie breaker.
        direct.sort(key=lambda item: (-item[0], -item[1], item[2]))
        first_beam = direct[:min(beam_width, len(direct))]

        scored_choices = []
        for direct_end_dlong, direct_distance, first_change, first_k, _ in first_beam:
            # A path is not eligible to win unless its first arc can actually
            # be committed continuously to the very next LP station.
            committed = _advance_to_target_dlong(
                current, first_k, target_dlong,
                center, dl, lo, hi, track_length, dlat_sign,
            )
            if committed is None:
                commit_retries += 1
                continue

            branch_state = _advance_checked(
                current, first_k, min(branch_feet, horizon_feet),
                center, dl, lo, hi, track_length, dlat_sign,
                sample_feet=12.0,
            )
            if branch_state is None:
                key = (
                    direct_end_dlong, direct_distance,
                    -first_change, -abs(first_k),
                )
                scored_choices.append((key, first_k, committed))
                continue

            remaining = max(0.0, horizon_feet - branch_feet)
            continuation_best = branch_state.dlong
            continuation_distance = 0.0
            continuation_change = float("inf")
            for second_k in curvatures:
                travelled2, end2 = _cast_clearance(
                    branch_state, float(second_k), remaining,
                    center, dl, lo, hi, track_length, dlat_sign,
                )
                tested += 1
                change = abs(float(second_k) - first_k)
                if (
                    end2.dlong > continuation_best
                    or (
                        abs(end2.dlong - continuation_best) < 1.0e-6
                        and (
                            travelled2 > continuation_distance
                            or (
                                abs(travelled2 - continuation_distance) < 1.0e-6
                                and change < continuation_change
                            )
                        )
                    )
                ):
                    continuation_best = end2.dlong
                    continuation_distance = travelled2
                    continuation_change = change

            # Actual projected track progress dominates. Smoothness/steering
            # only break near ties.
            key = (
                continuation_best,
                branch_feet + continuation_distance,
                -first_change,
                -abs(first_k),
            )
            scored_choices.append((key, first_k, committed))

        if scored_choices:
            scored_choices.sort(key=lambda item: item[0], reverse=True)
            _, _, current = scored_choices[0]
        else:
            # Do not teleport to the centerline. Preserve the previous lateral
            # offset as far as the next station's legal corridor permits.
            current = _fallback_station_state(
                current, i, target_dlong,
                center, lo, hi, dlat_sign,
            )
            continuity_recoveries += 1

        result.append(float(np.clip(current.dlat, lo[i], hi[i])))

        if progress_callback and i % 4 == 0:
            progress_callback(
                i, n - 1,
                f"Pathfinder world-space arc search: LP {i}/{n - 1}",
            )

    return (np.asarray(result) * 6000.0).tolist(), tested, n - 1, commit_retries, continuity_recoveries
