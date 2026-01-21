from __future__ import annotations

from pathlib import Path


def test_sg_preview_independence() -> None:
    preview_root = Path(__file__).resolve().parents[1] / "sg_viewer" / "sg_preview"
    assert preview_root.is_dir(), "sg_preview package is missing"

    forbidden = ["track_viewer", "trk", "TrackPreview"]
    hits: list[str] = []

    for path in preview_root.rglob("*.py"):
        content = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in content:
                hits.append(f"{path}: {token}")

    assert not hits, "Forbidden preview dependencies found:\n" + "\n".join(hits)
