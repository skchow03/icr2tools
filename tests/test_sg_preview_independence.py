from __future__ import annotations

from pathlib import Path


def test_sg_preview_removed() -> None:
    preview_root = Path(__file__).resolve().parents[1] / "sg_viewer" / "sg_preview"
    assert not preview_root.exists(), "sg_preview package should be removed"


def test_no_sg_preview_imports() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    forbidden = "sg_viewer.sg_preview"
    hits: list[str] = []

    for path in repo_root.rglob("*.py"):
        if path == Path(__file__):
            continue
        content = path.read_text(encoding="utf-8")
        if forbidden in content:
            hits.append(str(path))

    assert not hits, "Found imports referencing sg_preview:\n" + "\n".join(hits)
