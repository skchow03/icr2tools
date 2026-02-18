import sys
import types

if "numpy" not in sys.modules:
    sys.modules["numpy"] = types.ModuleType("numpy")

import math

from sg_viewer.geometry.sg_geometry import update_section_geometry
from sg_viewer.model.sg_model import SectionPreview
from sg_viewer.runtime.preview_geometry_service import (
    ConnectionSolveRequest,
    ConnectNodesRequest,
    NodeDisconnectRequest,
    NodeDragRequest,
    PreviewGeometryService,
)


def _straight(section_id: int, start, end, prev=-1, nxt=-1):
    return update_section_geometry(
        SectionPreview(
            section_id=section_id,
            source_section_id=section_id,
            type_name="straight",
            previous_id=prev,
            next_id=nxt,
            start=start,
            end=end,
            start_dlong=0.0,
            length=math.hypot(end[0] - start[0], end[1] - start[1]),
            center=None,
            sang1=None,
            sang2=None,
            eang1=None,
            eang2=None,
            radius=None,
            start_heading=None,
            end_heading=None,
            polyline=[start, end],
        )
    )


def _curve(section_id: int, start, end, center, radius, prev=-1, nxt=-1):
    return update_section_geometry(
        SectionPreview(
            section_id=section_id,
            source_section_id=section_id,
            type_name="curve",
            previous_id=prev,
            next_id=nxt,
            start=start,
            end=end,
            start_dlong=0.0,
            length=abs(radius) * math.pi / 2,
            center=center,
            sang1=1.0,
            sang2=0.0,
            eang1=0.0,
            eang2=1.0,
            radius=radius,
            start_heading=(1.0, 0.0),
            end_heading=(0.0, 1.0),
            polyline=[start, end],
        )
    )


def test_connect_and_disconnect_nodes_round_trip():
    service = PreviewGeometryService()
    sections = [_straight(0, (0.0, 0.0), (100.0, 0.0)), _straight(1, (100.0, 0.0), (200.0, 0.0))]

    connected = service.connect_nodes(ConnectNodesRequest(sections, (0, "end"), (1, "start")))
    assert connected.sections is not None
    assert connected.sections[0].next_id == 1
    assert connected.sections[1].previous_id == 0

    disconnected = service.disconnect_node(NodeDisconnectRequest(connected.sections, (0, "end")))
    assert disconnected.sections is not None
    assert disconnected.sections[0].next_id == -1
    assert disconnected.sections[1].previous_id == -1


def test_shared_straight_node_constraint_applies_projection_and_updates_both_segments():
    service = PreviewGeometryService()
    s1 = _straight(0, (0.0, 0.0), (100.0, 0.0), nxt=1)
    s2 = _straight(1, (100.0, 0.0), (200.0, 0.0), prev=0)
    response = service.update_dragged_section(
        NodeDragRequest(
            sections=[s1, s2],
            active_node=(0, "end"),
            track_point=(150.0, 20.0),
            can_drag_node=False,
        )
    )
    assert response.sections is not None
    assert response.sections[0].end == response.sections[1].start
    assert response.last_dragged_indices == [0, 1]


def test_closed_loop_transition_canonicalizes_when_loop_is_completed():
    service = PreviewGeometryService()
    old_sections = [
        _straight(0, (0.0, 0.0), (100.0, 0.0), prev=2, nxt=1),
        _straight(1, (100.0, 0.0), (100.0, 100.0), prev=0, nxt=2),
        _straight(2, (100.0, 100.0), (0.0, 0.0), prev=1, nxt=-1),
    ]
    new_sections = [
        _straight(0, (0.0, 0.0), (100.0, 0.0), prev=2, nxt=1),
        _straight(1, (100.0, 0.0), (100.0, 100.0), prev=0, nxt=2),
        _straight(2, (100.0, 100.0), (0.0, 0.0), prev=1, nxt=0),
    ]
    response = service.apply_closure_transition(old_sections, new_sections, [2, 0])
    assert response.closed_loop_transition is True
    assert response.status_message == "Closed loop detected — track direction fixed"
    assert response.sections[0].section_id == 0
    assert response.sections[0].next_id == 1


def test_solve_connection_allows_straight_to_straight_when_headings_match_and_join_is_straight():
    service = PreviewGeometryService()
    dragged = _straight(0, (0.0, 0.0), (10.0, 0.0))
    target = _straight(1, (20.0, 0.0), (30.0, 0.0))

    solved = service.solve_connection(
        ConnectionSolveRequest(
            sections=[dragged, target],
            source=(0, "end"),
            target=(1, "start"),
        )
    )

    assert solved.sections is not None
    assert solved.sections[0].next_id == 1
    assert solved.sections[1].previous_id == 0
    assert solved.status_message == "Straight → straight connected"


def test_solve_connection_rejects_straight_to_straight_when_join_would_not_be_straight():
    service = PreviewGeometryService()
    dragged = _straight(0, (0.0, 0.0), (10.0, 0.0))
    target = _straight(1, (20.0, 1.0), (30.0, 1.0))

    solved = service.solve_connection(
        ConnectionSolveRequest(
            sections=[dragged, target],
            source=(0, "end"),
            target=(1, "start"),
        )
    )

    assert solved.sections is None
    assert solved.status_message == (
        "Cannot connect straight → straight unless endpoint headings match and the connection is perfectly straight."
    )
