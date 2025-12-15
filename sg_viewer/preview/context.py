from __future__ import annotations

from typing import Protocol, runtime_checkable

Point = tuple[float, float]
Transform = tuple[float, tuple[float, float]]


@runtime_checkable
class PreviewContext(Protocol):
    def current_transform(self, widget_size: tuple[int, int]) -> Transform | None:
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

    def request_repaint(self) -> None:
        ...

    def widget_size(self) -> tuple[int, int]:
        ...

    def widget_height(self) -> int:
        ...
