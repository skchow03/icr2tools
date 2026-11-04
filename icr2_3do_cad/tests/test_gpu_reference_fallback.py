"""GPU referenced 3DO/N3 resolution: binary-first, validated, read-only.

These tests use synthetic N3 geometry and need no Qt, OpenGL or game assets.
"""
import tempfile
import unittest
from pathlib import Path

from gpu_viewer.model_assets import (
    candidate_model_paths, choose_reference, load_model_candidate,
    reference_directories,
)
from gpu_viewer.scene import build_scene, load_car_or_model
from n3_compile import compile_n3_text


CHILD = """3D VERSION 3.0;
a: [<0,0,0>];
b: [<100,0,0>];
c: [<0,100,0>];
poly: POLY <44> {a,b,c};
root: LIST {poly};
"""

PARENT = """3D VERSION 3.0;
a: [<0,0,0>];
b: [<100,0,0>];
c: [<0,100,0>];
poly: POLY <45> {a,b,c};
item: DYNAMIC 0, 0, 0, 0, 0, 0, 1, EXTERN "child";
root: LIST {poly, item};
"""

NESTED_CHILD = """3D VERSION 3.0;
a: [<0,0,0>];
b: [<100,0,0>];
c: [<0,100,0>];
poly: POLY <44> {a,b,c};
nested: DYNAMIC 0, 0, 0, 0, 0, 0, 1, EXTERN "grand";
root: LIST {poly, nested};
"""

EXTERNAL = """3D VERSION 3.0;
root: MATERIAL MIP="body", GROUP=3, EXTERN "child";
"""


class GPUReferenceFallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)

    def write_n3(self, stem, source=CHILD, folder=None):
        path = (folder or self.folder) / (stem + ".3d")
        path.write_text(source, encoding="utf-8")
        return path

    def write_3do(self, stem, source=CHILD, folder=None):
        path = (folder or self.folder) / (stem + ".3do")
        model, _ = compile_n3_text(source, path, associate_planes=False)
        path.write_bytes(model.raw)
        return path

    def parent_scene(self, source=PARENT):
        path = self.write_n3("parent", source)
        root, _ = compile_n3_text(source, path, associate_planes=False)
        return build_scene(root)

    def test_n3_only_dynamic_resolves_with_unchanged_file(self):
        child = self.write_n3("CHILD")
        original = child.read_bytes()
        scene = self.parent_scene()
        self.assertEqual(scene.loaded_instances, 1)
        self.assertEqual(scene.instances[1].model.path, child)
        self.assertEqual(scene.warnings, ())
        self.assertEqual(len(scene.geometry.polygons), 2)
        self.assertEqual(child.read_bytes(), original)

    def test_valid_binary_has_priority_over_source(self):
        source = self.write_n3("child")
        binary = self.write_3do("CHILD", source=CHILD.replace("POLY <44>", "POLY <55>"))
        scene = self.parent_scene()
        self.assertEqual(scene.loaded_instances, 1)
        self.assertEqual(scene.instances[1].model.path, binary)
        self.assertEqual(next(iter(scene.instances[1].model.polygons.values())).color, 55)
        self.assertEqual(scene.warnings, ())
        self.assertTrue(source.is_file())

    def test_binary_parent_can_resolve_n3_dynamic_child(self):
        parent = self.write_3do("parent", PARENT)
        child = self.write_n3("child")
        raw = parent.read_bytes()
        model, scene, appearance = load_car_or_model(parent)
        self.assertIsNone(appearance)
        self.assertEqual(scene.root.path, parent)
        self.assertEqual(scene.loaded_instances, 1)
        self.assertEqual(scene.instances[1].model.path, child)
        self.assertEqual(parent.read_bytes(), raw)

    def test_invalid_local_binary_does_not_shadow_valid_later_binary(self):
        self.write_n3("child")
        (self.folder / "child.3do").write_bytes(b"corrupt")
        others = self.folder / "assets"
        others.mkdir()
        valid_binary = self.write_3do("CHILD", folder=others)
        root_path = self.write_n3("parent", PARENT)
        model, _ = compile_n3_text(
            PARENT, root_path, associate_planes=False)
        scene = build_scene(model, objects_folder=others)
        self.assertEqual(scene.instances[1].model.path, valid_binary)
        self.assertTrue(any("child.3do" in issue for issue in scene.warnings))

    def test_bad_binary_falls_back_to_valid_source(self):
        source = self.write_n3("child")
        binary = self.folder / "child.3do"
        binary.write_bytes(b"not a 3do")
        before = binary.read_bytes()
        scene = self.parent_scene()
        self.assertEqual(scene.loaded_instances, 1)
        self.assertEqual(scene.instances[1].model.path, source)
        self.assertTrue(any("child.3do" in message for message in scene.warnings))
        self.assertEqual(binary.read_bytes(), before)

    def test_other_directory_valid_binary_beats_local_source(self):
        source = self.write_n3("child")
        objects = self.folder / "objects"
        objects.mkdir()
        binary = self.write_3do("CHILD", folder=objects)
        scene = build_scene(
            compile_n3_text(PARENT, self.write_n3("parent", PARENT),
                            associate_planes=False)[0],
            objects_folder=objects)
        self.assertEqual(scene.instances[1].model.path, binary)
        self.assertTrue(source.is_file())

    def test_nested_dynamic_can_mix_binary_and_n3(self):
        self.write_n3("child", NESTED_CHILD)
        binary = self.write_3do("grand")
        scene = self.parent_scene()
        self.assertEqual(scene.loaded_instances, 2)
        self.assertEqual(scene.instances[1].model.path.suffix.lower(), ".3d")
        self.assertEqual(scene.instances[2].model.path, binary)
        self.assertEqual(len(scene.geometry.polygons), 3)

    def test_negative_external_pointers_also_use_fallback(self):
        child = self.write_n3("child")
        scene = self.parent_scene(EXTERNAL)
        self.assertEqual(scene.loaded_instances, 1)
        self.assertEqual(scene.instances[1].model.path, child)

    def test_invalid_both_formats_do_not_break_parent(self):
        self.write_n3("child", "invalid 3D content")
        (self.folder / "child.3do").write_bytes(b"invalid")
        scene = self.parent_scene()
        self.assertEqual(scene.loaded_instances, 0)
        self.assertEqual(len(scene.geometry.polygons), 1)
        self.assertTrue(any("child.3do" in issue for issue in scene.warnings))
        self.assertTrue(any("child.3d" in issue for issue in scene.warnings))

    def test_repeated_instances_reuse_model(self):
        source = PARENT.replace(
            "root: LIST {poly, item};",
            'second: DYNAMIC 50, 0, 0, 0, 0, 0, 1, EXTERN "child";\n'
            "root: LIST {poly, item, second};")
        self.write_n3("child")
        scene = self.parent_scene(source)
        self.assertEqual(scene.loaded_instances, 2)
        self.assertIs(scene.instances[1].model, scene.instances[2].model)

    def test_explicit_n3_override_can_select_source(self):
        self.write_3do("child")
        custom = self.write_n3("my_special_child")
        scene = build_scene(
            compile_n3_text(PARENT, self.write_n3("parent", PARENT),
                            associate_planes=False)[0],
            object_overrides={"child": custom})
        self.assertEqual(scene.instances[1].model.path, custom)


if __name__ == "__main__":
    unittest.main()
