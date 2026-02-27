from sg_viewer.services.sg_settings_store import SGSettingsStore


def test_sunny_palette_colors_round_trip(tmp_path):
    sg_path = tmp_path / "tracks" / "test.sg"
    sg_path.parent.mkdir(parents=True, exist_ok=True)
    sg_path.write_bytes(b"")

    store = SGSettingsStore()
    colors = [(index, (index + 1) % 256, (index + 2) % 256) for index in range(256)]

    store.set_sunny_palette_colors(sg_path, colors)

    assert store.get_sunny_palette_colors(sg_path) == colors


def test_sunny_palette_colors_invalid_payload_returns_none(tmp_path):
    sg_path = tmp_path / "tracks" / "test.sg"
    sg_path.parent.mkdir(parents=True, exist_ok=True)
    sg_path.write_bytes(b"")

    settings_path = sg_path.with_suffix(".sgc")
    settings_path.write_text('{"sunny_palette_colors": [[0, 0, 0]]}', encoding="utf-8")

    store = SGSettingsStore()

    assert store.get_sunny_palette_colors(sg_path) is None
