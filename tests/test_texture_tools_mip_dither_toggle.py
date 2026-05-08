from PIL import Image

from texture_tools.main import _prepare_image_for_mip


def test_prepare_image_for_mip_uses_rgb_not_paletted() -> None:
    source = Image.new("RGB", (2, 2), color=(10, 20, 30))
    prepared = _prepare_image_for_mip(source)
    assert prepared.mode == "RGB"
