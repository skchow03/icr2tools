from dataclasses import FrozenInstanceError
from datetime import datetime
from pathlib import Path

import pytest

from sg_viewer.io.track3d_catalog import parse_track3d_catalog
from sg_viewer.io.track3d_edit_plan import (
    Track3DEditPlan,
    Track3DEditPlanError,
    Track3DTextEdit,
    apply_edits,
    create_timestamped_backup,
    preview_unified_diff,
    validate_non_overlapping_edits,
)


def test_edit_model_is_immutable():
    edit = Track3DTextEdit(0, 1, "x", "replace")

    with pytest.raises(FrozenInstanceError):
        edit.replacement = "y"  # type: ignore[misc]


def test_validate_non_overlapping_edits_allows_adjacent_ranges():
    edits = (Track3DTextEdit(4, 6, "BB"), Track3DTextEdit(0, 4, "AAAA"))

    assert validate_non_overlapping_edits(edits) == (
        Track3DTextEdit(0, 4, "AAAA"),
        Track3DTextEdit(4, 6, "BB"),
    )


def test_validate_non_overlapping_edits_rejects_overlap():
    edits = (Track3DTextEdit(0, 5, "first"), Track3DTextEdit(4, 8, "second"))

    with pytest.raises(Track3DEditPlanError, match="overlap"):
        validate_non_overlapping_edits(edits)


def test_apply_edits_uses_bottom_to_top_offset_order():
    original = "0123456789"
    edits = (Track3DTextEdit(2, 4, "ab"), Track3DTextEdit(6, 8, "cd"))

    assert apply_edits(original, edits) == "01ab45cd89"


def test_preview_unified_diff_text():
    diff = preview_unified_diff("a\nb\n", "a\nc\n", fromfile="old.3d", tofile="new.3d")

    assert "--- old.3d" in diff
    assert "+++ new.3d" in diff
    assert "-b\n" in diff
    assert "+c\n" in diff


def test_create_timestamped_backup_copies_original(tmp_path: Path):
    path = tmp_path / "track.3d"
    path.write_text("original\n", encoding="utf-8")

    backup = create_timestamped_backup(path, datetime(2026, 7, 6, 1, 2, 3))

    assert backup == tmp_path / "track.3d.bak_20260706_010203"
    assert backup.read_text(encoding="utf-8") == "original\n"


def test_replace_one_parsed_span_from_catalog_metadata(tmp_path: Path):
    path = tmp_path / "track.3d"
    path.write_text(
        '__TSO1: DYNAMIC 1, 2, 3, 4, EXTERN "tree";\n'
        "ObjectList_L12_0: LIST { __TSO1 };\n",
        encoding="utf-8",
    )
    catalog = parse_track3d_catalog(path)
    replacement = "ObjectList_L12_0: LIST { __TSO1, __TSO2 };"

    plan = Track3DEditPlan.replace_source_span(
        path,
        catalog.object_lists["ObjectList_L12_0"].span,
        replacement,
        "Add TSO2 to object list",
    )

    assert plan.apply_to_text(path.read_text(encoding="utf-8")) == (
        '__TSO1: DYNAMIC 1, 2, 3, 4, EXTERN "tree";\n'
        "ObjectList_L12_0: LIST { __TSO1, __TSO2 };\n"
    )


def test_write_preserves_existing_newlines_around_replacement(tmp_path: Path):
    path = tmp_path / "track.3d"
    original = "alpha\r\nbeta\r\ngamma\r\n"
    path.write_text(original, encoding="utf-8", newline="")
    start = original.index("beta")
    plan = Track3DEditPlan(path, (Track3DTextEdit(start, start + len("beta"), "BETA"),))

    backup = plan.write(timestamp=datetime(2026, 7, 6, 1, 2, 3))

    assert path.open("r", encoding="utf-8", newline="").read() == "alpha\r\nBETA\r\ngamma\r\n"
    assert backup.open("r", encoding="utf-8", newline="").read() == original
