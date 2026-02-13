"""Undo/redo manager for SG Viewer edit commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sg_viewer.model.edit_commands import EditCommand

if TYPE_CHECKING:
    from sg_viewer.model.sg_model import SectionPreview


class EditManager:
    """Execute reversible edit commands and manage undo/redo stacks."""

    def __init__(self) -> None:
        self._undo_stack: list[EditCommand] = []
        self._redo_stack: list[EditCommand] = []

    def execute(self, command: EditCommand) -> list["SectionPreview"]:
        """Execute a command, push it to undo history, and clear redo history."""
        result = command.apply()
        self._undo_stack.append(command)
        self._redo_stack.clear()
        return result

    def undo(self) -> list["SectionPreview"] | None:
        """Undo the latest command and return restored sections when available."""
        if not self._undo_stack:
            return None
        command = self._undo_stack.pop()
        result = command.revert()
        self._redo_stack.append(command)
        return result

    def redo(self) -> list["SectionPreview"] | None:
        """Redo the latest undone command and return reapplied sections when available."""
        if not self._redo_stack:
            return None
        command = self._redo_stack.pop()
        result = command.apply()
        self._undo_stack.append(command)
        return result
