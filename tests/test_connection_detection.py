from sg_viewer.preview.connection_detection import find_unconnected_node_target
from sg_viewer.models.sg_model import SectionPreview


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
