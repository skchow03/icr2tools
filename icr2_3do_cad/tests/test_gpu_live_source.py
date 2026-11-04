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
from text_3d import export_text, export_compilable_text, import_text

ROOT = Path(__file__).resolve().parents[1]


class GPULiveSourceTests(unittest.TestCase):
    def test_exported_car_geometry_compiles_and_edits_without_touching_binary(self):
        path = ROOT / 'fixtures' / 'roadcar.3do'
        original_bytes = path.read_bytes()
        original = Model(path, associate_planes=False)
        source = export_compilable_text(original)
        self.assertIn('3D VERSION 3.0;', source)
        self.assertRegex(source, r'(?m)^root:\s+\S')
        self.assertNotIn('% ICR2_OFFSET:', source)
        self.assertNotIn('% ICR2_ROOT:', source)
        self.assertNotIn('Original binary 3DO is required', source)
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / 'roadcar_edited.3d'
            compiled, document = compile_n3_text(
                source, source_path, associate_planes=False)
            self.assertEqual(
                compiled.records[compiled.root_offset],
                original.records[original.root_offset])
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

    def test_clean_source_handles_other_binary_models_and_root_identity(self):
        # Different kinds of 3DO hierarchy must preserve their real root
        # even if it is not the final binary record.
        for name in ('roadcar.3do', 'indycar.3do', 'panoz.3do',
                     'ind96.3do', 'fwheel.3do'):
            with self.subTest(model=name):
                path = ROOT / 'fixtures' / name
                original = Model(path, associate_planes=False)
                original_bytes = path.read_bytes()
                text = export_compilable_text(original)
                self.assertEqual(text.count('root:'), 1)
                self.assertNotIn('% ICR2_OFFSET:', text)
                self.assertNotIn('% ICR2_ROOT:', text)
                self.assertNotIn('Original binary 3DO', text)
                rebuilt, parsed = compile_n3_text(
                    text, Path(name).with_suffix('.3d'),
                    associate_planes=False)
                self.assertIn('root', rebuilt.n3_label_offsets)
                self.assertEqual(
                    rebuilt.n3_label_offsets['root'], rebuilt.root_offset)
                self.assertEqual(
                    rebuilt.records[rebuilt.root_offset],
                    original.records[original.root_offset])
                self.assertEqual(len(rebuilt.polygons), len(original.polygons))
                self.assertEqual(len(rebuilt.vertices), len(original.vertices))
                self.assertEqual(path.read_bytes(), original_bytes)

    def test_annotated_export_remains_for_conservative_binary_import(self):
        # The older file -> import onto loaded binary path needs offsets.
        path = ROOT / 'fixtures' / 'roadcar.3do'
        model = Model(path, associate_planes=False)
        original = path.read_bytes()
        annotated = export_text(model)
        self.assertIn('% ICR2_OFFSET:', annotated)
        self.assertIn('% ICR2_ROOT:', annotated)
        edited, _ = import_text(model, annotated)
        self.assertEqual(len(edited.polygons), len(model.polygons))
        self.assertEqual(path.read_bytes(), original)

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
