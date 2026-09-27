"""Topology-based pit-lane detection from TRK pavement and boundaries.

This module has no Qt dependencies. Values in the TRK and PIT lines are
Papyrus distance units (6000 units per foot); no TXT values are written here.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, replace
import math
from statistics import median
from typing import Sequence

from icr2_core.trk.trk_utils import getbounddlat, getgrounddlat
from track_viewer.model.pit_models import PitParameters

UNITS_PER_FOOT = 6000.0
PAVED_TYPES = frozenset(range(32, 56, 2))  # concrete, asphalt, paint
PIT_STALL_WALL_OFFSET = 31_250


@dataclass(frozen=True)
class Corridor:
    lo: float
    hi: float
    # An intermediate TRK boundary at the edge facing the racing surface.
    wall: float | None = None
    # A TRK boundary at the edge facing away from the racing surface.
    outer_wall: float | None = None

    @property
    def center(self) -> float:
        return (self.lo + self.hi) / 2

    @property
    def width(self) -> float:
        return self.hi - self.lo


@dataclass(frozen=True)
class Station:
    dlong: float
    roads: tuple[Corridor, ...]


@dataclass(frozen=True)
class PitSample:
    dlong: float
    pit: Corridor
    main: Corridor


@dataclass(frozen=True)
class PitCandidate:
    side: str
    samples: tuple[PitSample, ...]
    entrance_dlong: float
    exit_dlong: float
    length: float
    wall_dlat: float | None
    confidence: str
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PitDetection:
    candidates: tuple[PitCandidate, ...]
    dead_ends: int
    too_short: int


@dataclass(frozen=True)
class PitSuggestion:
    parameters: PitParameters
    updated_fields: tuple[str, ...]
    notes: tuple[str, ...]


def _lp_at(points: Sequence[tuple[float, float]], dlong: float, length: float) -> float | None:
    """Periodically interpolate an LP's DLAT without assuming matching grids."""
    if not points:
        return None
    samples = sorted((float(d) % length, float(v)) for d, v in points)
    positions = [p[0] for p in samples]
    i = bisect_right(positions, dlong % length)
    before = samples[i - 1] if i else (samples[-1][0] - length, samples[-1][1])
    after = samples[i] if i < len(samples) else (samples[0][0] + length, samples[0][1])
    distance = after[0] - before[0]
    return before[1] if distance <= 0 else before[1] + (
        (dlong % length - before[0]) / distance
    ) * (after[1] - before[1])


def _ground_and_wall_intervals(trk, section_id: int, fraction: float) -> tuple[Corridor, ...]:
    """Cut merged paved strips at every intermediate wall/Armco boundary."""
    sec = trk.sects[section_id]
    bounds = sorted(
        float(getbounddlat(trk, section_id, fraction, i))
        for i in range(sec.num_bounds)
    )
    if len(bounds) < 2 or not sec.ground_fsects:
        return ()
    left = bounds[-1]
    paved: list[tuple[float, float]] = []
    for i in range(sec.ground_fsects - 1, -1, -1):
        right = float(getgrounddlat(trk, section_id, fraction, i))
        if sec.ground_type[i] in PAVED_TYPES:
            paved.append((min(left, right), max(left, right)))
        left = right
    paved.sort()
    merged: list[tuple[float, float]] = []
    for lo, hi in paved:
        if merged and lo <= merged[-1][1] + 1.0:
            merged[-1] = (merged[-1][0], max(hi, merged[-1][1]))
        else:
            merged.append((lo, hi))

    roads: list[Corridor] = []
    for lo, hi in merged:
        for a, b in zip(bounds, bounds[1:]):
            start, end = max(lo, a), min(hi, b)
            if end - start >= 6 * UNITS_PER_FOOT:
                # The candidate-facing wall is picked later, after its side
                # and main racing corridor are identified.
                roads.append(Corridor(start, end))
    return tuple(sorted(roads, key=lambda p: p.lo))


