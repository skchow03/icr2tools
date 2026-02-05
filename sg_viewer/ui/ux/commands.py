from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EndType = Literal["start", "end"]


@dataclass(frozen=True)
class UXCommand:
    """Base class for user intent commands."""


@dataclass(frozen=True)
class ConnectSectionsCommand(UXCommand):
    from_section: int
    from_end: EndType
    to_section: int
    to_end: EndType


@dataclass(frozen=True)
class DisconnectSectionEndCommand(UXCommand):
    section: int
    end: EndType


@dataclass(frozen=True)
class DragNodeCommand(UXCommand):
    section: int
    end: EndType
    new_position: tuple[float, float]
