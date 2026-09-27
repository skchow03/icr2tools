"""Regression tests for topology-based PIT detection.

These use small TRK-shaped fixtures, not track-specific PIT/TXT metadata.
"""
from types import SimpleNamespace

from track_viewer.model.pit_models import PitParameters
from track_viewer.pit.pit_lane_detector import (
    Corridor, PitCandidate, PitSample, detect_pit_lanes,
    recommend_pit_parameters,
)

FT = 6000
SECTION = 300 * FT


def _section(i, *, pit=False, wall=False, drifting=False):
    if not pit:
        bounds = [-50 * FT, 50 * FT]
        ground = [40]
        breaks = [-50 * FT]
    elif wall:
        bounds = [-90 * FT, 0, 50 * FT]
        ground = [40]
        breaks = [-90 * FT]
    elif drifting:
        bounds = [-150 * FT, 50 * FT]
        ground = [40, 0, 40]
        breaks = [-150 * FT, -80 * FT, -25 * FT]
    else:
        bounds = [-90 * FT, 50 * FT]
        ground = [40, 0, 40]  # pavement, median grass, pavement
        breaks = [-90 * FT, -30 * FT, -25 * FT]

    return SimpleNamespace(
        start_dlong=i * SECTION,
        length=SECTION,
        num_bounds=len(bounds),
        bound_dlat_start=bounds,
        bound_dlat_end=bounds,
        ground_fsects=len(ground),
        ground_type=ground,
        ground_dlat_start=breaks,
        ground_dlat_end=breaks,
    )


def _trk(*sections):
    return SimpleNamespace(
        sects=list(sections), trklength=len(sections) * SECTION
    )


def test_detects_grass_divided_pit_and_fills_values_conservatively():
    trk = _trk(
        _section(0), _section(1, pit=True),
        _section(2, pit=True), _section(3),
    )
    result = detect_pit_lanes(trk)
    right = [c for c in result.candidates if c.side == "right"]
    assert len(right) == 1
    assert right[0].length > 400 * FT
    assert right[0].wall_dlat is None

    original = PitParameters.from_values([
        123, 0, 0, 0, 0, 0, 0, 3, 456, 0, 0
    ])
    suggestion = recommend_pit_parameters(right[0], trk.trklength, original)
    assert suggestion.parameters.pit_stall_count == 3
    assert suggestion.parameters.unknown_dlong == 456
    assert suggestion.parameters.pitwall_dlat == 123  # not a real wall
    assert suggestion.parameters.player_pit_stall_dlong != 0
    assert suggestion.parameters.last_pit_stall_dlong > suggestion.parameters.player_pit_stall_dlong
    assert suggestion.parameters.pit_stall_center_dlat < 0
    assert "unknown_dlong" not in suggestion.updated_fields


def test_rejects_road_that_leaves_the_track_without_rejoining():
    trk = _trk(
        _section(0), _section(1, pit=True),
        _section(2, pit=True, drifting=True), _section(3),
    )
    result = detect_pit_lanes(trk)
    assert not result.candidates
    assert result.dead_ends > 0


def test_paved_surface_divided_only_by_armco():
    trk = _trk(
        _section(0), _section(1, pit=True, wall=True),
        _section(2, pit=True, wall=True), _section(3),
    )
    race = [(0, 25 * FT), (2 * SECTION, 25 * FT)]
    result = detect_pit_lanes(trk, race_lp=race)
    assert len(result.candidates) == 1
    pit = result.candidates[0]
    assert pit.side == "right"
    assert pit.wall_dlat == 0
    assert pit.confidence == "strong"


def test_wraparound_entrance_and_exit():
    trk = _trk(
        _section(0, pit=True), _section(1),
        _section(2), _section(3, pit=True),
    )
    result = detect_pit_lanes(trk)
    right = [c for c in result.candidates if c.side == "right"]
    assert len(right) == 1
    assert right[0].entrance_dlong > right[0].exit_dlong
    assert right[0].length > 400 * FT


def test_speed_limit_uses_lp_panic_separation_when_available():
    trk = _trk(
        _section(0), _section(1, pit=True),
        _section(2, pit=True), _section(3),
    )
    candidate = next(c for c in detect_pit_lanes(trk).candidates if c.side == "right")
    lines = {
        "PIT": [(0, 0), (SECTION + 100 * FT, 0),
                (SECTION + 175 * FT, -55 * FT), (2 * SECTION, -55 * FT),
                (3 * SECTION, 0)],
        "MINPANIC": [(0, -10 * FT)],
        "MAXPANIC": [(0, 10 * FT)],
    }
    original = PitParameters.empty()
    suggestion = recommend_pit_parameters(candidate, trk.trklength, original, lp_lines=lines)
    assert suggestion.parameters.pit_speed_limit_start_dlong > candidate.entrance_dlong
    assert suggestion.parameters.pit_speed_limit_end_dlong < candidate.exit_dlong


def test_stall_row_starts_where_outside_wall_becomes_parallel():
    samples = []
    for feet in range(0, 601, 25):
        if feet < 100:
            outside = -80 - feet / 5
        elif feet <= 500:
            outside = -100
        else:
            outside = -100 + (feet - 500) / 5
        pit = Corridor(outside * FT, -25 * FT, outer_wall=outside * FT)
        samples.append(PitSample(feet * FT, pit, Corridor(0, 50 * FT)))
    candidate = PitCandidate(
        "right", tuple(samples), 0, 600 * FT, 600 * FT, None, "review"
    )
    original = PitParameters.from_values([
        0, 0, 0, 999, 999, 0, 0, 4, 0, 0, 0
    ])

    suggestion = recommend_pit_parameters(candidate, 1000 * FT, original)

    assert suggestion.parameters.player_pit_stall_dlong == 100 * FT
    assert suggestion.parameters.last_pit_stall_dlong == 435 * FT
    assert suggestion.parameters.pit_stall_count == 4


def test_stalls_unchanged_without_long_parallel_outside_wall():
    samples = tuple(
        PitSample(
            feet * FT,
            Corridor(
                (-80 - feet / 10) * FT,
                -25 * FT,
                outer_wall=(-80 - feet / 10) * FT,
            ),
            Corridor(0, 50 * FT),
        )
        for feet in range(0, 601, 25)
    )
    candidate = PitCandidate(
        "right", samples, 0, 600 * FT, 600 * FT, None, "review"
    )
    original = PitParameters.from_values([
        0, 0, 0, 111, 222, 0, 0, 4, 0, 0, 0
    ])

    suggestion = recommend_pit_parameters(candidate, 1000 * FT, original)

    assert suggestion.parameters.player_pit_stall_dlong == 111
    assert suggestion.parameters.last_pit_stall_dlong == 222
    assert any("parallel outside pit wall" in note for note in suggestion.notes)