def _stations(trk, sample_feet: float) -> list[Station]:
    if not trk.sects or float(trk.trklength) <= 0:
        return []
    stations: list[Station] = []
    for section_id, sec in enumerate(trk.sects):
        count = max(2, min(150, math.ceil(sec.length / (sample_feet * UNITS_PER_FOOT))))
        for k in range(count):
            fraction = (k + 0.5) / count
            dlong = (float(sec.start_dlong) + float(sec.length) * fraction) % float(trk.trklength)
            roads = _ground_and_wall_intervals(trk, section_id, fraction)
            stations.append(Station(dlong, roads))
            if len(stations) > 15000:
                raise ValueError("TRK contains too many sampling stations for pit detection.")
    # Section order normally already follows DLONG, but sorting handles unusual
    # section ordering and ensures the circular run detector has a lap order.
    return sorted(stations, key=lambda s: s.dlong)


def _gap(a: Corridor, b: Corridor) -> float:
    return max(a.lo - b.hi, b.lo - a.hi, 0.0)


def _nearest_main(roads: tuple[Corridor, ...], reference: float) -> int:
    return min(
        range(len(roads)),
        key=lambda i: (
            max(roads[i].lo - reference, reference - roads[i].hi, 0.0),
            -roads[i].width,
        ),
    )


def _side_sample(
    station: Station,
    side: str,
    reference: float,
    race_known: bool,
    trk,
) -> PitSample | None:
    roads = station.roads
    if len(roads) < 2:
        return None
    main = _nearest_main(roads, reference)
    # If zero falls exactly on the median wall and no RACE.LP is available,
    # both orientations must remain candidates for user confirmation.
    if not race_known and len(roads) == 2:
        distances = [
            max(r.lo - reference, reference - r.hi, 0.0) for r in roads
        ]
        if abs(distances[0] - distances[1]) <= UNITS_PER_FOOT and (
            abs(roads[0].hi - reference) <= UNITS_PER_FOOT
            and abs(roads[1].lo - reference) <= UNITS_PER_FOOT
        ):
            main = 1 if side == "right" else 0

    choices = [
        i for i in range(len(roads))
        if (i < main if side == "right" else i > main)
    ]
    if not choices:
        return None
    pit_index = max(choices) if side == "right" else min(choices)
    pit, racing = roads[pit_index], roads[main]
    if pit.width < 12 * UNITS_PER_FOOT:
        return None

    # Intermediate boundaries are physical walls/Armco, including walls
    # between identically paved strips.
    section_id = _section_at(trk, station.dlong)
    sec = trk.sects[section_id]
    fraction = max(0.0, min(1.0, (station.dlong - sec.start_dlong) / sec.length))
    boundaries = sorted(
        getbounddlat(trk, section_id, fraction, j)
        for j in range(sec.num_bounds)
    )
    median_edge = pit.hi if side == "right" else pit.lo
    outside_edge = pit.lo if side == "right" else pit.hi
    intermediate = boundaries[1:-1]
    matching = [b for b in intermediate if abs(b - median_edge) <= 2 * UNITS_PER_FOOT]
    outside_matching = [
        b for b in boundaries if abs(b - outside_edge) <= 2 * UNITS_PER_FOOT
    ]
    pit = replace(
        pit,
        wall=float(min(matching, key=lambda b: abs(b - median_edge))) if matching else None,
        outer_wall=float(min(outside_matching, key=lambda b: abs(b - outside_edge)))
        if outside_matching else None,
    )
    return PitSample(station.dlong, pit, racing)


def _section_at(trk, dlong: float) -> int:
    # A short binary search avoids the O(number of sections) lookup per sample
    # performed by the general-purpose dlong2sect helper.
    starts = [float(sec.start_dlong) for sec in trk.sects]
    return max(0, min(len(starts) - 1, bisect_right(starts, dlong) - 1))


