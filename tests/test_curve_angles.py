import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

try:  # pragma: no cover - allows tests to be skipped in headless CI without PyQt5
    from sg_viewer.preview_widget import _curve_angles
except ImportError:  # pragma: no cover
    pytest.skip("PyQt5 not available", allow_module_level=True)


def test_curve_angles_positive_radius():
    angles = _curve_angles((5.0, 3.0), (7.0, -1.0), (2.0, 1.0), 100.0)

    assert angles == (-2.0, 3.0, 2.0, 5.0)


def test_curve_angles_negative_radius():
    angles = _curve_angles((5.0, 3.0), (7.0, -1.0), (2.0, 1.0), -50.0)

    assert angles == (2.0, -3.0, -2.0, -5.0)
