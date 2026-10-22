#!/usr/bin/env python3
"""Read-only C/C2 (and B) wheel monitor for ICR2Runtime v0.13.
Auto-locates an adjacent icr2runtime folder or --runtime-dir / ICR2RUNTIME_DIR.
No host address calculations, Cheat Engine, or memory writes.
"""
from __future__ import annotations
import argparse
import os
from datetime import datetime,timezone
import json
from pathlib import Path
import struct
import sys
import time

TRACE=0xAB6E0  # REND32A guest/Ghidra address, not raw EXE offset
SIZE=56
MAGIC=b'ICW2\x02\x00\x00\x00'
MAIN=0x1AFE7
DIRECT=0x24232
MODE_AT=0xAB495
FILTER_AT=0xAB44C
ORIGINAL_FILTER=bytes.fromhex('8b857092f6ff')
C2_FILTER=bytes.fromhex('eb2690909090')
B_SIG=bytes.fromhex('8b452083f8ff7505')
C_SIG=bytes.fromhex('83ff0272088b85e3')

def site_call(site,destination):
    return b'\xe8'+struct.pack('<i',destination-site-5)

def classify(main:bytes,direct:bytes,mode:bytes,filter_code:bytes)->str:
    if (main,direct)!=(site_call(MAIN,0xAB390),site_call(DIRECT,0xAB3E0)):
        return 'OTHER: not one of these Build B/C call-site pairs'
    if mode==B_SIG:return 'B: single non-legacy car index'
    if mode==C_SIG and filter_code==ORIGINAL_FILTER:return 'C: extra chassis only; legacy Roadcar/Indycar excluded'
    if mode==C_SIG and filter_code==C2_FILTER:return 'C2: all valid nonselected chassis, including Roadcar/Indycar'
    return 'UNKNOWN: modified B/C style hooks; unrecognized probe version'

def read_trace(blob:bytes)->dict:
    if len(blob)!=SIZE or blob[:8]!=MAGIC:
        raise ValueError('ICW2 header absent or invalid; stop and confirm running executable')
    ints=struct.unpack('<12I',blob[8:])
    def index(n):return None if n==0xFFFFFFFF else n
    return {
        'main_hits':ints[0],'direct_hits':ints[1],
        'main_wheel_updates':ints[2],'direct_wheel_updates':ints[3],
        'main_invalid_pointer_or_index':ints[4],'direct_invalid_pointer_or_index':ints[5],
        'B_single_target_car_index':index(ints[6]),
        'last_successfully_updated_car_index':index(ints[7]),
        'last_updated_chassis_root':f'0x{ints[8]:08x}',
        'last_attempted_car_index':index(ints[9]),
        'main_legacy_root_skips':ints[10],'direct_legacy_root_skips':ints[11],
    }

def delta(old:int,new:int)->int:
    return (new-old)&0xFFFFFFFF

def run(client,pid,duration,interval,output,just_list):
    client.refresh()
    games=[g for g in client.list_games() if g.version=='REND32A']
    if not games:
        raise RuntimeError('No REND32A detected; start the game and ICR2Runtime v0.13')
    for g in games:
        print(f'REND32A PID {g.pid}: {g.window_title} / translation base 0x{g.translation_base:x}')
    if just_list:return 0
    if pid is None and len(games)>1:
        raise ValueError('Multiple games running; choose --pid explicitly')
    game=next((g for g in games if pid is None or g.pid==pid),None)
    if game is None:raise ValueError('Requested PID does not match a detected REND32A')
    from icr2_client import ICR2Session
    samples=[]
    with ICR2Session() as session:
        main=session.read_bytes(game.pid,MAIN,5)
        direct=session.read_bytes(game.pid,DIRECT,5)
        fingerprint=session.read_bytes(game.pid,MODE_AT,8)
        root_filter=session.read_bytes(game.pid,FILTER_AT,6)
        mode=classify(main,direct,fingerprint,root_filter)
        print(f'Loaded guest hook bytes: {main.hex()} / {direct.hex()} ; classification: {mode}')
        if not mode.startswith(('B:','C:','C2:')):
            raise RuntimeError('Unknown executable: declining to interpret memory as ICW2')
        started=time.monotonic()
        while True:
            raw=session.read_bytes(game.pid,TRACE,SIZE)
            decoded=read_trace(raw)
            elapsed=round(time.monotonic()-started,3)
            samples.append({'elapsed_seconds':elapsed,'trace':decoded,'raw_hex':raw.hex()})
            print(f'{elapsed:6.2f}s hits(main/direct) {decoded["main_hits"]}/{decoded["direct_hits"]} '
                  f'updates {decoded["main_wheel_updates"]}/{decoded["direct_wheel_updates"]} '
                  f'legacy_skips {decoded["main_legacy_root_skips"]}/{decoded["direct_legacy_root_skips"]} '
                  f'invalid {decoded["main_invalid_pointer_or_index"]}/{decoded["direct_invalid_pointer_or_index"]} '
                  f'last_updated {decoded["last_successfully_updated_car_index"]}')
            remaining=duration-(time.monotonic()-started)
            if remaining<=0:break
            time.sleep(min(interval,remaining))
    first,last=samples[0]['trace'],samples[-1]['trace']
    increments={k:delta(first[k],last[k]) for k in ['main_hits','direct_hits','main_wheel_updates','direct_wheel_updates','main_invalid_pointer_or_index','direct_invalid_pointer_or_index','main_legacy_root_skips','direct_legacy_root_skips']}
    notes=[]
    if not (increments['main_hits'] or increments['direct_hits']):
        notes.append('No hook counter changes: not evidence of invalid chassis pointers. Verify race/camera/hook first.')
    if not (increments['main_wheel_updates'] or increments['direct_wheel_updates']):
        notes.append('No newly recorded wheel writes: examine root validation, selected-car behavior, or B auto-latch.')
    if mode.startswith('B:'):
        notes.append('Build B chooses first valid non-legacy car encountered; target may not be the vehicle currently visible.')
    if mode.startswith('C2:'):
        notes.append('C2 has no legacy-chassis exclusion. Legacy skip counters should remain zero; valid wheel updates may include original Roadcar/Indycar.')
    notes.append('Positive update counter indicates the injected routine executed writes, NOT that spinning was visibly correct.')
    report={'tool':'ICR2Runtime v0.13 / ICW2 B/C monitor (read-only)','captured_utc':datetime.now(timezone.utc).isoformat(),'game_version':game.version,'pid':game.pid,'translation_base':hex(game.translation_base),'variant':mode,'trace_guest_address':hex(TRACE),'increments':increments,'samples':samples,'interpretation':notes}
    output=output or Path('wheel_BC_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.json')
    output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    output.with_suffix('.bin').write_bytes(bytes.fromhex(samples[-1]['raw_hex']))
    print('Saved:',output,'and',output.with_suffix('.bin'))
    for note in notes:print('-',note)
    return 0