def _runs(entries: list[PitSample | None]) -> list[list[PitSample]]:
    n = len(entries)
    if not n:
        return []
    starts = [
        i for i, entry in enumerate(entries)
        if entry is not None and (
            entries[(i - 1) % n] is None
            or _gap(entry.pit, entries[(i - 1) % n].pit) > 3 * UNITS_PER_FOOT
        )
    ]
    # A corridor that never separates and rejoins is not a detected pit lane.
    if not starts:
        return []
    runs: list[list[PitSample]] = []
    visited: set[int] = set()
    for start in starts:
        if start in visited:
            continue
        current = start
        run: list[PitSample] = []
        while current not in visited and entries[current] is not None:
            if run and _gap(run[-1].pit, entries[current].pit) > 3 * UNITS_PER_FOOT:
                break
            visited.add(current)
            run.append(entries[current])
            current = (current + 1) % n
        if run:
            runs.append(run)
    return runs


def detect_pit_lanes(
    trk,
    *,
    race_lp: Sequence[tuple[float, float]] = (),
    sample_feet: float = 25.0,
    min_length_feet: float = 250.0,
) -> PitDetection:
    """Detect sustained parallel paved branches with BOTH connections.

    Dead ends are explicitly rejected. A service road that does rejoin is
    geometrically indistinguishable from a pit lane, so all retained candidates
    must be reviewed by the user before applying any PIT values.
    """
    if sample_feet <= 0 or min_length_feet <= 0:
        raise ValueError("Sampling distance and minimum pit length must be positive.")
    stations = _stations(trk, sample_feet)
    if not stations:
        return PitDetection((), 0, 0)
    length = float(trk.trklength)
    candidates: list[PitCandidate] = []
    dead_ends = too_short = 0

    for side in ("right", "left"):
        entries = [
            _side_sample(
                station, side, _lp_at(race_lp, station.dlong, length) if race_lp else 0.0,
                bool(race_lp), trk,
            )
            for station in stations
        ]
        for run in _runs(entries):
            first, last = run[0], run[-1]
            first_index = next(i for i, e in enumerate(entries) if e is first)
            last_index = next(i for i, e in enumerate(entries) if e is last)
            previous = stations[(first_index - 1) % len(stations)]
            following = stations[(last_index + 1) % len(stations)]
            # A legitimate exit has to reconnect with the surface at the next
            # station. A road which vanishes while still separated is a spur.
            previous_main = previous.roads[_nearest_main(
                previous.roads, _lp_at(race_lp, previous.dlong, length) if race_lp else 0.0
            )] if previous.roads else None
            next_main = following.roads[_nearest_main(
                following.roads, _lp_at(race_lp, following.dlong, length) if race_lp else 0.0
            )] if following.roads else None
            if (
                previous_main is None or next_main is None
                or _gap(first.pit, previous_main) > 3 * UNITS_PER_FOOT
                or _gap(last.pit, next_main) > 3 * UNITS_PER_FOOT
            ):
                dead_ends += 1
                continue
            run_length = (last.dlong - first.dlong) % length
            if run_length < min_length_feet * UNITS_PER_FOOT or len(run) < 4:
                too_short += 1
                continue
            adjacency = [
                max(0.0, s.main.lo - s.pit.hi) if side == "right"
                else max(0.0, s.pit.lo - s.main.hi) for s in run
            ]
            if sum(g <= 75 * UNITS_PER_FOOT for g in adjacency) < .7 * len(run):
                # Distant connecting roads are unlikely to be pit lanes.
                too_short += 1
                continue
            walls = [s.pit.wall for s in run if s.pit.wall is not None]
            wall_dlat = float(median(walls)) if len(walls) >= len(run) * .6 else None
            notes: list[str] = []
            if wall_dlat is None:
                notes.append("No consistent median wall was detected; pit wall DLAT needs review.")
            if not race_lp:
                notes.append("RACE.LP unavailable; confirm which parallel road is the pit lane.")
            # Confidence describes the geometric evidence, not functional
            # proof that the corridor is the track's actual pit lane.
            confidence = "strong" if wall_dlat is not None and race_lp else "review"
            candidates.append(PitCandidate(
                side, tuple(run), first.dlong, last.dlong, run_length,
                wall_dlat, confidence, tuple(notes),
            ))

    candidates.sort(key=lambda c: (
        c.confidence != "strong", -len(c.samples), -c.length
    ))
    return PitDetection(tuple(candidates), dead_ends, too_short)


