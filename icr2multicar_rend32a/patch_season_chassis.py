#!/usr/bin/env python3
"""Configurable REND32A chassis preloader built on the verified, working FOUR V2 + C2.

Supports either the exact original REND32A CART.EXE (requires GNU as/ld/objcopy
through bundled build_complete_C2.py), or the byte-exact C2 executable (stdlib only).

Injects a compact PIC preload loop and 16-byte name slots into *existing* mapped
LE code object 1 slack. Does not modify wheel update code. Does not include game assets.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ORIGINAL_SHA = 'e22effeb75105a3155212eb25d88b2e2cd127d521b72d0fa122adbd32e7a721c'
C2_SHA = 'cba955eab5ed03a83bebf9fa0553dca8b871e6d6405e6b5383c241a310b85be0'
EXECUTABLE_SIZE = 1109095
LE = 0x6E68
CODE_RAW = 0x4BE20
CODE_BASE = 0x10000
CODE_PAGES = 0x9C
CODE_LIMIT = CODE_RAW + CODE_PAGES * 4096
PRELOAD_HOOK = 0x50970       # ORIGINAL Roadcar loader call, raw file address
PRELOAD_NEW = 0xE7540       # begins AFTER original C2 helper+trace (0xE7538)
LOADER = 0xA840C           # original 3DO loader, raw file address
LE_VIRT = LE + 0xC4
LE_FLAGS = LE_VIRT + 8
MAIN_WHEEL_HOOK_RAW = 0x1AFE7 + 0x3BE20
DIRECT_WHEEL_HOOK_RAW = 0x24232 + 0x3BE20
GEOMETRY_RAW = 0x80ACF
NAME_SLOT = 16             # supports 8-character basenames + '.3do' + NUL
VIRTUAL_SIZE_C2 = 0x9B800
MAX_RACE_ENTRIES = 33      # cars.3do driver collection, not a theoretical chassis limit
REQUIRED_WHEEL_MAGIC = b'ICW2\x02\x00\x00\x00'

VALID_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_~!#$%&\x27()@^`{}-]{0,7}\Z')


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(b: bytes, off: int) -> int:
    return struct.unpack_from('<I', b, off)[0]


def relcall(source: int, target: int) -> bytes:
    return b'\xe8' + struct.pack('<i', target - source - 5)


def parse_name(name: str) -> str:
    if not isinstance(name, str):
        raise ValueError(f'Expected chassis basename string, got {name!r}')
    name = name.strip()
    if name.lower().endswith('.3do'):
        name = name[:-4]
    if not VALID_NAME.fullmatch(name):
        raise ValueError(f'Invalid chassis name {name!r}: use a DOS 8.3-compatible ASCII basename, 1–8 characters, no path')
    return name.lower()


def uniq(names: list[str]) -> list[str]:
    clean, found = [], set()
    for item in names:
        n = parse_name(item)
        if n not in found:
            found.add(n)
            if n not in ('roadcar', 'indycar'):
                clean.append(n)
    return clean


def parse_3do(path: Path) -> dict:
    b = path.read_bytes()
    if len(b) < 20:
        raise ValueError(f'{path}: truncated 3DO header')
    body_len, root, mi, pm, obj = struct.unpack_from('<5I', b, 0)
    total = mi + pm + obj
    header = 20 + total * 8
    if total > 300 or header + body_len != len(b) or root + 4 > body_len:
        raise ValueError(f'{path}: malformed or unsupported 3DO header')
    names = [b[20+8*i:28+8*i].split(b'\0')[0].decode('ascii') for i in range(total)]
    return dict(b=b, header=header, root=root, body_len=body_len,
                object_names=names[mi+pm:], tag=u32(b, header+root))


def casefile(folder: Path, basename: str) -> Path | None:
    # On Linux/WSL carsets copied from Windows may have uppercase filenames.
    wanted = f'{basename}.3do'.lower()
    matches = [p for p in folder.iterdir() if p.is_file() and p.name.lower() == wanted]
    if len(matches) > 1:
        raise ValueError(f'Duplicate case-folding filename in {folder}: {wanted}')
    return matches[0] if matches else None


def discover_from_carset(folder: Path) -> tuple[list[str], dict]:
    folder = folder.resolve(strict=True)
    cars_path = casefile(folder, 'cars')
    if not cars_path:
        raise ValueError(f'No cars.3do in carset folder {folder}')
    collection = parse_3do(cars_path)
    b, body, root = collection['b'], collection['header'], collection['root']
    if collection['tag'] != 0x80000010:
        raise ValueError('cars.3do root is not an F16 SUPEROBJ')
    count = u32(b, body+root+8)
    if not (1 <= count <= MAX_RACE_ENTRIES):
        raise ValueError(f'Unexpected cars.3do count {count}; current fix tested for a maximum of 33 cars')
    if root + 12 + 4*count > collection['body_len']:
        raise ValueError('cars.3do has out-of-range child array')
    drivers = []
    for i in range(count):
        c = u32(b, body+root+12+4*i)
        if c+32 > collection['body_len'] or u32(b,body+c) != 0x8000000F:
            raise ValueError(f'cars.3do child {i}: unsupported non-DYNAMIC driver entry')
        ref = struct.unpack_from('<i',b,body+c+28)[0]
        if not (-len(collection['object_names']) <= ref < 0):
            raise ValueError(f'cars.3do child {i}: invalid external reference {ref}')
        drivers.append(parse_name(collection['object_names'][-ref-1]))
    chassis, inspected = [], {}
    for driver in dict.fromkeys(drivers):
        file = casefile(folder,driver)
        if file is None:
            raise ValueError(f'Missing driver wrapper {driver}.3do (referenced by cars.3do)')
        wrapper = parse_3do(file)
        if wrapper['tag'] != 0x80000004:
            raise ValueError(f'{file.name}: unsupported wrapper root {wrapper["tag"]:#x}; use explicit --config/--chassis')
        body, root = wrapper['header'], wrapper['root']
        recolor_offset = u32(wrapper['b'],body+root+12)
        if recolor_offset + 8 > wrapper['body_len'] or u32(wrapper['b'],body+recolor_offset) != 0x8000000E:
            raise ValueError(f'{file.name}: material is not backed by expected F14 RECOLOR')
        count_recolor = u32(wrapper['b'],body+recolor_offset+4)
        tail = recolor_offset + 8 + count_recolor*8
        if tail+4 > wrapper['body_len']:
            raise ValueError(f'{file.name}: RECOLOR model slot outside data')
        ref = struct.unpack_from('<i',wrapper['b'],body+tail)[0]
        if not (-len(wrapper['object_names']) <= ref < 0):
            raise ValueError(f'{file.name}: invalid external chassis index {ref}')
        chassis_name = parse_name(wrapper['object_names'][-ref-1])
        chassis.append(chassis_name)
        inspected[driver] = chassis_name
    distinct = uniq(chassis)
    # Chassis resources are expected in the carset for deploy/test, but patch-only
    # workflows may provide them in another asset-search directory.
    missing_models = [x+'.3do' for x in distinct if casefile(folder,x) is None]
    return distinct, dict(source=str(cars_path),number_cars=count,
                          number_unique_driver_wrappers=len(inspected),
                          wrappers=inspected,missing_chassis_assets=missing_models)


def emit_payload(extra: list[str]) -> bytes:
    """Emit reloc-free i386 PIC call/loop, holding immutable names in LE code page.

    Call original Roadcar load, pushad, reserve same 16-byte local stack as
    the FOUR V2 trampoline, loop through arbitrary 16-byte filename slots,
    restore caller regs/return original loader EAX, finish with RET.
    """
    buf = bytearray()
    def emit(blob: bytes) -> None: buf.extend(blob)
    def call_loader() -> None: emit(relcall(PRELOAD_NEW+len(buf),LOADER))
    call_loader()                    # Original Roadcar load: preserve as in FOUR V2
    emit(bytes.fromhex('60 83 ec 10'))  # pushad; sub esp,16
    emit(b'\xe8\0\0\0\0')             # call next
    getpc = len(buf)
    emit(b'\x5e')                    # pop esi
    emit(b'\x8d\xb6\0\0\0\0')     # lea esi,[esi+table_address-getpc]
    delta = getpc + 3               # 4-byte LEA displacement begins here
    emit(b'\xbf' + struct.pack('<I',len(extra)))  # mov edi,count
    emit(b'\x85\xff')              # test edi,edi
    emit(b'\x74\0')                # jz done; short fixup
    exit_jump_disp = len(buf)-1
    loop = len(buf)
    emit(bytes.fromhex('56 57 89 f0'))      # push esi; push edi; mov eax,esi
    call_loader()
    emit(bytes.fromhex('5f 5e 83 c6 10 4f')) # pop edi; pop esi; add esi,16; dec edi
    emit(b'\x75\0')                # jnz loop
    back_jump_disp = len(buf)-1
    done = len(buf)
    emit(bytes.fromhex('83 c4 10 61 c3'))   # add esp,16; popad; ret
    while len(buf)%16: emit(b'\x90')
    table = len(buf)
    struct.pack_into('<i',buf,delta,table-getpc)
    for pos,target in ((exit_jump_disp,done),(back_jump_disp,loop)):
        relative = target - (pos+1)
        if relative < -128 or relative > 127:
            raise AssertionError('Unexpected short branch overflow')
        buf[pos] = relative & 0xff
    for name in extra:
        slot = (name+'.3do\0').encode('ascii')
        if len(slot)>NAME_SLOT:
            raise ValueError(f'Filename {name}.3do exceeds table slot')
        emit(slot.ljust(NAME_SLOT,b'\0'))
    assert len(buf)==table+len(extra)*NAME_SLOT
    if PRELOAD_NEW+len(buf)>CODE_LIMIT:
        raise ValueError(f'Chassis list has {len(extra)} extra names; at most 138 fit in the current LE layout')
    return bytes(buf)


def validate_c2(b:bytes) -> None:
    if len(b)!=EXECUTABLE_SIZE or sha(b)!=C2_SHA:
        raise ValueError('Input must be the exact verified C2 binary, SHA256 '+C2_SHA)
    if b[LE:LE+2]!=b'LE':
        raise ValueError('Not a DOS/32A LE executable')
    if tuple(struct.unpack_from('<6I',b,LE_VIRT))!=(VIRTUAL_SIZE_C2,CODE_BASE,0x2047,1,CODE_PAGES,0):
        raise ValueError('Unexpected LE code object layout')
    if b[PRELOAD_HOOK:PRELOAD_HOOK+5] != relcall(PRELOAD_HOOK,0xE7160):
        raise ValueError('Original FOUR V2 preload hook signature missing')
    if b[GEOMETRY_RAW:GEOMETRY_RAW+2]!=b'\x90\x90':
        raise ValueError('Chassis-preservation NOP missing')
    if b[0xE7500:0xE7508] != REQUIRED_WHEEL_MAGIC:
        raise ValueError('C2 wheel helper/diagnostic buffer signature missing')
    if b[MAIN_WHEEL_HOOK_RAW:MAIN_WHEEL_HOOK_RAW+5] != relcall(MAIN_WHEEL_HOOK_RAW,0xE71B0):
        raise ValueError('Main wheel hook missing')
    if b[DIRECT_WHEEL_HOOK_RAW:DIRECT_WHEEL_HOOK_RAW+5] != relcall(DIRECT_WHEEL_HOOK_RAW,0xE7200):
        raise ValueError('Direct wheel hook missing')
    if any(b[PRELOAD_NEW:CODE_LIMIT]):
        raise ValueError('Candidate preload cave is not empty')
    from build_rend32a_preload_v2 import assert_no_fixups
    assert_no_fixups(b,PRELOAD_NEW,CODE_LIMIT-PRELOAD_NEW)


def patch(b: bytes, extra: list[str]) -> tuple[bytes,dict]:
    validate_c2(b)
    payload = emit_payload(extra)
    new=bytearray(b)
    new[PRELOAD_NEW:PRELOAD_NEW+len(payload)]=payload
    new[PRELOAD_HOOK:PRELOAD_HOOK+5]=relcall(PRELOAD_HOOK,PRELOAD_NEW)
    new_virtual=max(VIRTUAL_SIZE_C2, ((PRELOAD_NEW+len(payload)-CODE_RAW+15)//16)*16)
    if new_virtual>CODE_PAGES*4096 or CODE_BASE+new_virtual>=0xB0000:
        raise ValueError('Requested names exceed mapped LE code pages')
    struct.pack_into('<I',new,LE_VIRT,new_virtual)
    for raw_start,raw_end in [(GEOMETRY_RAW,GEOMETRY_RAW+2),
                    (MAIN_WHEEL_HOOK_RAW,MAIN_WHEEL_HOOK_RAW+5),
                    (DIRECT_WHEEL_HOOK_RAW,DIRECT_WHEEL_HOOK_RAW+5),
                    (0xE7160,0xE71AC),(0xE71B0,0xE7538),
                    (LE_FLAGS,LE_FLAGS+4)]:
        assert new[raw_start:raw_end]==b[raw_start:raw_end],f'Modified protected C2 byte region {raw_start:#x}'
    allowed=set(range(PRELOAD_NEW,PRELOAD_NEW+len(payload)))
    allowed.update(range(PRELOAD_HOOK,PRELOAD_HOOK+5))
    allowed.update(range(LE_VIRT,LE_VIRT+4))
    differences=[i for i,(x,y) in enumerate(zip(b,new)) if x!=y]
    if not set(differences)<=allowed:
        raise AssertionError('Unanticipated binary changes detected')
    manifest={'patch':'REND32A configurable season chassis preload + unchanged C2 wheel fix',
        'input_c2_sha256':C2_SHA,'output_sha256':sha(new),'file_size':len(new),
        'extra_chassis':extra,'extra_chassis_count':len(extra),
        'builtin_loads':['roadcar','indycar'],'loader_hook_raw':hex(PRELOAD_HOOK),
        'new_loader_raw':hex(PRELOAD_NEW),'new_loader_guest':hex(PRELOAD_NEW-0x3BE20),
        'loader_raw_length':len(payload),'code_object_virtual_size':hex(new_virtual),
        'code_object_size_limit':hex(CODE_PAGES*4096),
        'le_pages_added':0,'le_relocation_records_added':0,'changed_byte_count':len(differences),
        'wheel_hook_bytes_unchanged':True,'chassis_nop_preserved':True,'original_four_v2_preloader_retained_but_bypassed':True,
        'testing_status':'static checks only; new configurable loader untested in DOSBox'}
    return bytes(new),manifest


def read_config(path:Path)->list[str]:
    data=json.loads(path.read_text(encoding='utf-8'))
    if isinstance(data,list):return data
    if not isinstance(data,dict):raise ValueError('JSON must contain a list or {"chassis":[...]}')
    names=data.get('chassis')
    if not isinstance(names,list):raise ValueError('JSON object must contain a "chassis" list')
    return names


def main(argv:list[str]|None=None)->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('exe',type=Path,help='Original verified CART.EXE or verified final FOUR V2 C2 EXE')
    p.add_argument('--config',type=Path,help='JSON {"chassis": ["irl", "panoz", ...]}')
    p.add_argument('--chassis',nargs='+',help='Additional chassis basenames, e.g. --chassis irl panoz reynard')
    p.add_argument('--carset-dir',type=Path,help='Auto-discover from cars.3do and F04/F14 driver wrappers')
    p.add_argument('--output',type=Path,default=Path('CART_SEASON_CHASSIS_C2.EXE'))
    p.add_argument('--overwrite',action='store_true',help='Allow overwriting an existing generated output (never the input EXE)')
    args=p.parse_args(argv)
    names=[]
    details={}
    if args.config:names.extend(read_config(args.config))
    if args.chassis:names.extend(args.chassis)
    if args.carset_dir:
        auto,details=discover_from_carset(args.carset_dir)
        names.extend(auto)
    if not (args.config or args.chassis or args.carset_dir):
        p.error('Supply --config, --chassis, or --carset-dir')
    names=uniq(names)
    if args.exe.resolve() == args.output.resolve():
        raise ValueError('Refusing to overwrite the source executable; choose a different --output')
    if not args.overwrite and (args.output.exists() or args.output.with_suffix('.json').exists()):
        raise ValueError('Output already exists; choose another --output or specify --overwrite')
    input_bytes=args.exe.read_bytes()
    source_hash=sha(input_bytes)
    if source_hash==ORIGINAL_SHA:
        with tempfile.TemporaryDirectory(prefix='rend32a_c2_season_') as temp:
            kit=Path(__file__).resolve().parent
            command=[sys.executable,str(kit/'build_complete_C2.py'),str(args.exe.resolve()),'--output-dir',temp]
            print('Rebuilding byte-exact C2 from original; GNU as/ld/objcopy required.',flush=True)
            subprocess.run(command,check=True)
            c2=Path(temp)/'CART_FOUR_V2_WHEEL_BUILD_C2_ALL_CHASSIS_EXPERIMENTAL.EXE'
            input_bytes=c2.read_bytes()
    elif source_hash!=C2_SHA:
        raise ValueError('Unsupported input SHA256 '+source_hash+'; requires original '+ORIGINAL_SHA+' or C2 '+C2_SHA)
    output,manifest=patch(input_bytes,names)
    manifest.update({'requested_source_sha256':source_hash,'source_discovery':details})
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_bytes(output)
    args.output.with_suffix('.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    assert sha(args.output.read_bytes())==manifest['output_sha256']
    print(f'Chassis preloaded: {", ".join(names) if names else "none beyond stock Indycar/Roadcar"}')
    print('Wrote:',args.output)
    print('SHA256:',manifest['output_sha256'])
    print('LE object 1 virtual size:',manifest['code_object_virtual_size'])
    if details.get('missing_chassis_assets'):
        print('WARNING: missing carset-local chassis files:',', '.join(details['missing_chassis_assets']))
    print('UNTESTED configurable loader; copy only to a backed-up disposable game installation.')
    return 0


if __name__=='__main__':
    try:sys.exit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as e:
        print('ERROR:',e,file=sys.stderr)
        sys.exit(1)
