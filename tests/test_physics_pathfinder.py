import math

from track_viewer.ai.indycar_speed_model import CarPerformance
from track_viewer.ai.physics_pathfinder_line_generator import (
    _estimate_sequence,
    _score_node,
)
from track_viewer.ai.pathfinder_line_generator import State


def test_physics_sequence_accelerates_on_straight():
    result = _estimate_sequence(
        (0.0, 0.0),
        (200.0, 200.0),
        (0.0, 0.0),
        100.0,
        CarPerformance(),
        245.0,
    )
    assert result is not None
    elapsed, exit_speed = result
    assert elapsed > 0.0
    assert exit_speed >= 100.0


def test_physics_sequence_rejects_instant_impossible_tight_turn():
    result = _estimate_sequence(
        (1.0 / 42.0,),
        (150.0,),
        (0.0,),
        220.0,
        CarPerformance(),
        245.0,
    )
    assert result is None


def test_node_score_rewards_more_progress_for_same_time():
    near = State(0.0, 0.0, 0.0, 0.0, 0, 300.0, 0.0)
    far = State(0.0, 0.0, 0.0, 0.0, 0, 600.0, 0.0)
    near_score = _score_node(near, 0.0, 3.0, 0.0, 1400.0)
    far_score = _score_node(far, 0.0, 3.0, 0.0, 1400.0)
    assert math.isfinite(near_score)
    assert far_score < near_score
