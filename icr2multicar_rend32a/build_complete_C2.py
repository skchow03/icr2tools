#!/usr/bin/env python3
"""Recreate the verified REND32A FOUR V2 + wheel C2 executable from a user's original CART.EXE.

Requires Python 3.10+, GNU as, ld, objcopy, unmodified CART.EXE matching ORIGINAL_SHA.
Ships source only. Writes executable in user-specified output directory.
"""
import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ORIGINAL_SHA = 'e22effeb75105a3155212eb25d88b2e2cd127d521b72d0fa122adbd32e7a721c'
EXPECTED = {
    'CART_FOUR_V2.EXE': 'a8da86b044c64c5c457fcbb865bf771dfe111ef6826d4c351d396c27d97cff40',
    'CART_FOUR_V2_WHEEL_BUILD_C_EXPERIMENTAL.EXE': '283cd32216c889f00ab8247d3823185668c8c3b66d723a95cf0a23d295718f30',
    'CART_FOUR_V2_WHEEL_BUILD_C2_ALL_CHASSIS_EXPERIMENTAL.EXE': 'cba955eab5ed03a83bebf9fa0553dca8b871e6d6405e6b5383c241a310b85be0',
}
FILES = ['build_rend32a_preload_v2.py','build_wheel_BC.py','build_C2.py','wheel_patch_bc.S']

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def run(*argv, cwd=None):
    print('+', ' '.join(map(str,argv)), flush=True)
    subprocess.run(list(map(str,argv)), cwd=cwd, check=True)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('original_exe', type=Path, help='Unmodified verified REND32A CART.EXE')
    p.add_argument('--output-dir', type=Path, default=Path('rend32a_c2_output'))
    args = p.parse_args()
    original = args.original_exe.resolve(strict=True)
    if original.stat().st_size != 1109095 or digest(original) != ORIGINAL_SHA:
        raise SystemExit('ERROR: Wrong CART.EXE. This patch supports exactly the original SHA256 '+ORIGINAL_SHA)
    for exe in ('as','ld','objcopy'):
        if shutil.which(exe) is None:
            raise SystemExit(f'ERROR: GNU binutils tool {exe!r} not found on PATH')
    source = Path(__file__).resolve().parent
    output = args.output_dir.resolve()
    output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='rend32a_build_c2_') as temporary:
        work = Path(temporary)
        for filename in FILES:
            shutil.copy2(source/filename,work/filename)
        run(sys.executable, work/'build_rend32a_preload_v2.py', original,'--output-dir',work/'preload',cwd=work)
        shutil.copy2(work/'preload'/'CART_FOUR_V2.EXE',work/'CART_FOUR_V2.EXE')
        run(sys.executable, work/'build_wheel_BC.py',cwd=work)
        run(sys.executable, work/'build_C2.py',cwd=work)
        for filename, expected in EXPECTED.items():
            candidate = work/filename
            actual = digest(candidate)
            if actual != expected:
                raise RuntimeError(f'{filename}: SHA256 mismatch expected {expected}, got {actual}; not exporting')
        for filename in EXPECTED:
            shutil.copy2(work/filename,output/filename)
        shutil.copy2(work/'CART_FOUR_V2_WHEEL_BUILD_C2_ALL_CHASSIS_EXPERIMENTAL.json',output/'C2_BUILD_MANIFEST.json')
    print('\nVerified reproducible builds:')
    for filename,expected in EXPECTED.items():
        print(f'  {filename}: {expected}')
    print('\nFINAL:', output/'CART_FOUR_V2_WHEEL_BUILD_C2_ALL_CHASSIS_EXPERIMENTAL.EXE')
    print('Copy and rename to CART.EXE ONLY in a backed-up test installation. Do not share proprietary game binaries.')

if __name__ == '__main__':
    main()
