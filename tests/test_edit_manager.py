"""Tests for SG Viewer edit command execution, validation, and undo/redo behavior."""

from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from sg_viewer.model.edit_commands import EditCommand, ReplaceSectionsCommand
from sg_viewer.model.edit_manager import EditManager
from sg_viewer.model.invariants import InvariantError


@dataclass(frozen=True)
class _Section:
    section_id: int
    source_section_id: int
    type_name: str
    previous_id: int
    next_id: int
    start: tuple[float, float]
    end: tuple[float, float]
    start_dlong: float
    length: float
    center: tuple[float, float] | None
    sang1: float | None
    sang2: float | None
    eang1: float | None
    eang2: float | None
    radius: float | None
    start_heading: tuple[float, float] | None
    end_heading: tuple[float, float] | None
    polyline: list[tuple[float, float]]


def _make_section(section_id: int, previous_id: int, next_id: int) -> _Section:
    return _Section(
        section_id=section_id,
        source_section_id=section_id,
        type_name="straight",
        previous_id=previous_id,
        next_id=next_id,
        start=(float(section_id), 0.0),
        end=(float(section_id + 1), 0.0),
        start_dlong=float(section_id),
        length=1.0,
        center=None,
        sang1=None,
        sang2=None,
        eang1=None,
        eang2=None,
        radius=None,
        start_heading=(1.0, 0.0),
        end_heading=(1.0, 0.0),
        polyline=[(float(section_id), 0.0), (float(section_id + 1), 0.0)],
    )


def _valid_sections() -> list[_Section]:
    return [_make_section(0, -1, 1), _make_section(1, 0, -1)]


def _invalid_sections() -> list[_Section]:
    sections = _valid_sections()
    sections[1] = replace(sections[1], section_id=0)
    return sections


class _StatefulCommand(EditCommand):
    def __init__(self, state: list[_Section], after: list[_Section]) -> None:
        self._state = state
        self._before = list(state)
        self._after = after

    def apply(self) -> list[_Section]:
        self._state[:] = self._after
        return list(self._state)

    def revert(self) -> list[_Section]:
        self._state[:] = self._before
        return list(self._state)


def test_execute_command_updates_sections() -> None:
    manager = EditManager()
    before = _valid_sections()
    after = [replace(before[0], end=(2.0, 0.0), polyline=[before[0].start, (2.0, 0.0)]), before[1]]

    applied = manager.execute(ReplaceSectionsCommand(before=before, after=after))

    assert applied == after


def test_undo_restores_original_sections() -> None:
    manager = EditManager()
    before = _valid_sections()
    after = [replace(before[0], end=(2.0, 0.0), polyline=[before[0].start, (2.0, 0.0)]), before[1]]

    manager.execute(ReplaceSectionsCommand(before=before, after=after))
    undone = manager.undo()

    assert undone == before


def test_redo_reapplies_sections() -> None:
    manager = EditManager()
    before = _valid_sections()
    after = [replace(before[0], end=(2.0, 0.0), polyline=[before[0].start, (2.0, 0.0)]), before[1]]

    manager.execute(ReplaceSectionsCommand(before=before, after=after))
    manager.undo()
    redone = manager.redo()

    assert redone == after


def test_invalid_sequence_raises_invariant_error() -> None:
    manager = EditManager()

    with pytest.raises(InvariantError):
        manager.execute(ReplaceSectionsCommand(before=_valid_sections(), after=_invalid_sections()))


def test_failed_edit_is_rolled_back() -> None:
    manager = EditManager()
    state = _valid_sections()
    command = _StatefulCommand(state=state, after=_invalid_sections())

    with pytest.raises(InvariantError):
        manager.execute(command)

    assert state == _valid_sections()
    assert manager.undo() is None
def test_canonicalize_closed_loop_reindexes_section_ids() -> None:
    pytest.importorskip("numpy")
    from sg_viewer.geometry.canonicalize import canonicalize_closed_loop
    from sg_viewer.model.invariants import validate_sections

    # Simulate a valid closed loop topology where section_id values no longer
    # match list indices after section insertion/reordering.
    sections = [
        _make_section(0, 2, 1),
        _make_section(1, 0, 2),
        _make_section(3, 1, 0),
    ]

    canonical = canonicalize_closed_loop(sections, start_idx=0)

    assert [s.section_id for s in canonical] == [0, 1, 2]
    validate_sections(canonical)

