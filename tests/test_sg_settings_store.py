import json

from sg_viewer.services.sg_settings_store import SGSettingsStore


def test_set_sunny_palette_stores_relative_path(tmp_path):
    sg_path = tmp_path / "tracks" / "test.sg"
    sg_path.parent.mkdir(parents=True, exist_ok=True)
    sg_path.write_bytes(b"")
    palette_path = tmp_path / "tracks" / "palettes" / "SUNNY.PCX"
    palette_path.parent.mkdir(parents=True, exist_ok=True)
    palette_path.write_bytes(b"")

    store = SGSettingsStore()
    store.set_sunny_palette(sg_path, palette_path)

    payload = json.loads(sg_path.with_suffix(".sgc").read_text(encoding="utf-8"))
    assert payload["sunny_palette"] == "palettes/SUNNY.PCX"


def test_set_sunny_palette_removes_embedded_palette_colors(tmp_path):
    sg_path = tmp_path / "tracks" / "test.sg"
    sg_path.parent.mkdir(parents=True, exist_ok=True)
    sg_path.write_bytes(b"")

    settings_path = sg_path.with_suffix(".sgc")
    settings_path.write_text(
        '{"sunny_palette": "SUNNY.PCX", "sunny_palette_colors": [[0, 0, 0]]}',
        encoding="utf-8",
    )

    store = SGSettingsStore()
    store.set_sunny_palette(sg_path, tmp_path / "tracks" / "SUNNY.PCX")

    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "sunny_palette_colors" not in payload
