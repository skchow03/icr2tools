import sys
from pathlib import Path
from types import SimpleNamespace

# Provide a minimal numpy stub so imports succeed without the dependency.
sys.modules.setdefault("numpy", SimpleNamespace())

import icr2_core.trk.track_loader as track_loader


class DummyTRK:
    pass


def _touch_dat(track_dir: Path, name: str = "example.dat") -> Path:
    dat_path = track_dir / name
    dat_path.write_bytes(b"dat")
    return dat_path


def test_load_trk_prefers_folder_named_trk(monkeypatch, tmp_path):
    track_dir = tmp_path / "mytrack"
    track_dir.mkdir()
    _touch_dat(track_dir)

    monkeypatch.setattr(
        track_loader, "list_dat_entries", lambda path: [("OTHER.TRK", 0, 0), ("MYTRACK.TRK", 0, 0)]
    )

    selected = {}

    def fake_extract(dat_path, target):
        selected["name"] = target
        return b"trk-bytes"

    monkeypatch.setattr(track_loader, "extract_file_bytes", fake_extract)
    monkeypatch.setattr(track_loader.TRKFile, "from_bytes", classmethod(lambda cls, raw: DummyTRK()))

    result = track_loader.load_trk_from_folder(str(track_dir))

    assert isinstance(result, DummyTRK)
    assert selected["name"] == "MYTRACK.TRK"


def test_load_trk_uses_first_available_entry(monkeypatch, tmp_path):
    track_dir = tmp_path / "another"
    track_dir.mkdir()
    _touch_dat(track_dir, name="different.dat")

    monkeypatch.setattr(track_loader, "list_dat_entries", lambda path: [("FIRST.TRK", 0, 0), ("SECOND.TRK", 0, 0)])

    extracted = {}

    def fake_extract(dat_path, target):
        extracted["name"] = target
        return b"trk-bytes"

    monkeypatch.setattr(track_loader, "extract_file_bytes", fake_extract)
    monkeypatch.setattr(track_loader.TRKFile, "from_bytes", classmethod(lambda cls, raw: DummyTRK()))

    result = track_loader.load_trk_from_folder(str(track_dir))

    assert isinstance(result, DummyTRK)
    assert extracted["name"] == "FIRST.TRK"
