"""Tests for SG Viewer edit command execution and undo/redo behavior."""

from sg_viewer.model.edit_commands import ReplaceSectionsCommand
from sg_viewer.model.edit_manager import EditManager


def test_execute_command_updates_sections() -> None:
    manager = EditManager()
    before = ["a", "b"]
    after = ["a", "c"]

    applied = manager.execute(ReplaceSectionsCommand(before=before, after=after))

    assert applied == after


def test_undo_restores_original_sections() -> None:
    manager = EditManager()
    before = ["section-1"]
    after = ["section-2"]

    manager.execute(ReplaceSectionsCommand(before=before, after=after))
    undone = manager.undo()

    assert undone == before


def test_redo_reapplies_sections() -> None:
    manager = EditManager()
    before = ["old"]
    after = ["new"]

    manager.execute(ReplaceSectionsCommand(before=before, after=after))
    manager.undo()
    redone = manager.redo()

    assert redone == after
