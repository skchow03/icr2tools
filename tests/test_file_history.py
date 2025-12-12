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
