# sg_viewer/preview/edit_interactions.py

from typing import Optional, Tuple

from sg_viewer.preview.connection_detection import find_unconnected_node_target
from sg_viewer.model.sg_model import SectionPreview

Point = Tuple[float, float]


class EndpointDragInteraction:
    def __init__(self, controller) -> None:
        self._controller = controller
        self._dragged_key: Optional[tuple[int, str]] = None

    @property
    def active(self) -> bool:
        return self._dragged_key is not None

    def begin_drag(self, key: tuple[int, str]) -> None:
        self._dragged_key = key

    def cancel(self) -> None:
        self._dragged_key = None
        self._controller.clear_connection_target()

    def handle_move(self, pos: Point, context) -> bool:
        if self._dragged_key is None:
            return False

        sections, _ = self._controller.preview.get_section_set()

        target = find_unconnected_node_target(
            dragged_key=self._dragged_key,
            dragged_pos=context.map_to_track(pos),
            sections=sections,
            snap_radius=context.snap_radius,
        )

        self._controller.set_connection_target(target)
        return True
