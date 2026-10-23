#!/usr/bin/env python3
"""Create controlled diagnostic EXEs for the ICRWide viewport regression.

Requires the unmodified ICRWide CART or INDYCAR executable and the multi-car
patcher in this directory. All output files are experimental, intended for
isolated, backed-up test installations, and are never distributed by the repo.
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

from rend32a_multicar import (
    LE_FLAGS, LE_VIRT, PRELOAD_NEW, PRELOAD_HOOK, MAIN_WHEEL_HOOK_RAW,
    DIRECT_WHEEL_HOOK_RAW, GEOMETRY_RAW, identify_profile, raw, sha,
    reconstruct_core_patch, patch,
)


def variants(source: bytes, profile) -> dict[str, bytes]:
    if not profile.key.startswith('icrwide_'):
        raise ValueError('This diagnostic tool is only for the two verified ICRWide builds')
    core = reconstruct_core_patch(source, profile)
    full, _ = patch(core, ['irl', 'panoz'], profile)
    results = {}

    # The zero-filled location is beyond the original code object's virtual
    # size; this changes the file fingerprint without modifying live code.
    marker = raw(profile, PRELOAD_NEW)
    if source[marker] != 0:
        raise ValueError('Expected unused fingerprint probe byte is not zero')
    probe = bytearray(source)
    probe[marker] = 0x90
    results['01_fingerprint_only'] = bytes(probe)

    # These header changes are the only metadata modifications made by the
    # multi-car patch; the rest of this variant remains completely stock.
    header = bytearray(source)
    struct.pack_into('<I', header, raw(profile, LE_VIRT), 0x9B800)
    struct.pack_into('<I', header, raw(profile, LE_FLAGS), 0x2047)
    results['02_header_only'] = bytes(header)

    geometry = bytearray(source)
    site = raw(profile, GEOMETRY_RAW)
    if geometry[site:site+2] != b'\x89\x02':
        raise ValueError('Unexpected stock geometry instruction')
    geometry[site:site+2] = b'\x90\x90'
    results['03_chassis_only'] = bytes(geometry)

    def restore_sites(blob: bytes, sites: tuple[int, ...]) -> bytes:
        out = bytearray(blob)
        for canonical_site in sites:
            offset = raw(profile, canonical_site)
            out[offset:offset+5] = source[offset:offset+5]
        return bytes(out)

    results['04_no_wheel_hooks'] = restore_sites(
        full, (MAIN_WHEEL_HOOK_RAW, DIRECT_WHEEL_HOOK_RAW))
    results['05_no_preloader'] = restore_sites(full, (PRELOAD_HOOK,))
    results['06_neither_hook'] = restore_sites(
        full, (MAIN_WHEEL_HOOK_RAW, DIRECT_WHEEL_HOOK_RAW, PRELOAD_HOOK))
    # Preload Roadcar only; there are no additional 3DO model loads. All wheel
    # hooks and geometry-preservation logic remain enabled.
    results['07_no_extra_chassis'] = patch(core, [], profile)[0]
    results['08_full_multicar'] = full

    if any(len(blob) != len(source) for blob in results.values()):
        raise AssertionError('Diagnostic output unexpectedly changed file length')
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('exe', type=Path, help='Unmodified, verified ICRWide executable')
    parser.add_argument('--output-dir', type=Path, help='Diagnostic directory next to EXE by default')
    parser.add_argument('--overwrite', action='store_true')
    args = parser.parse_args()
    source_path = args.exe.resolve(strict=True)
    source = source_path.read_bytes()
    profile = identify_profile(source)
    if not profile.key.startswith('icrwide_'):
        parser.error('Expected an original ICRWide (20260722001) input EXE')
    target = (args.output_dir or source_path.parent / 'icrwide_diagnostics').resolve()
    created = variants(source, profile)
    for name, blob in created.items():
        output = target / name / f'{profile.game}.EXE'
        if output == source_path:
            raise ValueError('Refusing to overwrite original input')
        if output.exists() and not args.overwrite:
            raise ValueError(f'Already exists: {output} (use --overwrite)')
    for name, blob in created.items():
        output = target / name / f'{profile.game}.EXE'
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(blob)
        if sha(output.read_bytes()) != sha(blob):
            raise ValueError(f'Failed output verification: {output}')
        print(f'{name:<26} SHA256 {sha(blob)}')
    print(f'Saved under: {target}')
    print('Use one executable at a time in a separate, backed-up game installation.')
    print('The first (fingerprint-only) output tests whether the wrapper requires an exact EXE hash.')
    print('The hook-disabled outputs may lack custom chassis and accurate wheel animation.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as exc:
        raise SystemExit(f'ERROR: {exc}') from exc
