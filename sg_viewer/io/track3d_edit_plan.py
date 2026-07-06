"""Immutable text edit plans for generated track .3D files.

This module intentionally stays UI-agnostic and only models safe text edits.
Callers can preview a unified diff, validate spans, create a timestamped backup,
and then write an edited file.  The initial workflow is one parsed catalog span at
at time, using :class:`sg_viewer.io.track3d_catalog.Track3DSourceSpan` metadata.
"""

from __future__ import annotations

import difflib
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Protocol


class Track3DEditPlanError(ValueError):
    """Raised when a track .3D edit plan is invalid or cannot be applied."""


class _SourceSpanLike(Protocol):
    start_offset: int | None
    end_offset: int | None
    text: str


@dataclass(frozen=True, order=True)
class Track3DTextEdit:
    """A single immutable replacement against absolute source offsets."""

    start_offset: int
    end_offset: int
    replacement: str
    description: str = "Replace track .3D span"

    @classmethod
    def from_source_span(
        cls,
        span: _SourceSpanLike,
        replacement: str,
        description: str = "Replace parsed track .3D span",
    ) -> "Track3DTextEdit":
        """Create an edit from parsed source-span metadata.

        The catalog parser can return ``None`` offsets when a span cannot be
        mapped back into source text.  Such spans are rejected so destructive
        writes cannot silently target the wrong text.
        """
        if span.start_offset is None or span.end_offset is None:
            raise Track3DEditPlanError("Cannot edit a span without source offsets")
        return cls(
            start_offset=span.start_offset,
            end_offset=span.end_offset,
            replacement=replacement,
            description=description,
        )


def _coerce_edits(edits: Iterable[Track3DTextEdit]) -> tuple[Track3DTextEdit, ...]:
    return tuple(edits)


@dataclass(frozen=True)
class Track3DEditPlan:
    """An immutable collection of text edits for one source .3D file."""

    original_path: Path | str
    edits: tuple[Track3DTextEdit, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "original_path", Path(self.original_path))
        object.__setattr__(self, "edits", _coerce_edits(self.edits))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        validate_non_overlapping_edits(self.edits)

    @classmethod
    def replace_source_span(
        cls,
        original_path: str | Path,
        span: _SourceSpanLike,
        replacement: str,
        description: str = "Replace parsed track .3D span",
        warnings: Iterable[str] = (),
    ) -> "Track3DEditPlan":
        """Build a one-span replacement plan from catalog source metadata."""
        return cls(
            original_path=original_path,
            edits=(Track3DTextEdit.from_source_span(span, replacement, description),),
            warnings=tuple(warnings),
        )

    def apply_to_text(self, original_text: str) -> str:
        """Return edited text, applying replacements from bottom to top."""
        return apply_edits(original_text, self.edits)

    def preview_unified_diff(self, original_text: str | None = None, context: int = 3) -> str:
        """Return unified diff text for this plan without writing anything."""
        if original_text is None:
            with self.original_path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
                original_text = handle.read()
        edited_text = self.apply_to_text(original_text)
        return preview_unified_diff(
            original_text,
            edited_text,
            fromfile=str(self.original_path),
            tofile=f"{self.original_path} (edited)",
            context=context,
        )

    def create_backup(self, timestamp: datetime | None = None) -> Path:
        """Copy the original file to a timestamped backup path."""
        return create_timestamped_backup(self.original_path, timestamp=timestamp)

    def write(self, timestamp: datetime | None = None) -> Path:
        """Create a backup, apply this plan, and write the edited file.

        Returns the backup path.  This function is deliberately separate from UI
        code so tests can cover validation and backup behavior before any
        destructive action is wired into the application.
        """
        with self.original_path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            original_text = handle.read()
        edited_text = self.apply_to_text(original_text)
        backup_path = self.create_backup(timestamp=timestamp)
        with self.original_path.open("w", encoding="utf-8", newline="") as handle:
            handle.write(edited_text)
        return backup_path


def validate_non_overlapping_edits(edits: Iterable[Track3DTextEdit]) -> tuple[Track3DTextEdit, ...]:
    """Validate edit ranges and reject overlaps.

    Adjacent ranges are allowed.  Empty ranges are allowed for insertions, but
    offsets must be non-negative and ``end_offset`` cannot be before
    ``start_offset``.
    """
    ordered = tuple(sorted(_coerce_edits(edits), key=lambda edit: (edit.start_offset, edit.end_offset)))
    previous: Track3DTextEdit | None = None
    for edit in ordered:
        if edit.start_offset < 0 or edit.end_offset < 0:
            raise Track3DEditPlanError("Edit offsets must be non-negative")
        if edit.end_offset < edit.start_offset:
            raise Track3DEditPlanError("Edit end_offset cannot be before start_offset")
        if previous is not None and edit.start_offset < previous.end_offset:
            raise Track3DEditPlanError(
                "Track .3D edits overlap: "
                f"{previous.start_offset}-{previous.end_offset} and "
                f"{edit.start_offset}-{edit.end_offset}"
            )
        previous = edit
    return ordered


def apply_edits(original_text: str, edits: Iterable[Track3DTextEdit]) -> str:
    """Apply edits from highest offset to lowest and return the result."""
    validated = validate_non_overlapping_edits(edits)
    text = original_text
    for edit in sorted(validated, key=lambda item: item.start_offset, reverse=True):
        if edit.end_offset > len(text):
            raise Track3DEditPlanError(
                f"Edit range {edit.start_offset}-{edit.end_offset} exceeds source length {len(text)}"
            )
        text = text[: edit.start_offset] + edit.replacement + text[edit.end_offset :]
    return text


def preview_unified_diff(
    original_text: str,
    edited_text: str,
    fromfile: str = "original",
    tofile: str = "edited",
    context: int = 3,
) -> str:
    """Return a unified diff between original and edited text."""
    return "".join(
        difflib.unified_diff(
            original_text.splitlines(keepends=True),
            edited_text.splitlines(keepends=True),
            fromfile=fromfile,
            tofile=tofile,
            n=context,
        )
    )


def create_timestamped_backup(path: str | Path, timestamp: datetime | None = None) -> Path:
    """Create a timestamped copy next to ``path`` and return its path."""
    source_path = Path(path)
    stamp = (timestamp or datetime.now()).strftime("%Y%m%d_%H%M%S")
    backup_path = source_path.with_suffix(f"{source_path.suffix}.bak_{stamp}")
    counter = 1
    while backup_path.exists():
        backup_path = source_path.with_suffix(f"{source_path.suffix}.bak_{stamp}_{counter}")
        counter += 1
    shutil.copy2(source_path, backup_path)
    return backup_path
