#!/usr/bin/env python3
"""Regression tests for the DOS/4GW Rendition multi-car patcher.

The normal unit tests need no commercial files. To run binary golden tests,
set ICR2_DOS4GW_FIXTURES to a directory containing the two supported
IncreasedHeapSize original EXEs listed in FIXTURES. They are intentionally not distributed in this repository.
"""
from __future__ import annotations

import os
import struct
import tempfile
import unittest
from pathlib import Path

from dos4gw_multicar import (
    CODE_LIMIT, LE_VIRT, PRELOAD_HOOK, PRELOAD_NEW, PROFILES,
    emit_payload, identify_profile, main, patch, raw, reconstruct_core_patch,
    relcall, sha, validate_core_patch,
)


FIXTURES = {
    "increasedheap_cart": ("ICR2.IncreasedHeapSize_CART.EXE",
                           "5cb3ee72f261f256249cd316b3c0425ba37539e021916783ee62eb7c194defe8"),
    "increasedheap_indycar": ("ICR2.IncreasedHeapSize_INDYCAR.EXE",
                             "fa43698f2362c92090cfc2216868ce9bdb094ed05992eb18bb5a004c122c7799"),
}

# Optional negative fixtures, when present in the same test directory. These
# binaries must remain rejected even if their previously supported fingerprints
# still match. They are not required for the positive golden regression tests.
EXCLUDED_FIXTURES = {
    "CART(1).EXE": "e22effeb75105a3155212eb25d88b2e2cd127d521b72d0fa122adbd32e7a721c",
    "ICRWide.20260722001_CART.EXE": "d3329cde896725066436a20f4f67bf9c70fed59db1bc9947f3f3a5aa0d78889d",
    "ICRWide.20260722001_INDYCAR.EXE": "2a97bf1f1d04201eeef144031851a2f35f38b7309c636ad421c1084572d562c3",
}


class ProfileTests(unittest.TestCase):
    def test_unique_and_consistent_profiles(self) -> None:
        self.assertEqual(len(PROFILES), 2)
        self.assertEqual({p.key for p in PROFILES}, set(FIXTURES))
        self.assertEqual(len({p.input_sha256 for p in PROFILES}), 2)
        for profile in PROFILES:
            with self.subTest(profile=profile.key):
                self.assertIn(profile.game, ("CART", "INDYCAR"))
                self.assertTrue(profile.key.startswith("increasedheap_"))
                self.assertEqual(profile.file_shift, 0x21E34)
                self.assertEqual(profile.size, 1247899)
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


@unittest.skipUnless(os.environ.get("ICR2_DOS4GW_FIXTURES"),
                     "Set ICR2_DOS4GW_FIXTURES for binary regression tests")
class ExecutableGoldenTests(unittest.TestCase):
    def test_excluded_original_builds_are_rejected(self) -> None:
        directory = Path(os.environ["ICR2_DOS4GW_FIXTURES"])
        for filename, expected_sha in EXCLUDED_FIXTURES.items():
            path = directory / filename
            if not path.is_file():
                continue
            with self.subTest(excluded=filename):
                source = path.read_bytes()
                self.assertEqual(sha(source), expected_sha)
                with self.assertRaisesRegex(ValueError, "Unsupported"):
                    identify_profile(source)

    def test_every_profile_against_uploaded_fixture_hashes(self) -> None:
        directory = Path(os.environ["ICR2_DOS4GW_FIXTURES"])
        for profile in PROFILES:
            filename, expected_final_sha = FIXTURES[profile.key]
            with self.subTest(profile=profile.key):
                source = (directory / filename).read_bytes()
                self.assertEqual(len(source), profile.size)
                self.assertEqual(sha(source), profile.input_sha256)
                self.assertEqual(identify_profile(source), profile)
                mutated = bytearray(source)
                mutated[-1] ^= 1
                with self.assertRaisesRegex(ValueError, "Unsupported"):
                    identify_profile(bytes(mutated))
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

    def test_cli_selects_game_specific_default_filename(self) -> None:
        directory = Path(os.environ["ICR2_DOS4GW_FIXTURES"])
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
