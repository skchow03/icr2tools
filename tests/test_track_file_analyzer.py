import struct

from sg_viewer.services.track_file_analyzer import (
    REQUIRED_TRACK_FILES,
    analyze_track_folder,
)


def _write_3do(path, *, mips=(), pmps=(), children=()):
    def field(name):
        return name.encode("latin1")[:8].ljust(8, b"\0")

    path.write_bytes(
        b"\0" * 8
        + struct.pack("<III", len(mips), len(pmps), len(children))
        + b"".join(field(name) for name in (*mips, *pmps, *children))
    )


def _write_required_files(folder):
    for template in REQUIRED_TRACK_FILES:
        path = folder / template.format(track=folder.name)
        if not path.exists():
            path.write_bytes(b"")


def test_analyzer_recurses_assets_case_insensitively_and_reports_unused_mips(tmp_path):
    folder = tmp_path / "Laguna"
    folder.mkdir()
    _write_required_files(folder)
    _write_3do(
        folder / "Laguna.3do",
        mips=("road",),
        pmps=("crowd",),
        children=("bridge",),
    )
    _write_3do(folder / "bridge.3DO", mips=("metal",))
    _write_3do(folder / "sky.3do")
    _write_3do(folder / "horiz.3do")
    (folder / "road.MIP").write_bytes(b"\0" * 8 + struct.pack("<II", 64, 32))
    (folder / "metal.mip").write_bytes(b"\0" * 8 + struct.pack("<II", 16, 8))
    (folder / "crowd.pmp").write_bytes(b"pmp")
    (folder / "unused.mip").write_bytes(b"unused")

    result = analyze_track_folder(folder)

    assert result.is_complete
    assert {item.name.casefold() for item in result.three_do_files} == {
        "laguna.3do", "bridge.3do", "sky.3do", "horiz.3do"
    }
    road = next(item for item in result.mip_files if item.name.casefold() == "road.mip")
    assert (road.width, road.height) == (64, 32)
    assert result.unused_mip_files == ("unused.mip",)


def test_analyzer_marks_required_and_referenced_files_missing(tmp_path):
    folder = tmp_path / "missing"
    folder.mkdir()
    _write_3do(folder / "missing.3do", mips=("absent",))

    result = analyze_track_folder(folder)

    assert not result.is_complete
    assert "missing.trk" in result.required_missing
    assert next(item for item in result.mip_files if item.name == "absent.mip").missing
    report = result.format_report()
    assert "Completeness: INCOMPLETE" in report
    assert "[MISSING] absent.mip" in report
