"""Beam-search racing-line constructor using straight/arc path primitives."""

from __future__ import annotations
from dataclasses import dataclass
import numpy as np


@dataclass
class State:
    index: int
    dlat: float
    slope: float
    curvature: float
    cost: float
    path: tuple


def generate_pathfinder(dlongs, lower, upper, seed, *, progress_callback=None, beam_width=160):
    """Construct DLAT using every LP interval and a broad arc beam.

    Each state advances exactly one LP record. Very shallow curvatures are
    included so a wide arc can survive for hundreds of records and beat a
    centerline-parallel path when it fits farther through an upcoming bend.
    """
    n = len(seed)
    if n < 8:
        return list(seed), 0, 0
    dl = np.asarray(dlongs, dtype=float)
    lo = np.asarray(lower, dtype=float) / 6000.0
    hi = np.asarray(upper, dtype=float) / 6000.0
    start_lat = float(np.clip(seed[0] / 6000.0, lo[0], hi[0]))

    # Dense near zero: these are the wide arcs missing from the earlier model.
    primitive_curvatures = np.array((
        -0.0020, -0.0012, -0.0007, -0.0004, -0.00022, -0.00012,
        -0.00006, -0.00003, -0.000015, 0.0,
         0.000015, 0.00003, 0.00006, 0.00012, 0.00022, 0.0004,
         0.0007, 0.0012, 0.0020,
    ))
    states = [State(0, start_lat, 0.0, 0.0, 0.0, (start_lat,))]
    tested = 0

    for idx in range(1, n):
        prev_i = idx - 1
        ds = max((dl[idx] - dl[prev_i]) / 6000.0, 0.05)
        candidates = []
        for st in states:
            for k in primitive_curvatures:
                tested += 1
                lat = st.dlat + st.slope * ds + 0.5 * k * ds * ds
                slope = st.slope + k * ds
                if lat < lo[idx] or lat > hi[idx]:
                    continue
                # Quarter/mid/three-quarter checks make wide arcs obey corridor
                # changes between LP samples instead of merely endpoint clipping.
                legal = True
                for frac in (0.25, 0.5, 0.75):
                    qlat = st.dlat + st.slope * (ds * frac) + 0.5 * k * (ds * frac) ** 2
                    qlo = lo[prev_i] + (lo[idx] - lo[prev_i]) * frac
                    qhi = hi[prev_i] + (hi[idx] - hi[prev_i]) * frac
                    if qlat < qlo or qlat > qhi:
                        legal = False
                        break
                if not legal:
                    continue

                # The main objective is survival/progress. Since all candidates
                # at this generation have equal progress, these terms only rank
                # which states remain in the beam for future LP intervals.
                steering_change = abs(k - st.curvature)
                lateral_motion = abs(lat - st.dlat)
                edge_clearance = min(lat - lo[idx], hi[idx] - lat)
                cost = (
                    st.cost
                    + 0.20 * abs(k) * ds
                    + 1.5 * steering_change
                    + 0.0005 * lateral_motion
                    - 0.00005 * edge_clearance
                )
                candidates.append(State(
                    idx, lat, slope, float(k), cost, st.path + (lat,)
                ))

        if not candidates:
            best = min(states, key=lambda x: x.cost)
            lat = float(np.clip(seed[idx] / 6000.0, lo[idx], hi[idx]))
            candidates = [State(idx, lat, 0.0, 0.0, best.cost + 1.0, best.path + (lat,))]

        candidates.sort(key=lambda x: x.cost)
        kept = []
        # Much finer diversity buckets: preserve many distinct shallow arcs.
        for cand in candidates:
            if all(
                abs(cand.dlat - old.dlat) > 0.12
                or abs(cand.slope - old.slope) > 0.003
                or abs(cand.curvature - old.curvature) > 0.000025
                for old in kept
            ):
                kept.append(cand)
            if len(kept) >= beam_width:
                break
        states = kept or candidates[:beam_width]
        if progress_callback and idx % 16 == 0:
            progress_callback(idx, n - 1, f"Pathfinder: LP interval {idx}/{n-1}")

    best = min(states, key=lambda x: x.cost)
    result_ft = np.asarray(best.path, dtype=float)
    result_ft = np.clip(result_ft, lo, hi)
    return (result_ft * 6000.0).tolist(), tested, n - 1
