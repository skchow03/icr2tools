"""Experimental physics-aware receding-horizon racing-line planner.

This extends the geometric Pathfinder idea by evaluating deeper arc sequences
with the existing 1995 CART performance model. It is intentionally kept
separate from the original Pathfinder so the two approaches remain directly
comparable.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import numpy as np

from track_viewer.ai.indycar_speed_model import (
    CarPerformance,
    G_FPS2,
    MAX_SPEED_MPH,
    MPH_TO_FPS,
    _ACCEL_G,
    _BRAKE_G,
    _corner_speed_mph,
    _interp,
)
from track_viewer.ai.pathfinder_line_generator import (
    State,
    _advance_checked,
    _advance_to_target_dlong,
    _cast_clearance,
    _smooth_periodic_seam,
)


@dataclass
class SearchNode:
    state: State
    first_curvature: float
    curvatures: tuple[float, ...]
    distances: tuple[float, ...]
    elapsed_seconds: float
    exit_speed_mph: float
    score_seconds: float
    steering_cost: float
    bankings: tuple[float, ...]


def _candidate_curvatures() -> np.ndarray:
    """Return the same useful radius family as geometric Pathfinder."""
    radii = (
        3200.0, 1800.0, 1100.0, 750.0, 520.0, 360.0,
        250.0, 175.0, 120.0, 85.0, 60.0, 42.0,
    )
    positive = [1.0 / r for r in radii]
    return np.asarray([-k for k in reversed(positive)] + [0.0] + positive)


def _periodic_interp(
    dlong: float,
    dlongs_ft: np.ndarray,
    values: np.ndarray,
    track_length_ft: float,
) -> float:
    if len(values) == 0:
        return 0.0
    x = float(dlong) % track_length_ft
    extended_x = np.concatenate((
        dlongs_ft[-1:] - track_length_ft,
        dlongs_ft,
        dlongs_ft[:1] + track_length_ft,
    ))
    extended_y = np.concatenate((values[-1:], values, values[:1]))
    return float(np.interp(x, extended_x, extended_y))


def _accel_fps2(speed_mph: float, performance: CarPerformance) -> float:
    return (
        performance.safety_factor
        * performance.acceleration_factor
        * _interp(_ACCEL_G, max(0.0, speed_mph))
        * G_FPS2
    )


def _brake_fps2(speed_mph: float, performance: CarPerformance) -> float:
    return (
        performance.safety_factor
        * performance.braking_factor
        * _interp(_BRAKE_G, max(0.0, speed_mph))
        * G_FPS2
    )


def _estimate_sequence(
    curvatures: tuple[float, ...],
    distances: tuple[float, ...],
    banking_degrees: tuple[float, ...],
    start_speed_mph: float,
    performance: CarPerformance,
    max_speed_mph: float,
) -> tuple[float, float] | None:
    """Estimate traversal time with lateral, acceleration and braking limits.

    Each search stage is a constant-curvature motion primitive. The speed at
    every stage boundary is limited by the adjacent cornering limits. A
    backward braking pass then makes sure future stages remain reachable, and a
    forward acceleration pass estimates the speed actually achieved.
    """
    count = len(curvatures)
    if count == 0 or count != len(distances) or count != len(banking_degrees):
        return None

    limits = np.asarray([
        min(
            float(max_speed_mph),
            float(MAX_SPEED_MPH),
            _corner_speed_mph(k, performance, bank),
        )
        for k, bank in zip(curvatures, banking_degrees)
    ], dtype=float)

    start_speed = min(float(start_speed_mph), float(max_speed_mph), float(MAX_SPEED_MPH))
    if start_speed < 1.0:
        start_speed = 1.0

    # The first primitive starts immediately at the current state; it cannot
    # demand an instantaneous reduction to a lower cornering limit.
    if start_speed > limits[0] + 0.5:
        return None

    caps = np.empty(count + 1, dtype=float)
    caps[0] = min(start_speed, limits[0])
    for i in range(1, count):
        caps[i] = min(limits[i - 1], limits[i])
    caps[count] = limits[-1]

    allowed = caps.copy()
    for i in range(count - 1, -1, -1):
        downstream_fps = allowed[i + 1] * MPH_TO_FPS
        guess = max(float(allowed[i]), float(allowed[i + 1]))
        brake = _brake_fps2(guess, performance)
        upstream = math.sqrt(max(
            0.0,
            downstream_fps * downstream_fps
            + 2.0 * brake * max(0.0, float(distances[i])),
        )) / MPH_TO_FPS
        allowed[i] = min(allowed[i], upstream)

    if start_speed > allowed[0] + 0.5:
        return None

    speeds = np.empty(count + 1, dtype=float)
    speeds[0] = start_speed
    elapsed = 0.0

    for i in range(count):
        distance = max(0.01, float(distances[i]))
        v0_fps = speeds[i] * MPH_TO_FPS
        accel = _accel_fps2(speeds[i], performance)
        reachable = math.sqrt(max(
            0.0, v0_fps * v0_fps + 2.0 * accel * distance
        )) / MPH_TO_FPS
        speeds[i + 1] = min(float(allowed[i + 1]), reachable)

        v1_fps = speeds[i + 1] * MPH_TO_FPS
        denom = max(v0_fps + v1_fps, 1.0)
        elapsed += 2.0 * distance / denom

    return float(elapsed), float(speeds[-1])


def _score_node(
    state: State,
    start_dlong: float,
    elapsed_seconds: float,
    steering_cost: float,
    horizon_feet: float,
) -> float:
    """Convert time and actual track progress into a comparable horizon cost."""
    progress = float(state.dlong - start_dlong)
    if progress <= 1.0 or elapsed_seconds <= 0.0:
        return float("inf")
    projected_time = elapsed_seconds * float(horizon_feet) / progress
    # Small regularizer: physics/time dominates, but gratuitous curvature
    # reversals lose close ties and produce a more drivable final LP.
    return projected_time + 0.055 * steering_cost


def generate_physics_pathfinder(
    dlongs,
    lower,
    upper,
    seed,
    center_xy,
    track_length_feet,
    dlat_sign,
    *,
    reference_speeds_mph,
    banking_degrees,
    performance: CarPerformance | None = None,
    max_speed_mph: float = 245.0,
    progress_callback=None,
    beam_width: int = 24,
    horizon_feet: float = 1260.0,
    decision_feet: float = 180.0,
    depth: int = 6,
    terminal_feet: float = 180.0,
    minimum_stage_feet: float = 30.0,
):
    """Generate a physics-aware line by deeper receding-horizon beam search.

    Search nodes are sequences of true XY circular arcs. Each primitive is
    cast only until it reaches the legal boundary or the decision horizon;
    reaching the boundary is therefore a natural place to steer again rather
    than a reason to discard the whole candidate. Candidates are rejected when
    they cannot make useful forward progress or when the current speed cannot
    physically satisfy the sequence's lateral/braking requirements. Remaining
    nodes are ranked by predicted time per unit of actual DLONG progress, with
    a steering-change regularizer.

    Only the first arc is committed to the next LP station, then the complete
    search is repeated.
    """
    n = len(seed)
    if n < 8:
        return list(seed), 0, 0, 0, 0, 0.0, 0.0

    performance = performance or CarPerformance()
    center = np.asarray(center_xy, dtype=float)
    dl = np.asarray(dlongs, dtype=float) / 6000.0
    lo = np.asarray(lower, dtype=float) / 6000.0
    hi = np.asarray(upper, dtype=float) / 6000.0
    reference_speeds = np.asarray(reference_speeds_mph, dtype=float)
    banking = np.asarray(banking_degrees, dtype=float)
    track_length = float(track_length_feet)

    if reference_speeds.shape != (n,):
        raise ValueError("Physics Pathfinder reference speeds must match LP samples.")
    if banking.shape != (n,):
        raise ValueError("Physics Pathfinder banking must match LP samples.")

    curvatures = _candidate_curvatures()

    start_dlat = float(np.clip(0.0, lo[0], hi[0]))
    cx0, cy0 = float(center[0, 0]), float(center[0, 1])
    cx1, cy1 = float(center[1, 0]), float(center[1, 1])
    cxm, cym = float(center[-1, 0]), float(center[-1, 1])
    tx = cx1 - cxm
    ty = cy1 - cym
    tangent_len = max(math.hypot(tx, ty), 1.0e-9)
    tx /= tangent_len
    ty /= tangent_len
    nx = -ty * dlat_sign
    ny = tx * dlat_sign

    current = State(
        cx0 + nx * start_dlat,
        cy0 + ny * start_dlat,
        math.atan2(ty, tx),
        0.0,
        0,
        float(dl[0]),
        start_dlat,
    )

    result = [start_dlat]
    tested = 0
    rejected_physics = 0
    continuity_recoveries = 0

    for i in range(1, n):
        target_dlong = float(dl[i])
        start_dlong = float(current.dlong)
        planning_speed = float(np.clip(
            reference_speeds[(i - 1) % n], 1.0, max_speed_mph
        ))

        beam: list[SearchNode] = []

        for stage in range(max(1, int(depth))):
            expanded: list[SearchNode] = []
            parents = beam if beam else [None]

            for parent in parents:
                parent_state = current if parent is None else parent.state
                prior_curvatures = () if parent is None else parent.curvatures
                prior_distances = () if parent is None else parent.distances
                prior_steering = 0.0 if parent is None else parent.steering_cost
                previous_k = current.curvature if parent is None else prior_curvatures[-1]

                for k in curvatures:
                    tested += 1

                    # The first arc must be continuously commit-able to the
                    # next LP station. This prevents spending the beam budget
                    # on paths that will inevitably trigger a recovery.
                    if parent is None:
                        first_commit = _advance_to_target_dlong(
                            current,
                            float(k),
                            target_dlong,
                            center,
                            dl,
                            lo,
                            hi,
                            track_length,
                            dlat_sign,
                        )
                        if first_commit is None:
                            continue

                    # Unlike v1, do not require one curvature to remain legal
                    # for the entire decision distance. Cast until the boundary
                    # or horizon and let the next stage steer from there.
                    travelled, next_state = _cast_clearance(
                        parent_state,
                        float(k),
                        float(decision_feet),
                        center,
                        dl,
                        lo,
                        hi,
                        track_length,
                        dlat_sign,
                        sample_feet=12.0,
                    )
                    stage_progress = float(next_state.dlong - parent_state.dlong)
                    if (
                        travelled < float(minimum_stage_feet)
                        or stage_progress < max(8.0, 0.20 * travelled)
                    ):
                        continue

                    seq_k = prior_curvatures + (float(k),)
                    seq_d = prior_distances + (float(travelled),)
                    stage_bank = _periodic_interp(
                        0.5 * (parent_state.dlong + next_state.dlong),
                        dl,
                        banking,
                        track_length,
                    )
                    prior_banks = () if parent is None else parent.bankings
                    banks = prior_banks + (stage_bank,)
                    estimate = _estimate_sequence(
                        seq_k,
                        seq_d,
                        banks,
                        planning_speed,
                        performance,
                        max_speed_mph,
                    )
                    if estimate is None:
                        rejected_physics += 1
                        continue

                    elapsed, exit_speed = estimate
                    steering = prior_steering + abs(float(k) - float(previous_k)) * 1000.0
                    score = _score_node(
                        next_state,
                        start_dlong,
                        elapsed,
                        steering,
                        horizon_feet,
                    )
                    if not math.isfinite(score):
                        continue

                    expanded.append(SearchNode(
                        state=next_state,
                        first_curvature=float(k) if parent is None else parent.first_curvature,
                        curvatures=seq_k,
                        distances=seq_d,
                        elapsed_seconds=elapsed,
                        exit_speed_mph=exit_speed,
                        score_seconds=score,
                        steering_cost=steering,
                        bankings=banks,
                    ))

            if not expanded:
                break

            expanded.sort(key=lambda node: (
                node.score_seconds,
                -node.state.dlong,
                node.steering_cost,
                abs(node.first_curvature),
            ))
            beam = expanded[:max(1, int(beam_width))]

        # Give each finalist one uncommitted continuation step. This reduces
        # the classic finite-horizon failure mode of arriving at the horizon
        # very fast but badly positioned for the next corner.
        finalists: list[SearchNode] = []
        for parent in beam:
            best_terminal: SearchNode | None = None
            for k in curvatures:
                tested += 1
                travelled, end_state = _cast_clearance(
                    parent.state,
                    float(k),
                    float(terminal_feet),
                    center,
                    dl,
                    lo,
                    hi,
                    track_length,
                    dlat_sign,
                    sample_feet=12.0,
                )
                terminal_progress = float(end_state.dlong - parent.state.dlong)
                if travelled < 20.0 or terminal_progress < max(6.0, 0.20 * travelled):
                    continue

                seq_k = parent.curvatures + (float(k),)
                seq_d = parent.distances + (float(travelled),)
                terminal_bank = _periodic_interp(
                    0.5 * (parent.state.dlong + end_state.dlong),
                    dl,
                    banking,
                    track_length,
                )
                banks = parent.bankings + (terminal_bank,)
                estimate = _estimate_sequence(
                    seq_k,
                    seq_d,
                    banks,
                    planning_speed,
                    performance,
                    max_speed_mph,
                )
                if estimate is None:
                    rejected_physics += 1
                    continue

                elapsed, exit_speed = estimate
                steering = (
                    parent.steering_cost
                    + abs(float(k) - parent.curvatures[-1]) * 1000.0
                )
                score = _score_node(
                    end_state,
                    start_dlong,
                    elapsed,
                    steering,
                    horizon_feet,
                )
                candidate = SearchNode(
                    state=end_state,
                    first_curvature=parent.first_curvature,
                    curvatures=seq_k,
                    distances=seq_d,
                    elapsed_seconds=elapsed,
                    exit_speed_mph=exit_speed,
                    score_seconds=score,
                    steering_cost=steering,
                    bankings=banks,
                )
                if (
                    best_terminal is None
                    or candidate.score_seconds < best_terminal.score_seconds
                ):
                    best_terminal = candidate

            finalists.append(best_terminal or parent)

        if finalists:
            finalists.sort(key=lambda node: (
                node.score_seconds,
                -node.state.dlong,
                node.steering_cost,
                abs(node.first_curvature),
            ))
            chosen_k = finalists[0].first_curvature
            committed = _advance_to_target_dlong(
                current,
                chosen_k,
                target_dlong,
                center,
                dl,
                lo,
                hi,
                track_length,
                dlat_sign,
            )
        else:
            committed = None

        if committed is None:
            # Preserve continuity by trying the legal curvature closest to the
            # previous steering state before falling back to the current DLAT.
            legal_commit = None
            for k in sorted(curvatures, key=lambda value: abs(value - current.curvature)):
                trial = _advance_to_target_dlong(
                    current,
                    float(k),
                    target_dlong,
                    center,
                    dl,
                    lo,
                    hi,
                    track_length,
                    dlat_sign,
                )
                if trial is not None:
                    legal_commit = trial
                    break
            if legal_commit is None:
                # No lateral teleport: retain the previous offset, clipped only
                # if the legal corridor narrows at the next LP station.
                dlat = float(np.clip(current.dlat, lo[i], hi[i]))
                j = i % n
                prev_j = (j - 1) % n
                next_j = (j + 1) % n
                ltx = float(center[next_j, 0] - center[prev_j, 0])
                lty = float(center[next_j, 1] - center[prev_j, 1])
                length = max(math.hypot(ltx, lty), 1.0e-9)
                ltx /= length
                lty /= length
                lnx = -lty * dlat_sign
                lny = ltx * dlat_sign
                current = State(
                    float(center[j, 0]) + lnx * dlat,
                    float(center[j, 1]) + lny * dlat,
                    current.heading,
                    current.curvature,
                    j,
                    target_dlong,
                    dlat,
                )
            else:
                current = legal_commit
            continuity_recoveries += 1
        else:
            current = committed

        result.append(float(np.clip(current.dlat, lo[i], hi[i])))

        if progress_callback and i % 2 == 0:
            progress_callback(
                i,
                n - 1,
                f"Physics Pathfinder beam search: LP {i}/{n - 1}",
            )

    result_array = np.asarray(result, dtype=float)
    result_array, seam_window, seam_adjustment = _smooth_periodic_seam(
        result_array,
        dl,
        lo,
        hi,
        track_length,
    )
    return (
        (result_array * 6000.0).tolist(),
        tested,
        n - 1,
        rejected_physics,
        continuity_recoveries,
        seam_window,
        seam_adjustment,
    )
