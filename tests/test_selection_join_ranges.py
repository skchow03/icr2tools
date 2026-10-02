from __future__ import annotations

import math
from types import SimpleNamespace

from sg_viewer.model.selection import SelectionManager


def _sections_with_join(second_start):
    return [
        SimpleNamespace(polyline=[(0.0, 0.0), (10.0, 0.0)],
                        start_dlong=0.0, length=10.0),
        SimpleNamespace(polyline=[second_start, (20.0, 0.0)],
                        start_dlong=10.0, length=10.0),
    ]


def test_subsection_highlighting_preserves_nonmatching_join():
    # STPETE24 has a one-unit X/Y gap between sections 23 and 24.
    sections = _sections_with_join((11.0, 1.0))
    dlongs = [0.0, 10.0, 10.0 + math.sqrt(2.0),
              10.0 + math.sqrt(2.0) + math.sqrt(82.0)]
    manager = SelectionManager()
    manager.update_context(sections, dlongs[-1], None, dlongs)
    assert manager._sampled_centerline == [
        (0.0, 0.0), (10.0, 0.0), (11.0, 1.0), (20.0, 0.0)
    ]

    manager.set_selected_dlong_range(2.0, 8.0)
    assert manager.selected_section_points == [(2.0, 0.0), (8.0, 0.0)]
    manager.set_selected_dlong_range(dlongs[2], dlongs[-1])
    assert manager.selected_section_points == [(11.0, 1.0), (20.0, 0.0)]

    # reset() must reconstruct the same samples as update_context().
    manager.reset(sections, dlongs[-1], None, dlongs)
    manager.set_selected_dlong_range(2.0, 8.0)
    assert manager.selected_section_points == [(2.0, 0.0), (8.0, 0.0)]


def test_subsection_highlighting_deduplicates_exact_join():
    sections = _sections_with_join((10.0, 0.0))
    manager = SelectionManager()
    manager.update_context(sections, 20.0, None, [0.0, 10.0, 20.0])
    assert manager._sampled_centerline == [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)]
    manager.set_selected_dlong_range(5.0, 15.0)
    assert manager.selected_section_points == [
        (5.0, 0.0), (10.0, 0.0), (15.0, 0.0)
    ]
