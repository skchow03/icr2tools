"""Command objects for section edit operations in SG Viewer."""

from __future__ import annotations

from abc import ABC, abstractmethod
import copy
from typing import TYPE_CHECKING

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
