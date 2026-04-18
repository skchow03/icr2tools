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


def test_tsd_skid_marks_state_round_trip(tmp_path):
    sg_path = tmp_path / "tracks" / "test.sg"
    sg_path.parent.mkdir(parents=True, exist_ok=True)
    sg_path.write_bytes(b"")

    store = SGSettingsStore()
    store.set_tsd_skid_marks_state(
        sg_path,
        {
            "rows_csv": "Turn1,100,120,140,10,20,1000,3,20,10,12,8,11,7",
            "colors_csv": "45,28",
        },
    )

    payload = store.get_tsd_skid_marks_state(sg_path)

    assert payload == {
        "rows_csv": "Turn1,100,120,140,10,20,1000,3,20,10,12,8,11,7",
        "colors_csv": "45,28",
    }


def test_track3d_file_round_trip_with_relative_path(tmp_path):
    sg_path = tmp_path / "tracks" / "test.sg"
    sg_path.parent.mkdir(parents=True, exist_ok=True)
    sg_path.write_bytes(b"")
    track3d_path = sg_path.parent / "track.3d"
    track3d_path.write_text("", encoding="utf-8")

    store = SGSettingsStore()
    store.set_track3d_file(sg_path, track3d_path)

    payload = json.loads(sg_path.with_suffix(".sgc").read_text(encoding="utf-8"))
    assert payload["track3d_file"] == "track.3d"
    assert store.get_track3d_file(sg_path) == track3d_path.resolve()


def test_track3d_file_can_be_cleared(tmp_path):
    sg_path = tmp_path / "tracks" / "test.sg"
    sg_path.parent.mkdir(parents=True, exist_ok=True)
    sg_path.write_bytes(b"")

    store = SGSettingsStore()
    store.set_track3d_file(sg_path, tmp_path / "tracks" / "track.3d")
    store.set_track3d_file(sg_path, None)

    payload = json.loads(sg_path.with_suffix(".sgc").read_text(encoding="utf-8"))
    assert "track3d_file" not in payload
