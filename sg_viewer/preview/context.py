from __future__ import annotations

from typing import Protocol, runtime_checkable

Point = tuple[float, float]
Transform = tuple[float, tuple[float, float]]


@runtime_checkable
class PreviewContext(Protocol):
    def current_transform(self, widget_size: tuple[int, int]) -> Transform | None:
        ...

    def begin_drag_transform(self, transform: Transform) -> None:
        ...

    def end_drag_transform(self) -> None:
        ...

    def map_to_track(
        self,
        screen_pos: tuple[float, float] | Point,
        widget_size: tuple[int, int],
        widget_height: int,
        transform: Transform | None = None,
    ) -> Point | None:
        ...

    def set_status(self, text: str) -> None:
        ...

    def set_status_text(self, text: str) -> None:
        ...

    def request_repaint(self) -> None:
        ...

    def request_repaint_throttled(self, min_interval_ms: int = 33) -> None:
        ...

    def refresh_fsections_preview(self) -> bool:
        ...

    def refresh_fsections_preview_lightweight(self) -> bool:
        ...

    def widget_size(self) -> tuple[int, int]:
        ...

    def widget_height(self) -> int:
        ...