def _parallel_outer_wall_span(
    candidate: PitCandidate,
    track_length: float,
) -> tuple[float, float] | None:
    """Return the longest stall-sized run with a constant outside wall.

    Pit entry and exit pavement is commonly present well before and after the
    stalls, so the full detected corridor is not a useful stall-row extent.
    The outside edge of the pit corridor is the physical wall beside the
    stalls; while that wall is parallel to the centerline its DLAT is constant.
    """
    if not candidate.samples:
        return None
    ft = UNITS_PER_FOOT
    start = candidate.entrance_dlong
    observations = [
        (
            (sample.dlong - start) % track_length,
            sample.pit.outer_wall,
        )
        for sample in candidate.samples
        if sample.pit.outer_wall is not None
    ]
    if not observations:
        return None
    observations.sort()

    # Permit small TRK rounding/fitting noise, but do not let a gradually
    # angled approach qualify merely because each individual step is small.
    tolerance = 2 * ft
    best: tuple[int, int] | None = None
    left = 0
    for right in range(len(observations)):
        while left < right:
            values = [value for _, value in observations[left:right + 1]]
            if max(values) - min(values) <= tolerance:
                break
            left += 1
        if best is None or right - left > best[1] - best[0]:
            best = (left, right)

    if best is None:
        return None
    first, last = best
    # Four stations prevent a brief straight-looking part of an entry taper
    # from becoming a stall row. It must also fit a car stall plus the pace-car
    # space which follows the final opponent stall.
    if last - first + 1 < 4:
        return None
    span_start, span_end = observations[first][0], observations[last][0]
    if span_end - span_start < 110 * ft:
        return None
    return start + span_start, start + span_end


