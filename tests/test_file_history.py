from pathlib import Path

from sg_viewer.history import FileHistory


def test_get_background_resolves_relative_path(tmp_path):
    sg_path = tmp_path / "sample.sg"
    image_relative = Path("backgrounds/sample.png")

    config_path = tmp_path / "history.ini"
    config_path.write_text(
        """
[files]
{path} = {{"background_image": "{image}", "background_scale": 2.5, "background_origin_u": 10.0, "background_origin_v": 20.0}}
""".format(
            path=sg_path.resolve(), image=image_relative
        )
    )

    history = FileHistory(config_path)

    background = history.get_background(sg_path)
    assert background is not None

    image_path, scale, origin = background
    assert image_path == (sg_path.parent / image_relative).resolve()
    assert scale == 2.5
    assert origin == (10.0, 20.0)


def test_preserves_paths_with_drive_letter(tmp_path):
    sg_path = tmp_path / "C:/Users/Steven/Desktop/ICR2Tools/sg_viewer/detroit.sg"
    sg_path.parent.mkdir(parents=True, exist_ok=True)
    sg_path.touch()

    image_path = tmp_path / "background.png"
    image_path.touch()

    config_path = tmp_path / "history.ini"
    history = FileHistory(config_path)

    history.record_open(sg_path)
    history.set_background(sg_path, image_path, 10000.0, (0.0, 0.0))

    config_text = config_path.read_text()
    assert "C:/Users/Steven/Desktop/ICR2Tools/sg_viewer/detroit.sg" in config_text

    background = history.get_background(sg_path)
    assert background is not None

    image, scale, origin = background
    assert image == image_path
    assert scale == 10000.0
    assert origin == (0.0, 0.0)
