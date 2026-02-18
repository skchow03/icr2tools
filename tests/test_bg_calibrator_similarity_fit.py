import math

import pytest

try:
    from sg_viewer.ui.bg_calibrator_minimal import mat2_mul_vec, similarity_fit, vec_scale
except ImportError:  # pragma: no cover
    pytest.skip("PyQt5 not available", allow_module_level=True)


def test_similarity_fit_recovers_known_transform():
    angle = math.radians(30.0)
    scale = 2.5
    c = math.cos(angle)
    s = math.sin(angle)
    R_true = ((c, -s), (s, c))

    P = [
        (-2.0, -1.0),
        (0.5, 3.0),
        (4.0, -2.0),
        (1.0, 1.0),
    ]
    Q = [vec_scale(mat2_mul_vec(R_true, p), scale) for p in P]

    fit_scale, fit_R = similarity_fit(P, Q)

    assert fit_scale == pytest.approx(scale, rel=1e-12, abs=1e-12)
    assert fit_R[0][0] == pytest.approx(R_true[0][0], rel=1e-12, abs=1e-12)
    assert fit_R[0][1] == pytest.approx(R_true[0][1], rel=1e-12, abs=1e-12)
    assert fit_R[1][0] == pytest.approx(R_true[1][0], rel=1e-12, abs=1e-12)
    assert fit_R[1][1] == pytest.approx(R_true[1][1], rel=1e-12, abs=1e-12)
