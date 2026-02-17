import sys
import types

if "numpy" not in sys.modules:
    sys.modules["numpy"] = types.ModuleType("numpy")

import math

from sg_viewer.geometry.sg_geometry import update_section_geometry
from sg_viewer.model.sg_model import SectionPreview
from sg_viewer.runtime.preview_geometry_service import NodeDragRequest, PreviewGeometryService


def _make_curve_section(
    *,
    section_id: int,
    start_angle: float,
    end_angle: float,
    center: tuple[float, float],
    radius: float,
    previous_id: int,
    next_id: int,
) -> SectionPreview:
    cx, cy = center
    start = (cx + math.cos(start_angle) * radius, cy + math.sin(start_angle) * radius)
    end = (cx + math.cos(end_angle) * radius, cy + math.sin(end_angle) * radius)

    def _tangent(angle: float) -> tuple[float, float]:
        return (-math.sin(angle), math.cos(angle))

    start_heading = _tangent(start_angle)
    end_heading = _tangent(end_angle)

    return update_section_geometry(
        SectionPreview(
            section_id=section_id,
            source_section_id=section_id,
            type_name="curve",
            previous_id=previous_id,
            next_id=next_id,
            start=start,
            end=end,
            start_dlong=0.0,
            length=abs(end_angle - start_angle) * abs(radius),
            center=center,
            sang1=start_heading[0],
            sang2=start_heading[1],
            eang1=end_heading[0],
            eang2=end_heading[1],
            radius=radius,
            start_heading=start_heading,
            end_heading=end_heading,
            polyline=[start, end],
        )
    )


def test_shared_curve_node_drag_constrains_to_arc():
    center = (0.0, 0.0)
    radius = 100.0
    s1 = _make_curve_section(
        section_id=0,
        start_angle=0.0,
        end_angle=math.pi / 2,
        center=center,
        radius=radius,
        previous_id=-1,
        next_id=1,
    )
    s2 = _make_curve_section(
        section_id=1,
        start_angle=math.pi / 2,
        end_angle=math.pi,
        center=center,
        radius=radius,
        previous_id=0,
        next_id=-1,
    )

    target_angle = math.radians(135.0)
    track_point = (
        center[0] + math.cos(target_angle) * radius,
        center[1] + math.sin(target_angle) * radius,
    )

    response = PreviewGeometryService().update_dragged_section(
        NodeDragRequest(
            sections=[s1, s2],
            active_node=(0, "end"),
            track_point=track_point,
            can_drag_node=False,
        )
    )
    assert response.sections is not None

    updated = response.sections
    shared_point = updated[0].end
    assert math.isclose(shared_point[0], track_point[0], abs_tol=1e-6)
    assert math.isclose(shared_point[1], track_point[1], abs_tol=1e-6)
    assert shared_point == updated[1].start
