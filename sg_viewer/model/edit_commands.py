"""Command objects for section edit operations in SG Viewer."""

from __future__ import annotations

from abc import ABC, abstractmethod
import copy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from sg_viewer.model.sg_model import SectionPreview


class EditCommand(ABC):
    """Base class for reversible preview edit commands."""

    @abstractmethod
    def apply(self) -> list["SectionPreview"]:
        """Apply the command and return the updated section list."""

    @abstractmethod
    def revert(self) -> list["SectionPreview"]:
        """Revert the command and return the prior section list."""


class ReplaceSectionsCommand(EditCommand):
    """Replace the complete section collection with a new version."""

    def __init__(
        self,
        before: list["SectionPreview"],
        after: list["SectionPreview"],
    ) -> None:
        self._before = copy.deepcopy(before)
        self._after = copy.deepcopy(after)

    def apply(self) -> list["SectionPreview"]:
        """Return the replacement section list for command execution."""
        return copy.deepcopy(self._after)

    def revert(self) -> list["SectionPreview"]:
        """Return the original section list for undo."""
        return copy.deepcopy(self._before)


@dataclass(frozen=True)
class TrackEditSnapshot:
    """Complete mutable track-edit state used for unified undo/redo."""

    sections: list["SectionPreview"]
    start_finish_dlong: float | None
    fsects_by_section: list[list[object]]
    elevation_state: dict[str, object] | None


class ReplaceTrackSnapshotCommand(EditCommand):
    """Restore full track snapshots for undo/redo across all SG edit types."""

    def __init__(
        self,
        *,
        before: TrackEditSnapshot,
        after: TrackEditSnapshot,
        restore_snapshot: Callable[[TrackEditSnapshot], list["SectionPreview"]],
    ) -> None:
        self._before = copy.deepcopy(before)
        self._after = copy.deepcopy(after)
        self._restore_snapshot = restore_snapshot
        self._executed = False

    def apply(self) -> list["SectionPreview"]:
        if self._executed:
            return self._restore_snapshot(copy.deepcopy(self._after))
        self._executed = True
        return copy.deepcopy(self._after.sections)

    def revert(self) -> list["SectionPreview"]:
        return self._restore_snapshot(copy.deepcopy(self._before))
