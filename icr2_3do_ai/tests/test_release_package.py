"""Phase 4 release-candidate provenance and safety regression tests."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from PIL import Image

from icr2_3do_ai.parametric import generate_source
from icr2_3do_ai.stage2 import validate_source
from icr2_3do_ai.release_package import (
    MODEL_FILES, WASP_RECIPES, candidate_bytes, create_candidate,
)

SHA = "abcdef1234567890abcdef1234567890abcdef12"


def _json(path, obj):
    path.write_text(json.dumps(obj, indent=2)+"\n", encoding="utf-8")


class ReleaseCandidateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.models = self.directory/"models"
        self.previews = self.directory/"preview"
        self.comparison = self.directory/"compare"
        self.recipes = self.directory/"recipes"
        for p in (self.models, self.previews, self.comparison, self.recipes):
            p.mkdir()
        source, _ = generate_source({
            "schema":"icr2.n3.recipe.v1", "coordinate_scale":1,
            "operations":[{"type":"polygon","name":"panel","axis":"z",
                           "at":0,"color":49,
                           "outline":[[0,0],[300,0],[300,300],[0,300]]}],
        })
        model, _ = validate_source(source)
        for name in ("WASP","FWHEEL","RWHEEL"):
            (self.models/f"{name}.3D").write_text(source)
            (self.models/f"{name}.3do").write_bytes(model.raw)
        (self.models/"HELMET.3do").write_bytes(model.raw)
        _json(self.models/"assembly_manifest.json",{
            "sha256": {
                f"{name}.3do":sha256((self.models/f"{name}.3do").read_bytes()).hexdigest()
                for name in ("WASP","FWHEEL","RWHEEL","HELMET")
            }
        })
        for name in WASP_RECIPES:
            (self.recipes/name).write_text('{"schema":"icr2.n3.recipe.v1"}\n')
        self.cameras = ["front","rear"]
        views={}
        stats={}
        comparisons={}
        for cam in self.cameras:
            color=(125,155,215) if cam=="front" else (215,155,125)
            path=self.previews/f"{cam}.png"
            Image.new("RGB", (80,80), color).save(path)
            views[cam]={"file":path.name,"sha256":sha256(path.read_bytes()).hexdigest()}
            stats[cam]={"rendered_sprites":1}
            comparisons[cam]={"changed_pixels":0}
            for suffix in ("before","after","diff","comparison"):
                Image.new("RGB",(80,80),color).save(
                    self.comparison/f"{cam}-{suffix}.png")
        _json(self.previews/"preview.json",{
            "schema":"icr2.visual-preview.v1",
            "cameras":self.cameras,"warnings":[],
            "views":views,"statistics":stats,
        })
        _json(self.comparison/"comparison.json",{
            "schema":"icr2.visual-regression.v1",
            "cameras":self.cameras,"warnings":[],
            "threshold_passed":True,"maximum_changed_fraction":0,
            "views":comparisons,
        })

    def build(self):
        return candidate_bytes(
            self.models,self.previews,self.comparison,self.recipes,
            source_commit=SHA)

    def test_deterministic_binary_and_complete_review_artifacts(self):
        zipped, manifest = self.build()
        again, same = self.build()
        self.assertEqual(zipped,again)
        self.assertEqual(manifest,same)
        self.assertEqual(manifest["source_commit"],SHA)
        self.assertEqual(manifest["status"],"review-only-unpublished")
        self.assertEqual(len(manifest["cameras"]),2)
        with ZipFile(__import__("io").BytesIO(zipped)) as archive:
            self.assertIsNone(archive.testzip())
            names=set(archive.namelist())
            self.assertIn("SHA256SUMS",names)
            self.assertIn("release_manifest.json",names)
            for file in MODEL_FILES:
                self.assertIn("models/"+file,names)
            for file in WASP_RECIPES:
                self.assertIn("recipes/"+file,names)
            self.assertIn("visuals/comparison/front-diff.png",names)
            sums=dict(
                (line.split("  ",1)[1],line.split("  ",1)[0])
                for line in archive.read("SHA256SUMS").decode().splitlines())
            for path,digest in sums.items():
                self.assertEqual(sha256(archive.read(path)).hexdigest(),digest)

    def test_transactional_output_and_no_overwrite(self):
        out=self.directory/"candidate"
        result=create_candidate(
            self.models,self.previews,self.comparison,self.recipes,
            out,source_commit=SHA)
        self.assertEqual(result["status"],"review-only-unpublished")
        self.assertTrue((out/"release-candidate.zip").is_file())
        self.assertTrue((out/"release_manifest.json").is_file())
        with self.assertRaises(FileExistsError):
            create_candidate(self.models,self.previews,self.comparison,
                             self.recipes,out,source_commit=SHA)

    def test_reject_modified_binary_and_recompile_mismatch(self):
        path=self.models/"WASP.3do"
        path.write_bytes(path.read_bytes()+b"x")
        with self.assertRaises(ValueError):
            self.build()
        self.assertFalse((self.directory/"candidate").exists())

    def test_reject_missing_reference_inputs(self):
        (self.recipes/WASP_RECIPES[0]).unlink()
        with self.assertRaises(ValueError):
            self.build()

    def test_reject_missing_or_wrong_camera_images(self):
        (self.previews/"front.png").unlink()
        with self.assertRaises(ValueError):
            self.build()

    def test_reject_missing_helmet_sprite_or_asset_warnings(self):
        document=json.loads((self.previews/"preview.json").read_text())
        document["statistics"]["rear"]["rendered_sprites"]=0
        _json(self.previews/"preview.json",document)
        with self.assertRaisesRegex(ValueError,"helmet"):
            self.build()
        document["statistics"]["rear"]["rendered_sprites"]=1
        document["warnings"]=["Missing helm0001.pmp"]
        _json(self.previews/"preview.json",document)
        with self.assertRaisesRegex(ValueError,"Missing assets"):
            self.build()

    def test_reject_failed_visual_difference_and_bad_sha(self):
        doc=json.loads((self.comparison/"comparison.json").read_text())
        doc["views"]["front"]["changed_pixels"]=3
        _json(self.comparison/"comparison.json",doc)
        with self.assertRaisesRegex(ValueError,"baseline difference"):
            self.build()
        doc["views"]["front"]["changed_pixels"]=0
        doc["maximum_changed_fraction"]=.1
        _json(self.comparison/"comparison.json",doc)
        with self.assertRaisesRegex(ValueError,"pixel-identical"):
            self.build()
        doc["maximum_changed_fraction"]=0
        _json(self.comparison/"comparison.json",doc)
        with self.assertRaisesRegex(ValueError,"source_commit"):
            candidate_bytes(self.models,self.previews,self.comparison,
                            self.recipes,source_commit="main")


if __name__=="__main__":
    unittest.main()