def locate_runtime(explicit:Path|None,require_launcher:bool)->Path:
    """Make the ICR2Tools/icr2multicar -> ../icr2runtime layout work automatically."""
    here=Path(__file__).resolve().parent
    candidates=[]
    if explicit is not None:candidates.append(explicit)
    env=os.environ.get('ICR2RUNTIME_DIR')
    if env:candidates.append(Path(env))
    candidates.extend([
        here, here/'icr2runtime', here.parent/'icr2runtime',
        here.parent.parent/'icr2runtime', Path.cwd()/'icr2runtime',
        Path.cwd().parent/'icr2runtime',
    ])
    seen=set()
    for candidate in candidates:
        folder=candidate.expanduser().resolve()
        if folder in seen:continue
        seen.add(folder)
        if (folder/'icr2_client.py').is_file() and (not require_launcher or (folder/'runtime_launcher.py').is_file()):
            if str(folder) not in sys.path:sys.path.insert(0,str(folder))
            return folder
    needed='icr2_client.py and runtime_launcher.py' if require_launcher else 'icr2_client.py'
    raise RuntimeError(
        f'Cannot locate {needed}. Expected ICR2Tools\\icr2runtime next to '
        f'ICR2Tools\\icr2multicar. Pass --runtime-dir "C:\\path\\to\\ICR2Tools\\icr2runtime" '
        'or set ICR2RUNTIME_DIR. Install matching v0.13 Python modules from '
        'https://github.com/skchow03/icr2tools/tree/main/icr2runtime'
    )


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pid',type=int)
    p.add_argument('--seconds',type=float,default=10)
    p.add_argument('--interval',type=float,default=1)
    p.add_argument('--output',type=Path)
    p.add_argument('--list-only',action='store_true')
    p.add_argument('--launch',action='store_true',help='Start or reuse READ-ONLY runtime; no write flags')
    p.add_argument('--runtime-dir',type=Path,help='Directory containing icr2_client.py and runtime_launcher.py (default: auto-detect sibling icr2runtime)')
    a=p.parse_args()
    if not 0<=a.seconds<=600 or not 0.1<=a.interval<=60:p.error('Invalid seconds or interval')
    try:
        runtime_dir=locate_runtime(a.runtime_dir,require_launcher=a.launch)
        print('Using ICR2Runtime Python modules from:',runtime_dir)
        if a.launch:
            from runtime_launcher import ensure_runtime
            client=ensure_runtime()
        else:
            from icr2_client import ICR2Client
            client=ICR2Client()
        return run(client,a.pid,a.seconds,a.interval,a.output,a.list_only)
    except (ValueError,RuntimeError,OSError,ImportError) as exc:
        print('Diagnostic stopped:',exc,file=sys.stderr)
        print('No result about wheel models can be inferred from an unrecognized or unreadable buffer.',file=sys.stderr)
        return 3
if __name__=='__main__':raise SystemExit(main())
