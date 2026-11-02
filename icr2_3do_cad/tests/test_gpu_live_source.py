"""N3 source export/compile parity required by the GPU live editor.

The text is the same canonical export used by the CPU CAD source pane.
Editing and compiling source must not write the original .3DO asset.
"""
import re
import tempfile
import unittest
from pathlib import Path

from three_do import Model, FormatError
from n3_compile import compile_n3_text
from text_3d import export_text

ROOT = Path(__file__).resolve().parents[1]


class GPULiveSourceTests(unittest.TestCase):
    def test_exported_car_geometry_compiles_and_edits_without_touching_binary(self):
        path = ROOT / 'fixtures' / 'roadcar.3do'
        original_bytes = path.read_bytes()
        original = Model(path, associate_planes=False)
        source = export_text(original)
        self.assertIn('3D VERSION 3.0;', source)
        self.assertIn('% ICR2_ROOT:', source)
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / 'roadcar_edited.3d'
            compiled, document = compile_n3_text(
                source, source_path, associate_planes=False)
            self.assertGreater(len(compiled.polygons), 10)
            self.assertGreater(len(compiled.vertices), 10)
            self.assertTrue(compiled.dynamics)
            self.assertEqual(len(original.polygons), len(compiled.polygons))
            # Modify one declared polygon's actual indexed palette color.
            match = re.search(r'(?m)^(_\d+:\s*POLY(?:\s*\[T\])?\s*<)\s*(\d+)', source)
            self.assertIsNotNone(match)
            changed = (source[:match.start(2)] +
                       str((int(match.group(2))+23)%256) +
                       source[match.end(2):])
            edited, _ = compile_n3_text(
                changed, source_path, associate_planes=False)
            self.assertEqual(len(edited.polygons), len(compiled.polygons))
            self.assertNotEqual(
                [p.color for p in compiled.polygons.values()],
                [p.color for p in edited.polygons.values()])
            self.assertEqual(path.read_bytes(), original_bytes)

    def test_invalid_n3_is_rejected_without_writing_source_model(self):
        path = ROOT / 'fixtures' / 'roadcar.3do'
        before = path.read_bytes()
        source = export_text(Model(path, associate_planes=False))
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises((FormatError, ValueError)):
                compile_n3_text(
                    source + '\nBROKEN: FACE INVALID;\n',
                    Path(directory) / 'bad.3d', associate_planes=False)
        self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