def recommend_pit_parameters(
    candidate: PitCandidate,
    track_length: float,
    current: PitParameters | None,
    *,
    lp_lines: dict[str, Sequence[tuple[float, float]]] | None = None,
) -> PitSuggestion:
    """Conservative geometry-derived suggestions, never a direct TXT write."""
    if track_length <= 0:
        raise ValueError("A positive track length is required.")
    baseline = current or PitParameters.empty()
    changes: dict[str, int] = {}
    notes = list(candidate.notes)
    start = candidate.entrance_dlong
    total = candidate.length
    ft = UNITS_PER_FOOT
    wrap = lambda x: round(x % track_length)
    changes["pit_access_start_dlong"] = wrap(start - 25 * ft)
    changes["pit_access_end_dlong"] = wrap(start + total + 12 * ft)
    changes["pit_to_race_transition_dlong"] = wrap(start + total + 150 * ft)

    wall_span = _parallel_outer_wall_span(candidate, track_length)
    spacing = 45 * ft
    if wall_span is None:
        notes.append(
            "No sufficiently long, centerline-parallel outside pit wall was "
            "found; stall positions and count were left unchanged."
        )
    else:
        usable_start, parallel_end = wall_span
        # The pace car occupies the position after the final opponent stall.
        usable_end = parallel_end - 65 * ft
        if usable_end <= usable_start:
            notes.append(
                "The parallel outside-wall span is too short for a stall row "
                "and pace-car space."
            )
            usable_end = usable_start - 1
        capacity = 1 + int((usable_end - usable_start) // spacing)
        count = int(baseline.pit_stall_count)
        if count <= 0:
            count = min(capacity, 40)
            changes["pit_stall_count"] = count
            notes.append(f"Suggested {count} stalls at an assumed 45 ft spacing; verify actual capacity.")
        elif count > capacity:
            notes.append(
                f"Existing {count} stalls exceed the estimated {capacity}-stall capacity; "
                "stall positions and count were left unchanged."
            )
        if 0 < count <= capacity:
            # The constant-wall span identifies both ends of the stall row.
            # Count is used to validate capacity, not to pull those endpoints
            # inward using an assumed spacing.
            first_stall = usable_start
            last_stall = usable_end
            changes["player_pit_stall_dlong"] = wrap(first_stall)
            changes["last_pit_stall_dlong"] = wrap(last_stall)
            stall_samples = [
                sample for sample in candidate.samples
                if ((sample.dlong - start) % track_length) >= first_stall - start
                and ((sample.dlong - start) % track_length) <= last_stall - start
            ]
            if not stall_samples:
                stall_samples = [candidate.samples[len(candidate.samples) // 2]]
            # A constant PIT DLAT must stay inside the pavement at ALL stalls.
            legal_lo = max(s.pit.lo + 4 * ft for s in stall_samples)
            legal_hi = min(s.pit.hi - 4 * ft for s in stall_samples)
            # Cars are parked beside the outside (farthest) pit wall, not the
            # pit-wall edge facing the racing surface.  DLAT increases toward
            # track left, so move right-pit stalls upward from their low outer
            # wall and left-pit stalls downward from their high outer wall.
            outer_wall = median(
                s.pit.outer_wall
                for s in stall_samples
                if s.pit.outer_wall is not None
            )
            preferred = outer_wall + (
                PIT_STALL_WALL_OFFSET if candidate.side == "right"
                else -PIT_STALL_WALL_OFFSET
            )
            if legal_lo <= legal_hi:
                changes["pit_stall_center_dlat"] = round(
                    min(max(preferred, legal_lo), legal_hi)
                )
            else:
                notes.append("Pit width/position varies across stalls; no safe constant stall DLAT.")
            walls = [s.pit.wall for s in stall_samples if s.pit.wall is not None]
            if len(walls) >= .6 * len(stall_samples) and (
                max(walls) - min(walls) <= 2 * ft
            ):
                changes["pitwall_dlat"] = round(median(walls))
            else:
                notes.append("A constant physical pit wall was not verified; existing wall DLAT retained.")

    lines = lp_lines or {}
    pit = lines.get("PIT", ())
    minpanic, maxpanic = lines.get("MINPANIC", ()), lines.get("MAXPANIC", ())
    if pit and minpanic and maxpanic:
        outside: list[float] = []
        for s in candidate.samples:
            v = _lp_at(pit, s.dlong, track_length)
            lo = _lp_at(minpanic, s.dlong, track_length)
            hi = _lp_at(maxpanic, s.dlong, track_length)
            if v is not None and lo is not None and hi is not None and (
                v < min(lo, hi) or v > max(lo, hi)
            ):
                outside.append(s.dlong)
        if outside:
            changes["pit_speed_limit_start_dlong"] = wrap(outside[0])
            changes["pit_speed_limit_end_dlong"] = wrap(outside[-1])
        else:
            notes.append("PIT.LP never leaves PANIC boundaries in the detected corridor.")
    else:
        changes["pit_speed_limit_start_dlong"] = wrap(start + 40 * ft)
        changes["pit_speed_limit_end_dlong"] = wrap(start + total - 40 * ft)
        notes.append("Speed-limit points are geometric estimates; verify against PIT.LP and PANIC.")

    # No reliable meaning is established for the ninth PIT value.
    notes.append("PIT value 9 (unknown DLONG) is preserved without modification.")
    return PitSuggestion(
        replace(baseline, **changes), tuple(changes), tuple(dict.fromkeys(notes))
    )
