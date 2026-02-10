import math
from types import SimpleNamespace

from sg_viewer.services.preview_painter import _is_long_curve_section


def _curve_section(*, radius: float, arc_degrees: float):
    length = abs(radius) * math.radians(arc_degrees)
    return SimpleNamespace(center=(0.0, 1.0), radius=radius, length=length)


def test_long_curve_section_threshold():
    assert not _is_long_curve_section(_curve_section(radius=100.0, arc_degrees=120.0))
    assert _is_long_curve_section(_curve_section(radius=100.0, arc_degrees=120.1))
