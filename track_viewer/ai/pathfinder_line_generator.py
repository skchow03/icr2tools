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


def generate_pathfinder(dlongs, lower, upper, seed, *, progress_callback=None, beam_width=28):
    """Construct DLAT from scratch with a receding-horizon straight/arc search.

    In (DLONG, DLAT) coordinates, constant curvature is approximated by a
    constant second derivative. Straight is exactly curvature=0.
    """
    n = len(seed)
    if n < 8:
        return list(seed), 0, 0
    dl = np.asarray(dlongs, dtype=float)
    lo = np.asarray(lower, dtype=float)
    hi = np.asarray(upper, dtype=float)
    # Work in feet for numerically sensible primitive parameters.
    s = (dl - dl[0]) / 6000.0
    width = (hi - lo) / 6000.0
    center = (hi + lo) / 12000.0
    start_lat = float(np.clip(seed[0] / 6000.0, lo[0] / 6000.0, hi[0] / 6000.0))
    step_records = max(2, n // 180)
    anchors = list(range(0, n, step_records))
    if anchors[-1] != n - 1:
        anchors.append(n - 1)

    # Curvature-like lateral acceleration per longitudinal foot. The choices
    # deliberately include straight and symmetric increasingly tight arcs.
    primitive_curvatures = np.array((-0.0018, -0.0010, -0.0005, -0.0002, 0.0,
                                      0.0002, 0.0005, 0.0010, 0.0018))
    states = [State(0, start_lat, 0.0, 0.0, 0.0, (start_lat,))]
    tested = 0

    for ai in range(1, len(anchors)):
        prev_i, idx = anchors[ai - 1], anchors[ai]
        ds = max((dl[idx] - dl[prev_i]) / 6000.0, 0.25)
        candidates = []
        low_ft, high_ft = lo[idx] / 6000.0, hi[idx] / 6000.0
        target_center = center[idx]
        for st in states:
            for k in primitive_curvatures:
                tested += 1
                lat = st.dlat + st.slope * ds + 0.5 * k * ds * ds
                slope = st.slope + k * ds
                if lat < low_ft or lat > high_ft:
                    continue
                # Check midpoint too so an arc cannot tunnel through an edge.
                mid_idx = (prev_i + idx) // 2
                half = ds * 0.5
                mid_lat = st.dlat + st.slope * half + 0.5 * k * half * half
                if mid_lat < lo[mid_idx] / 6000.0 or mid_lat > hi[mid_idx] / 6000.0:
                    continue
                progress = ds
                steering = abs(k) * ds
                steering_change = abs(k - st.curvature)
                lateral_motion = abs(lat - st.dlat)
                # Progress is common to survivors. Prefer the straightest arc,
                # gentle steering changes and less needless lateral wandering.
                # Tiny center preference breaks ties and helps avoid edge riding.
                cost = (st.cost + 9.0 * steering + 28.0 * steering_change
                        + 0.012 * lateral_motion
                        + 0.0008 * abs(lat - target_center)
                        - 0.02 * progress)
                candidates.append(State(
                    idx, lat, slope, float(k), cost, st.path + (lat,)
                ))
        if not candidates:
            # Best-effort fallback: continue from the seed at this anchor.
            best = min(states, key=lambda x: x.cost)
            lat = float(np.clip(seed[idx] / 6000.0, low_ft, high_ft))
            candidates = [State(idx, lat, 0.0, 0.0, best.cost + 10.0, best.path + (lat,))]
        candidates.sort(key=lambda x: x.cost)
        # Diversity buckets prevent all beam entries collapsing onto nearly
        # identical states before a corner becomes visible.
        kept = []
        for cand in candidates:
            if all(abs(cand.dlat - old.dlat) > 0.35 or abs(cand.slope - old.slope) > 0.01 for old in kept):
                kept.append(cand)
            if len(kept) >= beam_width:
                break
        states = kept or candidates[:beam_width]
        if progress_callback and ai % 4 == 0:
            progress_callback(ai, len(anchors) - 1, f"Pathfinder: {ai}/{len(anchors)-1} intervals")

    best = min(states, key=lambda x: x.cost)
    anchor_lat = np.asarray(best.path, dtype=float)
    anchor_s = s[np.asarray(anchors)]
    # Interpolate the committed primitive path back to LP record density.
    result_ft = np.interp(s, anchor_s, anchor_lat)
    result_ft = np.clip(result_ft, lo / 6000.0, hi / 6000.0)
    return (result_ft * 6000.0).tolist(), tested, len(anchors) - 1
