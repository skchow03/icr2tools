import pytest

pytest.importorskip("PyQt5")

from sg_viewer.io.track3d_parser import Track3DObjectList
from sg_viewer.ui.controllers.features.trackside_objects_controller import (
    TracksideObjectsController,
)


def _controller() -> TracksideObjectsController:
    return object.__new__(TracksideObjectsController)


def _lists():
    entries = [
        Track3DObjectList("L", 0, 0, []),
        Track3DObjectList("L", 1, 0, []),
    ]
    return entries, {
        (entry.side, entry.section, entry.sub_index): entry for entry in entries
    }


def test_angle_sweep_extends_assignment_past_section_boundary() -> None:
    controller = _controller()
    entries, by_key = _lists()
    ranges = {(0, 0): (0.0, 100.0), (1, 0): (100.0, 200.0)}

    # Nine units beyond section 0 and ten units left of centerline falls
    # inside a 45-degree sweep projected forward from that section's end.
    targets = controller._object_lists_for_position(
        by_key, ranges, 109.0, 10.0, 1000.0, 45.0, 0.0
    )

    assert targets == [entries[0]]


def test_nearby_distance_can_assign_tso_to_multiple_object_lists() -> None:
    controller = _controller()
    entries, by_key = _lists()
    ranges = {(0, 0): (0.0, 100.0), (1, 0): (100.0, 200.0)}

    targets = controller._object_lists_for_position(
        by_key, ranges, 100.0, 6.0, 1000.0, 0.0, 10.0
    )

    assert targets == entries


def test_default_assignment_remains_exclusive() -> None:
    controller = _controller()
    entries, by_key = _lists()
    ranges = {(0, 0): (0.0, 100.0), (1, 0): (100.0, 200.0)}

    targets = controller._object_lists_for_position(
        by_key, ranges, 150.0, 10.0, 1000.0
    )

    assert targets == [entries[1]]
