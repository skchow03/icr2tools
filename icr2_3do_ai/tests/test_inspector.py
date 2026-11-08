"""CPU-only semantic inspector regressions: no Qt/OpenGL or internet access."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from icr2_3do_ai.geometry import analyze_geometry
from icr2_3do_ai.inspector import analyze_model, write_package

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "icr2_3do_cad" / "fixtures"

SOURCE = """3D VERSION 3.0;
a: [<0,0,0>];
b: [<1000,0,0>];
c: [<0,1000,0>];
d: [<1000,1000,0>];
e: [<5000,0,0>, T=<0,0>];
f: [<6000,0,0>, T=<255,0>];
g: [<5000,1000,0>, T=<0,255>];
p1: POLY <40> {a,b,c};
p2: POLY <41> {b,d,c};
p3: POLY [T] <42> {e,f,g};
surface: MATERIAL MIP="surface", GROUP=3, p3;
root: LIST {p1,p2,surface};
"""


class SemanticInspectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def synthetic(self):
        source = self.root / "sample.3D"
        source.write_text(SOURCE, encoding="utf-8")
        return source

    def test_edge_connected_groups_keep_original_binary_record_ids(self):
        reports = analyze_model(self.synthetic())
        summary = reports["summary"]
        geo = reports["geometry"]
        self.assertEqual(summary["counts"]["polygons"], 3)
        self.assertEqual(summary["counts"]["textured_polygons"], 1)
        self.assertEqual(geo["component_count"], 2)
        faces = geo["polygons"]
        first, second, last = (
            [p for p in faces if p["original_palette_index"] == x][0]
            for x in (40, 41, 42)
        )
        self.assertTrue(first["id"].startswith("i0:p"))
        self.assertTrue(first["vertex_ids"][0].startswith("i0:v"))
        self.assertIn(second["id"], first["adjacent_polygon_ids"])
        self.assertIn(first["id"], second["adjacent_polygon_ids"])
        self.assertEqual(first["component_id"], second["component_id"])
        self.assertNotEqual(first["component_id"], last["component_id"])
        self.assertAlmostEqual(first["area_raw_units_squared"], 500000.0)
        self.assertIsNotNone(first["winding_normal"])
        self.assertEqual(last["material"], "surface")
        self.assertEqual(last["uv_bounds"]["max"], [255, 255])
        self.assertEqual(geo["bounds"]["min"], [0.0, 0.0, 0.0])
        self.assertEqual(geo["bounds"]["max"], [6000.0, 1000.0, 0.0])

    def test_material_file_resolution_and_uv_metadata(self):
        source = self.synthetic()
        texture = self.root / "surface.mip"
        shutil.copyfile(FIX / "ind96.mip", texture)
        reports = analyze_model(source)
        mats = reports["materials"]["materials"]
        self.assertEqual(len(mats), 1)
        self.assertEqual(mats[0]["name"], "surface")
        self.assertEqual(mats[0]["file"], str(texture))
        self.assertGreater(mats[0]["dimensions"]["width"], 0)
        self.assertGreater(mats[0]["dimensions"]["height"], 0)
        self.assertEqual(reports["summary"]["counts"]["diagnostic_errors"], 0)
        self.assertFalse(any(
            d["code"] == "MISSING_MIP_FILE"
            for d in reports["diagnostics"]["entries"]))

    def test_real_car_scene_and_unique_reference_instances(self):
        report = analyze_model(FIX / "indycar.3do", objects_folder=FIX)
        summary = report["summary"]
        graph = report["scene_graph"]
        self.assertGreater(summary["counts"]["polygons"], 0)
        self.assertGreater(summary["counts"]["instances"], 1)
        self.assertEqual(graph["instances"][0]["parent_link"], None)
        self.assertEqual(graph["instances"][0]["model_id"], "model0")
        self.assertGreater(len(graph["models"][0]["nodes"]), 0)
        self.assertTrue(any(node["type"] == "DYNAMIC"
                            for node in graph["models"][0]["nodes"]))
        self.assertTrue(any(instance["parent_link"] and
                            instance["parent_link"]["link_kind"] == "dynamic"
                            for instance in graph["instances"][1:]))
        self.assertEqual(len(report["geometry"]["polygons"]),
                         summary["counts"]["polygons"])
        self.assertGreater(summary["counts"]["components"], 0)

    def test_car_driver_wrapper_remap_and_provenance(self):
        wrapped = analyze_model(FIX / "cit74.3do", objects_folder=FIX)
        self.assertEqual(wrapped["summary"]["appearance_wrapper"],
                         str(FIX / "cit74.3do"))
        self.assertEqual(wrapped["scene_graph"]["instances"][0][
                         "inherited_material"], "cit74")
        root_polygons = [
            p for p in wrapped["geometry"]["polygons"]
            if p["instance_id"] == 0 and p["kind"] == "POLY[T]"
        ]
        self.assertTrue(root_polygons)
        self.assertTrue(all(p["material"] == "cit74" for p in root_polygons))
        self.assertTrue(all(p["material_source"] == str(FIX / "cit74.3do")
                            for p in root_polygons))

    def test_reports_views_source_are_read_only(self):
        source = self.synthetic()
        original = source.read_bytes()
        output = self.root / "analysis"
        summary = write_package(source, output, with_source=True, with_views=True)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(summary["counts"]["polygons"], 3)
        for name in ("summary", "geometry", "scene_graph",
                     "materials", "diagnostics"):
            self.assertIsInstance(json.loads((output / (name + ".json")).read_text()), dict)
        self.assertEqual((output / "source.3D").read_text(), SOURCE)
        for view in ("side", "top", "front"):
            self.assertGreater((output / "views" / (view + ".png")).stat().st_size, 100)
        with self.assertRaises(FileExistsError):
            write_package(source, output)

    def test_cli_runs_outside_cad_gui(self):
        source = self.synthetic()
        out = self.root / "cli_output"
        process = subprocess.run(
            [sys.executable, "-m", "icr2_3do_ai", "inspect",
             str(source), "-o", str(out), "--views"],
            cwd=ROOT, text=True, capture_output=True, timeout=60)
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(result["counts"]["polygons"], 3)
        self.assertTrue((out / "geometry.json").is_file())

    def test_no_guesses_for_missing_external_or_missing_mip(self):
        source = self.synthetic()
        report = analyze_model(source)
        self.assertTrue(any(
            d["code"] == "MISSING_MIP_FILE"
            for d in report["diagnostics"]["entries"]))
        self.assertEqual(
            report["materials"]["materials"][0]["file"], None)


if __name__ == "__main__":
    unittest.main()
