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


def test_track3d_tso_writer_inserts_new_declaration_on_its_own_line():
    controller = _controller_with_objects([
        TracksideObject("tree", 1, 2, 3, 4, 5, 6),
        TracksideObject("sign", 7, 8, 9, 10, 11, 12),
    ])
    text = (
        '__TSO0: DYNAMIC 1, 2, 3, 4, 5, 6, 1, EXTERN "tree";\n'
        'ObjectList_L0_0: LIST { __TSO0, __TSO1 };\n'
    )

    updated, replaced_count, deleted_count = controller._replace_tso_dynamic_section_in_3d_text(text)

    assert replaced_count == 1
    assert deleted_count == 0
    assert (
        '__TSO0: DYNAMIC 1, 2, 3, 4, 5, 6, 1, EXTERN "tree";\n'
        '__TSO1: DYNAMIC 7, 8, 9, 10, 11, 12, 1, EXTERN "sign";\n'
        'ObjectList_L0_0: LIST { __TSO0, __TSO1 };\n'
    ) == updated


def test_project_restore_reads_settings_payload_once(monkeypatch, tmp_path):
    from sg_viewer.ui.viewer_controller import SGViewerController
    from sg_viewer.services.sg_settings_store import SGSettingsStore

    sg_path = tmp_path / "tracks" / "test.sg"
    sg_path.parent.mkdir(parents=True, exist_ok=True)
    track3d_path = sg_path.parent / "track.3d"

    class CountingStore(SGSettingsStore):
        def __init__(self):
            self.load_count = 0
            self.payload = {
                "track3d_file": "track.3d",
                "track3d_colors": {"TSO": 42},
                "tsd": {
                    "objects": [],
                    "skid_marks": {"rows_csv": "rows", "colors_csv": "45,28"},
                },
                "trackside_objects": [
                    {
                        "filename": "tower",
                        "x": 1,
                        "y": 2,
                        "z": 3,
                        "yaw": 4,
                        "pitch": 5,
                        "tilt": 6,
                    }
                ],
                "land_objects": [
                    {"name": "Tree Line", "points": [], "polygons": []}
                ],
                "tso_visibility": {
                    "object_lists": [{"section": 1}],
                    "detail_lists": [{"section": 2}],
                },
                "tso_auto_update_relative_z": True,
            }

        def load(self, path):
            self.load_count += 1
            return self.payload

    class Checkbox:
        def __init__(self):
            self.checked = False

        def blockSignals(self, _blocked):
            return False

        def setChecked(self, checked):
            self.checked = checked

    class Combo:
        def setCurrentIndex(self, index):
            self.index = index

    class Sidebar:
        def __init__(self):
            self.object_lists = None
            self.detail_lists = None

        def load_object_lists_from_payload(self, payload):
            self.object_lists = payload

        def load_detail_lists_from_payload(self, payload):
            self.detail_lists = payload

    class Window:
        def __init__(self):
            self.tso_auto_update_relative_z_checkbox = Checkbox()
            self.tsd_files_combo = Combo()
            self.tso_visibility_sidebar = Sidebar()
            self.land_objects = None

        def load_land_objects(self, payload):
            self.land_objects = payload

        def set_selected_track3d_path_text(self, _text):
            pass

        def set_selected_colors_path_text(self, text):
            self.colors_text = text

    controller = SGViewerController.__new__(SGViewerController)
    controller._window = Window()
    controller._current_path = sg_path
    controller._sg_settings_store = CountingStore()
    controller._loaded_tsd_files = []
    selected_track3d_paths = []

    monkeypatch.setattr(
        controller,
        "_clear_loaded_tsd_files",
        lambda: controller._loaded_tsd_files.clear(),
    )
    monkeypatch.setattr(controller, "_sync_tso_visibility_section_dlongs", lambda: None)
    monkeypatch.setattr(controller, "_refresh_tsd_objects_table", lambda: None)
    monkeypatch.setattr(controller, "_refresh_tso_table", lambda: None)
    monkeypatch.setattr(controller, "_set_tsd_dirty", lambda _dirty: None)
    monkeypatch.setattr(controller, "_set_trackside_objects_dirty", lambda _dirty: None)
    monkeypatch.setattr(controller, "set_land_objects_dirty", lambda _dirty: None)
    monkeypatch.setattr(
        controller,
        "_set_selected_track3d_path",
        lambda path, *, persist: selected_track3d_paths.append((path, persist)),
    )

    controller._load_tsd_state_for_current_track()

    assert controller._sg_settings_store.load_count == 1
    assert controller._auto_update_tso_relative_z is True
    assert controller._window.tso_auto_update_relative_z_checkbox.checked is True
    assert selected_track3d_paths == [(track3d_path.resolve(), False)]
    assert controller._window.land_objects == [
        {"name": "Tree Line", "points": [], "polygons": []}
    ]
    assert controller._window.tso_visibility_sidebar.object_lists == [{"section": 1}]
    assert controller._window.tso_visibility_sidebar.detail_lists == [{"section": 2}]
    assert len(controller._trackside_objects) == 1
    assert controller._trackside_objects[0].filename == "tower"
    assert controller._skid_marks_rows_text == "rows"
    assert controller._skid_marks_colors == (45, 28)
