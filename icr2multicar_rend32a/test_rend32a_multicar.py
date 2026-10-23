#!/usr/bin/env python3
"""Regression tests for the REND32A multi-car patcher.

The normal unit tests need no commercial files. To run binary golden tests,
set ICR2_REND32A_FIXTURES to a directory containing the five original EXEs
listed in FIXTURES. They are intentionally not distributed in this repository.
"""
from __future__ import annotations

import os
import struct
import tempfile
import unittest
from pathlib import Path

from diagnose_icrwide import variants as diagnostic_variants

from rend32a_multicar import (
    CODE_LIMIT, LE_VIRT, PRELOAD_HOOK, PRELOAD_NEW, PROFILES,
    emit_payload, identify_profile, main, patch, raw, reconstruct_core_patch,
    relcall, sha, validate_core_patch,
)


FIXTURES = {
    "stock_cart": ("CART(1).EXE",
                   "6105d39d94862eb5483f64ba27f7c1e4a8e6ac029c935c4c9631ebd5a1ecdd3c"),
    "icrwide_cart": ("ICRWide.20260722001_CART.EXE",
                     "51e99afcc0c57af1e82b37be40b1c8bf7ccc13cc45645fdd0a845de710e69c29"),
    "icrwide_indycar": ("ICRWide.20260722001_INDYCAR.EXE",
                       "bc41c58c6b0d4d6e5b2a6ba176e3c0c6ac62b7b317e42fb1b385cc883667d3ae"),
    "increasedheap_cart": ("ICR2.IncreasedHeapSize_CART.EXE",
                           "5cb3ee72f261f256249cd316b3c0425ba37539e021916783ee62eb7c194defe8"),
    "increasedheap_indycar": ("ICR2.IncreasedHeapSize_INDYCAR.EXE",
                             "fa43698f2362c92090cfc2216868ce9bdb094ed05992eb18bb5a004c122c7799"),
}


class ProfileTests(unittest.TestCase):
    def test_unique_and_consistent_profiles(self) -> None:
        self.assertEqual(len(PROFILES), 5)
        self.assertEqual({p.key for p in PROFILES}, set(FIXTURES))
        self.assertEqual(len({p.input_sha256 for p in PROFILES}), 5)
        for profile in PROFILES:
            with self.subTest(profile=profile.key):
                self.assertIn(profile.game, ("CART", "INDYCAR"))
                self.assertEqual(len(profile.input_sha256), 64)
                self.assertEqual(len(profile.core_sha256), 64)
                self.assertEqual(raw(profile, LE_VIRT), LE_VIRT + profile.file_shift)
                self.assertEqual(
                    relcall(PRELOAD_HOOK + profile.file_shift,
                            PRELOAD_NEW + profile.file_shift),
                    relcall(PRELOAD_HOOK, PRELOAD_NEW),
                )

    def test_known_preloader_payload(self) -> None:
        payload = emit_payload(["irl", "panoz"])
        self.assertEqual(len(payload), 96)
        self.assertIn(b"irl.3do\0", payload)
        self.assertIn(b"panoz.3do\0", payload)
        self.assertLessEqual(PRELOAD_NEW + len(payload), CODE_LIMIT)

    def test_reject_unknown_and_mutated_exe(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            identify_profile(b"not an executable")
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            identify_profile(b"\0" * PROFILES[0].size)


@unittest.skipUnless(os.environ.get("ICR2_REND32A_FIXTURES"),
                     "Set ICR2_REND32A_FIXTURES for binary regression tests")
class ExecutableGoldenTests(unittest.TestCase):
    def test_every_profile_against_uploaded_fixture_hashes(self) -> None:
        directory = Path(os.environ["ICR2_REND32A_FIXTURES"])
        for profile in PROFILES:
            filename, expected_final_sha = FIXTURES[profile.key]
            with self.subTest(profile=profile.key):
                source = (directory / filename).read_bytes()
                self.assertEqual(len(source), profile.size)
                self.assertEqual(sha(source), profile.input_sha256)
                self.assertEqual(identify_profile(source), profile)
                core = reconstruct_core_patch(source, profile)
                self.assertEqual(sha(core), profile.core_sha256)
                validate_core_patch(core, profile)
                result, manifest = patch(core, ["irl", "panoz"], profile)
                self.assertEqual(len(result), len(source))
                self.assertEqual(sha(result), expected_final_sha)
                self.assertEqual(manifest["output_sha256"], expected_final_sha)
                self.assertEqual(manifest["profile"], profile.key)
                self.assertEqual(manifest["loader_hook_raw"],
                                 hex(PRELOAD_HOOK + profile.file_shift))
                self.assertEqual(
                    result[raw(profile, PRELOAD_HOOK):raw(profile, PRELOAD_HOOK) + 5],
                    relcall(PRELOAD_HOOK, PRELOAD_NEW),
                )
                self.assertGreaterEqual(
                    struct.unpack_from("<I", result, raw(profile, LE_VIRT))[0],
                    0x9B800,
                )
                # The patch changes 964 bytes for the pinned two-name fixture.
                self.assertEqual(sum(a != b for a, b in zip(source, result)), 964)
                with self.assertRaisesRegex(ValueError, "Unsupported"):
                    identify_profile(result)

    def test_icrwide_diagnostics_only_change_intended_regions(self) -> None:
        directory = Path(os.environ["ICR2_REND32A_FIXTURES"])
        for profile in PROFILES:
            if not profile.key.startswith("icrwide_"):
                continue
            with self.subTest(profile=profile.key):
                filename, golden_sha = FIXTURES[profile.key]
                source = (directory / filename).read_bytes()
                variants = diagnostic_variants(source, profile)
                self.assertEqual(len(variants), 8)
                self.assertEqual(sha(variants["08_full_multicar"]), golden_sha)
                self.assertEqual(len(variants["01_fingerprint_only"]), len(source))
                self.assertEqual(sum(a != b for a, b in
                                     zip(source, variants["01_fingerprint_only"])), 1)
                self.assertEqual(sum(a != b for a, b in
                                     zip(source, variants["03_chassis_only"])), 2)
                main_hook = raw(profile, 0x56E07)
                direct_hook = raw(profile, 0x60052)
                no_wheels = variants["04_no_wheel_hooks"]
                self.assertEqual(no_wheels[main_hook:main_hook+5],
                                 source[main_hook:main_hook+5])
                self.assertEqual(no_wheels[direct_hook:direct_hook+5],
                                 source[direct_hook:direct_hook+5])
                no_preload = variants["05_no_preloader"]
                preload = raw(profile, PRELOAD_HOOK)
                self.assertEqual(no_preload[preload:preload+5],
                                 source[preload:preload+5])
                for blob in variants.values():
                    self.assertEqual(len(blob), len(source))

    def test_cli_selects_game_specific_default_filename(self) -> None:
        directory = Path(os.environ["ICR2_REND32A_FIXTURES"])
        for profile in PROFILES:
            filename, golden_sha = FIXTURES[profile.key]
            with self.subTest(profile=profile.key):
                with tempfile.TemporaryDirectory() as temp:
                    input_path = Path(temp) / filename
                    input_path.write_bytes((directory / filename).read_bytes())
                    self.assertEqual(main([str(input_path)]), 0)
                    output = Path(temp) / f"{profile.game}_MULTICAR.EXE"
                    self.assertEqual(sha(output.read_bytes()), golden_sha)
                    with self.assertRaisesRegex(ValueError, "already exists"):
                        main([str(input_path)])


if __name__ == "__main__":
    unittest.main()
