import os
import sys
import types

import pytest

sys.modules.setdefault("numpy", types.ModuleType("numpy"))

from icr2_core.trk import track_loader


class DummyTRKFile:
    from_bytes_call = None
    from_trk_call = None

    @classmethod
    def from_bytes(cls, data):
        cls.from_bytes_call = data
        return "from-bytes"

    @classmethod
    def from_trk(cls, path):
        cls.from_trk_call = path
        return "from-trk"


def test_load_trk_prefers_folder_named_dat(tmp_path, monkeypatch):
    track_dir = tmp_path / "phoenix"
    track_dir.mkdir()
    other_dat = track_dir / "backup.dat"
    other_dat.write_bytes(b"backup")
    phoenix_dat = track_dir / "PHOENIX.DAT"
    phoenix_dat.write_bytes(b"phoenix")

    captured = {}

    def fake_extract_file_bytes(dat_path, target_name):
        captured["dat_path"] = dat_path
        captured["target_name"] = target_name
        return b"trk-bytes"

    monkeypatch.setattr(track_loader, "extract_file_bytes", fake_extract_file_bytes)
    monkeypatch.setattr(track_loader, "TRKFile", DummyTRKFile)

    result = track_loader.load_trk_from_folder(str(track_dir))

    assert result == "from-bytes"
    assert os.path.samefile(captured["dat_path"], phoenix_dat)
    assert captured["target_name"].lower() == "phoenix.trk"
    assert DummyTRKFile.from_bytes_call == b"trk-bytes"


def test_load_trk_falls_back_to_matching_trk(tmp_path, monkeypatch):
    track_dir = tmp_path / "indy"
    track_dir.mkdir()
    other_trk = track_dir / "indy_backup.trk"
    other_trk.write_text("backup")
    indy_trk = track_dir / "INDY.TRK"
    indy_trk.write_text("main")

    monkeypatch.setattr(track_loader, "TRKFile", DummyTRKFile)

    result = track_loader.load_trk_from_folder(str(track_dir))

    assert result == "from-trk"
    assert os.path.samefile(DummyTRKFile.from_trk_call, indy_trk)


def test_load_trk_raises_when_no_matching_files(tmp_path):
    track_dir = tmp_path / "miami"
    track_dir.mkdir()
    (track_dir / "other.dat").write_bytes(b"data")
    (track_dir / "other.trk").write_bytes(b"data")

    with pytest.raises(FileNotFoundError):
        track_loader.load_trk_from_folder(str(track_dir))
