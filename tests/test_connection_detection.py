from sg_viewer.preview.connection_detection import find_unconnected_node_target
from sg_viewer.model.sg_model import SectionPreview


def _make_section(idx: int, start, end) -> SectionPreview:
    return SectionPreview(
        section_id=idx,
        type_name="straight",
        previous_id=-1,
        next_id=-1,
        start=start,
        end=end,
        start_dlong=0.0,
        length=0.0,
        center=None,
        sang1=None,
        sang2=None,
        eang1=None,
        eang2=None,
        radius=None,
        start_heading=None,
        end_heading=None,
        polyline=[],
    )


def test_unconnected_target_found_when_dragged_endpoint_overlaps():
    sections = [
        _make_section(0, start=(0.0, 0.0), end=(1.0, 0.0)),
        _make_section(1, start=(2.0, 0.0), end=(3.0, 0.0)),
    ]

    dragged_key = (0, "end")
    dragged_pos = (2.0, 0.0)  # Dragged onto the start of section 1

    target = find_unconnected_node_target(
        dragged_key=dragged_key,
        dragged_pos=dragged_pos,
        sections=sections,
        snap_radius=1.5,
    )

    assert target == (1, "start")


def test_target_found_even_when_dragged_node_marked_connected():
    """Dragging away from a still-marked connection should still snap."""

    connected_curve = SectionPreview(
        section_id=0,
        type_name="curve",
        previous_id=-1,
        next_id=2,  # still marked connected
        start=(0.0, 0.0),
        end=(1.0, 0.0),
        start_dlong=0.0,
        length=0.0,
        center=None,
        sang1=None,
        sang2=None,
        eang1=None,
        eang2=None,
        radius=None,
        start_heading=None,
        end_heading=None,
        polyline=[],
    )
    target_straight = _make_section(1, start=(2.0, 0.0), end=(3.0, 0.0))

    dragged_key = (0, "end")
    dragged_pos = (2.0, 0.0)

    target = find_unconnected_node_target(
        dragged_key=dragged_key,
        dragged_pos=dragged_pos,
        sections=[connected_curve, target_straight],
        snap_radius=1.5,
    )

    assert target == (1, "start")
