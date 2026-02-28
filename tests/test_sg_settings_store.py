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


def test_tsd_objects_round_trip_without_overwriting_files(tmp_path):
    sg_path = tmp_path / "tracks" / "test.sg"
    sg_path.parent.mkdir(parents=True, exist_ok=True)
    sg_path.write_bytes(b"")

    store = SGSettingsStore()
    tsd_file = sg_path.parent / "base.tsd"
    tsd_file.write_text("", encoding="utf-8")
    store.set_tsd_files(sg_path, [tsd_file], 0)
    store.set_tsd_objects(
        sg_path,
        [
            {
                "type": "zebra_crossing",
                "name": "Crossing A",
                "start_dlong": 100,
                "center_dlat": 0,
                "stripe_count": 4,
                "stripe_width_500ths": 3000,
                "stripe_length_500ths": 20000,
                "stripe_spacing_500ths": 2000,
                "color_index": 36,
                "command": "Detail",
            }
        ],
    )

    files, active_index = store.get_tsd_files(sg_path)
    objects = store.get_tsd_objects(sg_path)

    assert active_index == 0
    assert len(files) == 1
    assert files[0].name == "base.tsd"
    assert objects[0]["name"] == "Crossing A"
