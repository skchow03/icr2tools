"""REND32A experimental multi-chassis patch through ICR2Runtime v0.12.

Locates the target from two separated function signatures in live guest memory.
Read-only unless 'on', 'off', or 'run' is explicitly selected.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
for folder in (HERE.parent / 'icr2runtime', HERE, HERE / 'icr2runtime'):
    if (folder / 'icr2_client.py').is_file() and (folder / 'runtime_launcher.py').is_file():
        sys.path.insert(0, str(folder))
        break

from icr2_client import ICR2Client, RuntimeErrorResponse
from runtime_launcher import ensure_runtime, RuntimeCapabilityError, RuntimeStartupError

VERSION = 'REND32A'
EXPECTED_RUNTIME = '0.12'
ORIGINAL = bytes.fromhex('89 02')
REPLACEMENT = bytes.fromhex('90 90')
PRELUDE = bytes.fromhex('83 c0 1c 8b 00 83 c0 0c')
TAIL_PREFIX = bytes.fromhex('8b 00')
TAIL_SUFFIX = bytes.fromhex('83 c4 04 5e 5a 59 5b c3')
TAIL_OFFSET = 0x26
PATCH_OFFSET = 0x28
SCAN_START = 0x10000
SCAN_LENGTH = 0xE0000

class WrapperError(RuntimeError):
    pass


def runtime_path(explicit):
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if not p.is_file():
            raise WrapperError(f'Runtime executable not found: {p}')
        return str(p)
    for folder in (HERE.parent / 'icr2runtime', HERE, HERE / 'icr2runtime'):
        for name in ('build/Debug/icr2runtime.exe', 'build/Release/icr2runtime.exe', 'icr2runtime.exe'):
            p = folder / name
            if p.is_file():
                return str(p)
    return None


def connect(action, exe):
    if action in ('run', 'on'):
        return ensure_runtime(runtime_path=runtime_path(exe), enable_code_writes=True)
    c = ICR2Client()
    try:
        if not c.ping():
            raise WrapperError('No responsive ICR2Runtime service')
    except OSError as exc:
        raise WrapperError('Start ICR2Runtime v0.12 first') from exc
    return c


def get_game(c, requested_pid):
    for attempt in range(2):
        games = [g for g in c.list_games() if g.version == VERSION and
                 (requested_pid is None or g.pid == requested_pid)]
        if len(games) == 1:
            return games[0]
        if games:
            raise WrapperError('Multiple REND32A games; specify --pid: ' +
                               ', '.join(str(g.pid) for g in games))
        if attempt == 0:
            c.refresh()
    raise WrapperError('No recognized REND32A game running')


def locate(c, pid):
    """Require exactly one prelude/tail pair at the exact 0x26-byte separation.

    Tail is checked with a two-byte wildcard slot so the same locator works
    when the NOP patch is active. Reject every unknown or ambiguous build.
    """
    starts = c.scan(pid, SCAN_START, SCAN_LENGTH, PRELUDE, limit=256)
    matches = []
    for head in starts:
        try:
            tail = c.read_bytes(pid, head + TAIL_OFFSET,
                                len(TAIL_PREFIX) + 2 + len(TAIL_SUFFIX))
        except (OSError, RuntimeErrorResponse):
            continue
        if not (tail.startswith(TAIL_PREFIX) and tail.endswith(TAIL_SUFFIX)):
            continue
        site = head + PATCH_OFFSET
        actual = tail[2:4]
        if actual in (ORIGINAL, REPLACEMENT):
            matches.append((site, actual))
    if len(matches) != 1:
        raise WrapperError(f'Expected one complete chassis function, found {len(matches)} '
                           f'(prelude hits: {len(starts)}); no changes made')
    return matches[0]


def tracked_record(c, pid, site):
    records = [p for p in c.list_patches() if p[0] == pid and p[1] == site]
    if len(records) > 1:
        raise WrapperError('More than one tracked patch at this address')
    if not records:
        return None
    r = records[0]
    if r[2] != 'CODE' or r[3] != ORIGINAL or r[4] != REPLACEMENT:
        raise WrapperError('Different tracked patch already occupies the target')
    return r


def inspect(c, pid):
    site, observed = locate(c, pid)
    record = tracked_record(c, pid, site)
    if observed == ORIGINAL and record is None:
        state = 'READY'
    elif observed == REPLACEMENT and record is not None:
        state = 'APPLIED_TRACKED'
    elif observed == REPLACEMENT:
        state = 'APPLIED_UNTRACKED'
    else:
        state = 'TRACKING_MISMATCH'
    return site, observed, state


def report(c, pid):
    site, actual, state = inspect(c, pid)
    print(f'REND32A PID {pid}; found live chassis instruction at 0x{site:06X}')
    print(f'Original 89 02; observed {actual.hex(" ").upper()}; state: {state}')
    print('Prelude and function-tail spacing: MATCH; wheel/tire hook: NOT installed')
    return state


def apply(c, pid):
    site, _, state = inspect(c, pid)
    if state != 'READY':
        raise WrapperError(f'Cannot enable in state {state}; requires untouched bytes')
    if 'PATCH_CODE' not in c.capabilities():
        raise WrapperError('Code writes disabled: start v0.12 with --enable-code-writes')
    c.patch_code(pid, site, ORIGINAL, REPLACEMENT)
    if inspect(c, pid)[2] != 'APPLIED_TRACKED':
        raise WrapperError('Patch reported success but readback/tracking failed; inspect with check/off')
    print(f'Experimental NOP installed at 0x{site:06X}; runtime tracks restoration.')
    return site


def restore(c, pid):
    site, _, state = inspect(c, pid)
    if state == 'READY':
        print('Already restored; no tracked patch remains.')
        return
    if state != 'APPLIED_TRACKED':
        raise WrapperError(f'Cannot safely restore in state {state}')
    c.restore(pid, site)
    if inspect(c, pid)[2] != 'READY':
        raise WrapperError('RESTORE sent but original bytes not verified')
    print(f'Restored 89 02 at 0x{site:06X}; runtime patch record removed.')


def managed(c, pid):
    if inspect(c, pid)[2] != 'READY':
        raise WrapperError('Managed run requires a READY unpatched game')
    try:
        apply(c, pid)
        print('Patch active. Examine chassis in the game. Press Ctrl+C to restore.')
        print('No wheel/tire hook; do not close game or runtime during the test.')
        while True:
            time.sleep(1)
            if inspect(c, pid)[2] != 'APPLIED_TRACKED':
                raise WrapperError('Game or patch changed while running')
    except KeyboardInterrupt:
        print('\nCtrl+C received; restoring...')
    finally:
        try:
            site, _, state = inspect(c, pid)
            if state == 'APPLIED_TRACKED':
                restore(c, pid)
            elif state != 'READY':
                raise WrapperError(f'Unable to verify safe restore: {state}')
        except Exception as exc:
            print(f'WARNING: Restoration NOT confirmed: {exc}', file=sys.stderr)
            print('Do not assume the original instruction is restored.', file=sys.stderr)
            raise


def main():
    p = argparse.ArgumentParser(description='REND32A signature-located guarded chassis experiment')
    p.add_argument('action', nargs='?', choices=['check', 'run', 'on', 'off'], default='check')
    p.add_argument('--pid', type=int)
    p.add_argument('--runtime-exe')
    a = p.parse_args()
    try:
        c = connect(a.action, a.runtime_exe)
        status = c.status()
        if status.get('version') != EXPECTED_RUNTIME:
            raise WrapperError(f'Requires v{EXPECTED_RUNTIME} runtime; got {status.get("version")!r}')
        g = get_game(c, a.pid)
        print(f'ICR2Runtime {status["version"]}; code writes: '
              f'{"ENABLED" if "PATCH_CODE" in c.capabilities() else "disabled"}')
        if a.action == 'check':
            report(c, g.pid)
        elif a.action == 'run':
            managed(c, g.pid)
        elif a.action == 'on':
            apply(c, g.pid)
        else:
            restore(c, g.pid)
        return 0
    except (WrapperError, RuntimeCapabilityError, RuntimeStartupError,
            RuntimeErrorResponse, OSError, ValueError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2

if __name__ == '__main__':
    sys.exit(main())
