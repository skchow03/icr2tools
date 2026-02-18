import sys
import types
import copy

if "numpy" not in sys.modules:
    sys.modules["numpy"] = types.ModuleType("numpy")

import math

from sg_viewer.geometry.sg_geometry import update_section_geometry
from sg_viewer.model.edit_commands import TrackEditSnapshot
from sg_viewer.model.sg_model import SectionPreview
from sg_viewer.runtime.viewer_runtime_api import ViewerRuntimeApi


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


def test_runtime_api_connect_disconnect_contract_payloads():
    api = ViewerRuntimeApi()
    sections = [_straight(0, (0.0, 0.0), (100.0, 0.0)), _straight(1, (100.0, 0.0), (200.0, 0.0))]

    connected = api.connect_nodes_intent(sections=sections, source=(0, "end"), target=(1, "start"))
    assert connected.updated_sections is not None
    assert connected.changed_indices == [0, 1]
    assert connected.status_messages == []

    disconnected = api.disconnect_node_intent(sections=connected.updated_sections, node=(0, "end"))
    assert disconnected.updated_sections is not None
    assert disconnected.changed_indices == [0, 1]


def test_runtime_api_connection_solver_contract_payloads():
    api = ViewerRuntimeApi()
    sections = [_straight(0, (0.0, 0.0), (100.0, 0.0)), _straight(1, (300.0, 0.0), (400.0, 0.0))]

    solved = api.solve_connection_intent(sections=sections, source=(0, "end"), target=(1, "start"))
    assert solved.updated_sections is None
    assert solved.changed_indices == []
    assert solved.status_messages


def test_runtime_api_move_and_drag_payloads_include_changed_and_last_dragged_indices():
    api = ViewerRuntimeApi()
    s1 = _straight(0, (0.0, 0.0), (100.0, 0.0), nxt=1)
    s2 = _straight(1, (100.0, 0.0), (200.0, 0.0), prev=0)

    moved = api.move_sections_intent(sections=[s1, s2], chain_indices=[0, 1], dx=10.0, dy=5.0)
    assert moved.updated_sections is not None
    assert moved.changed_indices == [0, 1]

    dragged = api.drag_node_intent(
        sections=[s1, s2],
        active_node=(0, "end"),
        track_point=(150.0, 15.0),
        can_drag_node=False,
    )
    assert dragged.updated_sections is not None
    assert dragged.last_dragged_indices == [0, 1]


def test_runtime_api_track_metrics_payload():
    api = ViewerRuntimeApi()
    open_sections = [_straight(0, (0.0, 0.0), (100.0, 0.0))]
    open_metrics = api.track_metrics_intent(open_sections)
    assert open_metrics.status_messages == ["Track Length: Not a closed loop"]

    closed_sections = [
        _straight(0, (0.0, 0.0), (100.0, 0.0), prev=2, nxt=1),
        _straight(1, (100.0, 0.0), (0.0, 100.0), prev=0, nxt=2),
        _straight(2, (0.0, 100.0), (0.0, 0.0), prev=1, nxt=0),
    ]
    closed_metrics = api.track_metrics_intent(closed_sections)
    assert len(closed_metrics.status_messages) == 1
    assert float(closed_metrics.status_messages[0]) > 0.0


def test_runtime_api_unified_history_reverses_mixed_edits_by_time():
    state: dict[str, object] = {
        "sections": [_straight(0, (0.0, 0.0), (100.0, 0.0))],
        "start_finish_dlong": 0.0,
        "fsects": [[{"start": 100.0}]],
        "elevation": {"num_xsects": 1, "xsect_dlats": [0], "header": [0, 0, 0, 0, 1, 1], "sections": [{"alt": [1000], "grade": [100]}]},
    }

    def _snapshot() -> TrackEditSnapshot:
        return TrackEditSnapshot(
            sections=copy.deepcopy(list(state["sections"])),
            start_finish_dlong=state["start_finish_dlong"],
            fsects_by_section=copy.deepcopy(list(state["fsects"])),
            elevation_state=copy.deepcopy(dict(state["elevation"])),
        )

    def _restore(snapshot: TrackEditSnapshot) -> list[SectionPreview]:
        state["sections"] = copy.deepcopy(list(snapshot.sections))
        state["start_finish_dlong"] = snapshot.start_finish_dlong
        state["fsects"] = copy.deepcopy(list(snapshot.fsects_by_section))
        state["elevation"] = copy.deepcopy(dict(snapshot.elevation_state or {}))
        return copy.deepcopy(list(snapshot.sections))

    api = ViewerRuntimeApi(snapshot_provider=_snapshot, restore_snapshot=_restore)

    # geometry commit
    before = list(state["sections"])
    after = [_straight(0, (10.0, 0.0), (110.0, 0.0))]
    payload = api.commit_sections(before=before, after=after)
    state["sections"] = list(payload.updated_sections or after)

    # elevation commit
    elev_before = _snapshot()
    state["elevation"] = {"num_xsects": 1, "xsect_dlats": [0], "header": [0, 0, 0, 0, 1, 1], "sections": [{"alt": [2000], "grade": [100]}]}
    api.commit_snapshot(before=elev_before, after=_snapshot(), restore_snapshot=_restore)

    # fsect commit
    fsect_before = _snapshot()
    state["fsects"] = [[{"start": 150.0}]]
    api.commit_snapshot(before=fsect_before, after=_snapshot(), restore_snapshot=_restore)

    assert state["fsects"][0][0]["start"] == 150.0
    assert state["elevation"]["sections"][0]["alt"][0] == 2000
    assert state["sections"][0].start == (10.0, 0.0)

    assert api.undo().updated_sections is not None
    assert state["fsects"][0][0]["start"] == 100.0

    assert api.undo().updated_sections is not None
    assert state["elevation"]["sections"][0]["alt"][0] == 1000

    assert api.undo().updated_sections is not None
    assert state["sections"][0].start == (0.0, 0.0)
