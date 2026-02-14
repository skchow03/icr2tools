from sg_viewer.services import export_service


class _FakeSGFile:
    def __init__(self) -> None:
        self.sections_output = None
        self.header_output = None

    def output_sg_sections(self, output_path: str) -> None:
        self.sections_output = output_path

    def output_sg_header_xsects(self, output_path: str) -> None:
        self.header_output = output_path


class _FakeSGClass:
    @staticmethod
    def from_sg(path: str):
        _FakeSGClass.loaded_path = path
        return _FakeSGClass.fake


def test_export_sg_to_csv_uses_in_process_conversion(monkeypatch, tmp_path):
    sg_path = tmp_path / "track.sg"
    sg_path.write_text("dummy", encoding="utf-8")

    _FakeSGClass.fake = _FakeSGFile()
    _FakeSGClass.loaded_path = None

    monkeypatch.setattr(export_service, "_load_sg_class", lambda: _FakeSGClass)

    result = export_service.export_sg_to_csv(sg_path=sg_path)

    assert result.success is True
    assert _FakeSGClass.loaded_path == str(sg_path)
    assert _FakeSGClass.fake.sections_output == f"{sg_path}_sects.csv"
    assert _FakeSGClass.fake.header_output == f"{sg_path}_header_xsects.csv"


def test_export_sg_to_trk_writes_target_path(monkeypatch, tmp_path):
    sg_path = tmp_path / "track.sg"
    trk_path = tmp_path / "track.trk"

    calls = {}

    class _FakeTRKClass:
        @staticmethod
        def from_sg(path: str):
            calls["from_sg"] = path
            return object()

    def _write_trk(trk_obj, out_path: str):
        calls["write_trk"] = out_path
        trk_path.write_bytes(b"TRK")

    monkeypatch.setattr(
        export_service,
        "_load_trk_export_dependencies",
        lambda: (_FakeTRKClass, _write_trk),
    )

    result = export_service.export_sg_to_trk(sg_path=sg_path, trk_path=trk_path)

    assert result.success is True
    assert calls["from_sg"] == str(sg_path)
    assert calls["write_trk"] == str(trk_path)
    assert trk_path.exists()
