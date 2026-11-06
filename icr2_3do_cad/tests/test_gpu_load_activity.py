"""Read-only load trace regressions; no commercial track files needed."""
import tempfile
import threading
import unittest
from pathlib import Path

from gpu_viewer.load_activity import LoadActivityTrace
from gpu_viewer.mesh import make_mesh
from gpu_viewer.scene import build_scene
from gpu_viewer.textures import build_atlas
from n3_compile import compile_n3_text


SIMPLE_N3 = """3D VERSION 3.0;
a: [<0,0,0>];
b: [<10000,0,0>];
c: [<0,10000,0>];
p: POLY <42> {a,b,c};
root: LIST {p};
"""


class LoadActivityTraceTests(unittest.TestCase):
    def test_immediate_persistence_and_new_load_replaces_old_log(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "last.log"
            trace = LoadActivityTrace(path)
            line = trace.write("Parsing MICHIGAN.3DO")
            self.assertIn("Parsing MICHIGAN.3DO", path.read_text())
            self.assertEqual(path.read_text(encoding="utf-8").splitlines(),
                             [line])
            self.assertIn("[+", line)
            self.assertIn("s]", line)
            newer = LoadActivityTrace(path)
            newer.write("Opening CLEVLAND.3DO")
            self.assertNotIn("MICHIGAN", path.read_text())
            self.assertIn("CLEVLAND", path.read_text())

    def test_concurrent_disk_writes_never_interleave(self):
        with tempfile.TemporaryDirectory() as temp:
            trace = LoadActivityTrace(Path(temp) / "events.log")
            def work(index):
                for event in range(25):
                    trace.write(f"worker {index} event {event}")
            workers = [threading.Thread(target=work, args=(i,))
                       for i in range(4)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join()
            lines = trace.path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 100)
            self.assertEqual(len(set(lines)), 100)
            self.assertTrue(all("worker" in line for line in lines))

    def test_scene_mip_and_mesh_callbacks_identify_active_phase(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "minimal.3d"
            model, _ = compile_n3_text(
                SIMPLE_N3, path, associate_planes=False)
            events = []
            scene = build_scene(model, on_activity=events.append)
            atlas = build_atlas(
                scene.geometry, path, on_activity=events.append)
            mesh = make_mesh(
                scene.geometry, atlas=atlas, on_activity=events.append)
            self.assertEqual(mesh.polygon_count, 1)
            self.assertTrue(any("scene graph" in x for x in events))
            self.assertTrue(any("MIP" in x for x in events))
            self.assertTrue(any("Triangulating polygon" in x for x in events))
            self.assertTrue(any("Mesh normalization" in x for x in events))


if __name__ == "__main__":
    unittest.main()
