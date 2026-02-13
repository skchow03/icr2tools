from pathlib import Path

from sg_viewer.model.history import FileHistory


def test_ensure_preview_colors_writes_defaults_for_missing_file(tmp_path):
    ini_path = tmp_path / "sg_viewer.ini"
    history = FileHistory(ini_path)

    defaults = {
        "background": "#000000",
        "centerline_selected": "#FFFF00",
    }

    resolved = history.ensure_preview_colors(defaults)

    assert resolved == defaults
    content = ini_path.read_text(encoding="utf-8")
    assert "[preview_colors]" in content
    assert "background = #000000" in content
    assert "centerline_selected = #FFFF00" in content


def test_ensure_preview_colors_replaces_invalid_and_normalizes(tmp_path):
    ini_path = tmp_path / "sg_viewer.ini"
    ini_path.write_text(
        """
[preview_colors]
background = #abcdef
centerline_selected = not-a-color
""".strip()
        + "\n",
        encoding="utf-8",
    )

    history = FileHistory(ini_path)
    resolved = history.ensure_preview_colors(
        {
            "background": "#000000",
            "centerline_selected": "#FFFF00",
            "nodes_connected": "#32CD32",
        }
    )

    assert resolved["background"] == "#ABCDEF"
    assert resolved["centerline_selected"] == "#FFFF00"
    assert resolved["nodes_connected"] == "#32CD32"

    content = ini_path.read_text(encoding="utf-8")
    assert "background = #ABCDEF" in content
    assert "centerline_selected = #FFFF00" in content
    assert "nodes_connected = #32CD32" in content


def test_set_preview_color_persists_single_color(tmp_path):
    ini_path = tmp_path / "sg_viewer.ini"
    history = FileHistory(ini_path)

    history.set_preview_color("background", "#123456")
    history.set_preview_color("background", "not-a-color")

    content = ini_path.read_text(encoding="utf-8")
    assert "[preview_colors]" in content
    assert "background = #123456" in content


def test_preview_fsect_colors_use_descriptive_storage_keys(tmp_path):
    ini_path = tmp_path / "sg_viewer.ini"
    history = FileHistory(ini_path)

    resolved = history.ensure_preview_colors({"fsect_0": "#00AA00", "fsect_8": "#B0B0B0"})

    assert resolved["fsect_0"] == "#00AA00"
    assert resolved["fsect_8"] == "#B0B0B0"

    content = ini_path.read_text(encoding="utf-8")
    assert "fsect_grass = #00AA00" in content
    assert "fsect_armco = #B0B0B0" in content
    assert "fsect_0" not in content
    assert "fsect_8" not in content



def test_set_preview_color_persists_long_curve_color(tmp_path):
    ini_path = tmp_path / "sg_viewer.ini"
    history = FileHistory(ini_path)

    history.set_preview_color("centerline_long_curve", "#AA0000")

    content = ini_path.read_text(encoding="utf-8")
    assert "centerline_long_curve = #AA0000" in content

def test_measurement_unit_round_trip(tmp_path):
    ini_path = tmp_path / "sg_viewer.ini"
    history = FileHistory(ini_path)

    assert history.get_measurement_unit() is None

    history.set_measurement_unit("meter")
    assert history.get_measurement_unit() == "meter"

    content = ini_path.read_text(encoding="utf-8")
    assert "[view]" in content
    assert "uom = meter" in content

    history.set_measurement_unit("invalid")
    assert history.get_measurement_unit() == "meter"
