import pytest

pytest.importorskip("PyQt5")

from sg_viewer.services.trackside_objects import TracksideObject
from sg_viewer.ui.viewer_controller import SGViewerController


def _controller_with_objects(objects):
    controller = object.__new__(SGViewerController)
    controller._trackside_objects = list(objects)
    return controller


def test_track3d_tso_writer_replaces_non_contiguous_declarations():
    controller = _controller_with_objects([
        TracksideObject("tree", 10, 20, 30, 40, 50, 60),
        TracksideObject("sign", 11, 21, 31, 41, 51, 61),
    ])
    text = (
        "header: LIST { nope };\n"
        "__TSO0: DYNAMIC 1, 2, 3, 4, 5, 6, 1, EXTERN \"oldtree\";\n"
        "ObjectList_L0_0: LIST { __TSO0 };\n"
        "__TSO2: DYNAMIC 7, 8, 9, 10, 11, 12, 1, EXTERN \"oldsign\";\n"
        "footer: LIST { nope };\n"
    )

    updated, replaced_count, deleted_count = controller._replace_tso_dynamic_section_in_3d_text(text)

    assert replaced_count == 2
    assert deleted_count == 0
    assert '__TSO0: DYNAMIC 10, 20, 30, 40, 50, 60, 1, EXTERN "tree";' in updated
    assert '__TSO2: DYNAMIC 11, 21, 31, 41, 51, 61, 1, EXTERN "sign";' in updated
    assert "ObjectList_L0_0: LIST { __TSO0 };" in updated


def test_track3d_tso_writer_preserves_stable_ids_when_order_changes():
    tree = TracksideObject("tree", 1, 2, 3, 4, 5, 6)
    sign = TracksideObject("sign", 7, 8, 9, 10, 11, 12)
    controller = _controller_with_objects([sign, tree])
    text = (
        '__TSO0: DYNAMIC 1, 2, 3, 4, 5, 6, 1, EXTERN "tree";\n'
        '__TSO1: DYNAMIC 7, 8, 9, 10, 11, 12, 1, EXTERN "sign";\n'
    )

    updated, replaced_count, deleted_count = controller._replace_tso_dynamic_section_in_3d_text(text)

    assert replaced_count == 2
    assert deleted_count == 0
    assert '__TSO0: DYNAMIC 1, 2, 3, 4, 5, 6, 1, EXTERN "tree";' in updated
    assert '__TSO1: DYNAMIC 7, 8, 9, 10, 11, 12, 1, EXTERN "sign";' in updated


def test_track3d_tso_writer_preserves_comments_between_declarations_and_crlf():
    controller = _controller_with_objects([
        TracksideObject("tree", 10, 20, 30, 40, 50, 60),
        TracksideObject("sign", 11, 21, 31, 41, 51, 61),
    ])
    text = (
        '__TSO0: DYNAMIC 1, 2, 3, 4, 5, 6, 1, EXTERN "oldtree";\r\n'
        '// keep this comment between TSOs\r\n'
        '__TSO1: DYNAMIC 7, 8, 9, 10, 11, 12, 1, EXTERN "oldsign";\r\n'
    )

    updated, replaced_count, deleted_count = controller._replace_tso_dynamic_section_in_3d_text(text)

    assert replaced_count == 2
    assert deleted_count == 0
    assert "\r\n// keep this comment between TSOs\r\n" in updated
    assert "\n" not in updated.replace("\r\n", "")
    assert '__TSO0: DYNAMIC 10, 20, 30, 40, 50, 60, 1, EXTERN "tree";\r\n' in updated
    assert '__TSO1: DYNAMIC 11, 21, 31, 41, 51, 61, 1, EXTERN "sign";\r\n' in updated
