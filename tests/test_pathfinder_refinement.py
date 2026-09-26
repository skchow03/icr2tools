"""Baseline protection and curvature guards for Pathfinder Refinement."""
import numpy as np

from track_viewer.ai.pathfinder_refinement import refine_pathfinder


def test_refinement_never_returns_slower_than_pathfinder():
    n = 64
    seed = np.zeros(n)
    theta = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)

    def xy(dlats):
        radius = 100.0 + np.asarray(dlats) / 6000.0
        return np.column_stack((radius * np.cos(theta), radius * np.sin(theta)))

    def evaluate(dlats):
        # The baseline is deliberately optimal; any displacement costs time.
        return 52.6 + float(np.sum(np.square(dlats / 6000.0))), np.full(n, 110.0)

    result, speeds, before, after, trials, accepted, regions = refine_pathfinder(
        seed, np.full(n, -30000.0), np.full(n, 30000.0),
        xy, evaluate,
    )
    assert before == 52.6
    assert after == 52.6
    assert np.allclose(result, seed)
    assert np.allclose(speeds, 110.0)
    assert accepted == 0
    assert trials > 0
