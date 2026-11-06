"""Automatic same-folder SUNNY.PCX palette lookup for the GPU CAD viewer.

No binary model files are changed. All tests work on a case-sensitive CI
filesystem as well as Windows' usual case-insensitive filenames.
"""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from textures import find_model_sunny_palette, load_palette


ROOT = Path(__file__).resolve().parents[1]


class AutoSunnyPaletteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.base_palette = ROOT / "gamepal.pcx"

    def create_sunny(self, folder, name, *, malformed=False):
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / name
        if malformed:
            target.write_bytes(b"not a PCX palette")
        else:
            data = bytearray(self.base_palette.read_bytes())
            data[-768:] = bytes((i * 37 + 19) % 256 for i in range(768))
            target.write_bytes(data)
        return target

    def test_exact_dos_uppercase_sunny_with_3do(self):
        model = self.folder / "tree.3do"
        model.touch()
        candidate = self.create_sunny(self.folder, "SUNNY.PCX")
        self.assertEqual(find_model_sunny_palette(model), candidate)
        self.assertFalse(np.array_equal(
            load_palette(candidate), load_palette(self.base_palette)))

    def test_lower_and_mixed_case_filename_with_3d(self):
        for spelling in ("sunny.pcx", "SuNnY.PcX"):
            with self.subTest(spelling=spelling):
                folder = self.folder / spelling
                file = folder / "scenery.3D"
                candidate = self.create_sunny(folder, spelling)
                file.touch()
                self.assertEqual(find_model_sunny_palette(file), candidate)

    def test_only_opened_file_folder_not_child_parent_or_texture_folder(self):
        model_folder = self.folder / "models"
        model_folder.mkdir()
        file = model_folder / "tree.3do"
        file.touch()
        self.create_sunny(self.folder, "SUNNY.PCX")
        self.create_sunny(model_folder / "textures", "sunny.pcx")
        self.assertIsNone(find_model_sunny_palette(file))
        self.assertIsNone(find_model_sunny_palette(
            model_folder / "other.3d"))

    def test_exact_uppercase_wins_if_case_sensitive_folder_has_duplicates(self):
        model = self.folder / "tree.3do"
        upper = self.create_sunny(self.folder, "SUNNY.PCX")
        lower = self.create_sunny(self.folder, "sunny.pcx")
        self.assertEqual(find_model_sunny_palette(model), upper)
        self.assertTrue(lower.is_file())

    def test_case_mismatched_directory_entry_does_not_select_similar_file(self):
        model = self.folder / "tree.3d"
        (self.folder / "Sunny.PCX.bak").write_bytes(b"foo")
        (self.folder / "cloudy.pcx").write_bytes(b"foo")
        (self.folder / "SUNNY.PCX").mkdir()
        self.assertIsNone(find_model_sunny_palette(model))


if __name__ == "__main__":
    unittest.main()
