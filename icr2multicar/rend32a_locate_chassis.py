"""Read-only REND32A chassis-code locator for ICR2Runtime v0.12.

Run from the ICR2Tools root:
    python icr2multicar\\rend32a_locate_chassis.py
No write commands are issued, regardless of runtime write permissions.
"""
from __future__ import annotations

from pathlib import Path
import sys

here = Path(__file__).resolve().parent
for folder in (here.parent / 'icr2runtime', here, here / 'icr2runtime'):
    if (folder / 'icr2_client.py').is_file():
        sys.path.insert(0, str(folder))
        break
from icr2_client import ICR2Client

OLD_PRELUDE = 0x44C87
OLD_PATCH = 0x44CAF
PRELUDE = bytes.fromhex('83 c0 1c 8b 00 83 c0 0c')
TAIL = bytes.fromhex('8b 00 89 02 83 c4 04 5e 5a 59 5b c3')
# The tail begins at +0x26 from the prelude; the two-byte site is +0x28.
TAIL_OFFSET = 0x26
PATCH_OFFSET = 0x28
SCAN_START = 0x10000
SCAN_LENGTH = 0xE0000


def main():
    c = ICR2Client()
    games = [g for g in c.list_games() if g.version == 'REND32A']
    if len(games) != 1:
        raise RuntimeError(f'Expected one REND32A game; found {len(games)}. ' +
                           ', '.join(str(g.pid) for g in games))
    g = games[0]
    print(f'REND32A PID {g.pid}; runtime {c.status().get("version")}; read-only locator')
    print(f'Old expected address 0x{OLD_PRELUDE:06X}: ' +
          c.read_bytes(g.pid, OLD_PRELUDE, 8).hex(' '))
    print('Scanning for unique eight-byte function prelude ...')
    heads = c.scan(g.pid, SCAN_START, SCAN_LENGTH, PRELUDE, limit=64)
    print('Prelude hits:', [f'0x{x:06X}' for x in heads])
    print('Scanning independently for twelve-byte function tail ...')
    tails = c.scan(g.pid, SCAN_START, SCAN_LENGTH, TAIL, limit=64)
    print('Tail hits:', [f'0x{x:06X}' for x in tails])
    tail_set = set(tails)
    consistent = []
    for head in heads:
        if head + TAIL_OFFSET in tail_set:
            candidate = head + PATCH_OFFSET
            context = c.read_bytes(g.pid, head, 0x31)
            consistent.append(candidate)
            print(f'CONSISTENT FUNCTION: prelude 0x{head:06X}, '
                  f'tail 0x{head + TAIL_OFFSET:06X}, patch 0x{candidate:06X}')
            print('  Candidate bytes:', c.read_bytes(g.pid, candidate, 2).hex(' '))
            print('  Live instruction window:', context.hex(' '))
            print(f'  Displacement from previous estimate: {head - OLD_PRELUDE:+#x}')
    if len(consistent) == 1:
        print('ONE MATCHING FUNCTION FOUND. Do not patch yet; share this output.')
    elif not consistent:
        print('NO CONSISTENT FUNCTION FOUND. Do not patch; share this output.')
    else:
        print('MULTIPLE MATCHES FOUND. Do not patch; share this output.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        raise SystemExit(1)
