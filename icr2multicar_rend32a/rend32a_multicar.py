#!/usr/bin/env python3
"""Patch a verified stock REND32A CART.EXE for independent chassis and wheel/tire models.

Source-only patch: no GNU assembler, compiler, runtime service or game assets.
The configurable chassis preloader has user-reported in-game success; broader game validation is pending.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import re
import struct
import sys
import zlib
from pathlib import Path

# Modified-byte runs for the shared chassis/wheel patch applied to stock CART.EXE.
# This is a replacement-byte patch, not a bundled copy of the game executable.
_CORE_PATCH_DELTA = (
    'c-qs+XJBArVAx>-q!}693prUCm>FKDb8_af0>zm*gBjR>0xJtS&U0}91tv^LDCA=hXLzw(=+FOz<~IVzSyVEMa`cY7sIVBP<W~SCSr~vE'
    'js_r0hM|{5<wXlnB~VpCVqQK-Rh6D`3P?fze4q+mu!>ZmismB%iHA1;g|r!7{66&a|D1$w9~GO{lO^2UoIsMb+q2{~>(2i`&<)hw9ix(B'
    'c<F`xJ)i~?hQzstC*TJ!Rzr;RFX?tu>5kLb#VA_D2lUPhW~m~Oi-9J*Py(`88De|a-eb}%0y*u!%T$g|U!CTk3jFOKEP+CN4BcDzP5t@5'
    '+oZ4c8-L4vFQ6DZL$?`-b2S9WVPj~v6X0(>6APATuH#_gZ#t9?<nS;A1q63~daVX>Om_*`rq%-`T-{Y*rsW0xmWfRe(^|VHef!_t1yjP-'
    'JpstH1S%=1H~imSvWutnTS<Mh9e-(+d-H#mqPLx)8lAo>5UJ+>Ohp{st&jKr{QsJ*yY(WF?mh+7&dAVx21p4obh^nH9ssH;X6|ND`F@=7'
    'K2VgIp@h}+DUiX<(9r2701RFhpv-5W02f0E)At*lZX(CsBp8c<;lu>Ca#eST3I{N71YV2076Qe_f0tH+*BnrmMDr1z!$4UHLUA$*h8*y8'
    '4mV;_DCJ||VE7LOI;Eie17ZOH@(A}@'
)

ORIGINAL_SHA = 'e22effeb75105a3155212eb25d88b2e2cd127d521b72d0fa122adbd32e7a721c'
CORE_PATCH_SHA = 'cba955eab5ed03a83bebf9fa0553dca8b871e6d6405e6b5383c241a310b85be0'
# A known modified REND32A executable (31 changed bytes versus the
# supported stock version). Only this exact SHA is accepted. Its changes are
# preserved in the generated EXE, but in-game compatibility is not yet verified.
ALTERNATE_SHA = '14385142e4f0b99541f018c1f20eccd854fd17103da0dfddd81472520f9c3360'
ALTERNATE_DEFAULT_SHA = 'f19aeca5a4a34a544961ae86ec575c7d7d3b17dbebf0785b061664aea1dd84d2'
# (file offset, stock bytes, alternate bytes). Some runs contain unchanged
# bytes because they represent one complete x86 instruction.
ALTERNATE_BYTE_EDITS = (
    (0x61C26, '40 ac 27 00', '00 88 f5 04'),
    (0x61F74, '40 ac 27 00', '00 88 f5 04'),
    (0x6A3C7, '40 91', '20 43'),
    (0x6BED8, '0f b6 15 78 cb 0e 00', '8b 14 95 74 cb 03 00'),
    (0x79244, '2c 15 00 00', 'd4 ea ff ff'),
    (0x79252, '60 1a', '30 22'),
    (0xABC9A, '4b 44', 'e1 cc'),
    (0xAE67E, '40 ac 27 00', '00 88 f5 04'),
    (0xF5FC0, '40 ac 27 00', '00 88 f5 04'),
)
EXECUTABLE_SIZE = 1109095
LE = 0x6E68
CODE_RAW = 0x4BE20
CODE_BASE = 0x10000
CODE_PAGES = 0x9C
CODE_LIMIT = CODE_RAW + CODE_PAGES * 4096
PRELOAD_HOOK = 0x50970       # ORIGINAL Roadcar loader call, raw file address
PRELOAD_NEW = 0xE7540       # begins after the common wheel routine and trace buffer (0xE7538)
LOADER = 0xA840C           # original 3DO loader, raw file address
LE_VIRT = LE + 0xC4
LE_FLAGS = LE_VIRT + 8
MAIN_WHEEL_HOOK_RAW = 0x1AFE7 + 0x3BE20
DIRECT_WHEEL_HOOK_RAW = 0x24232 + 0x3BE20
GEOMETRY_RAW = 0x80ACF
NAME_SLOT = 16             # supports 8-character basenames + '.3do' + NUL
CORE_VIRTUAL_SIZE = 0x9B800
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
    the injected preloader, loop through arbitrary 16-byte filename slots,
    restore caller regs/return original loader EAX, finish with RET.
    """
    buf = bytearray()
    def emit(blob: bytes) -> None: buf.extend(blob)
    def call_loader() -> None: emit(relcall(PRELOAD_NEW+len(buf),LOADER))
    call_loader()                    # Preserve the original Roadcar resource load
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


def validate_core_patch(b:bytes) -> None:
    if len(b)!=EXECUTABLE_SIZE or sha(b)!=CORE_PATCH_SHA:
        raise ValueError('Internal shared patch checksum mismatch; expected SHA256 '+CORE_PATCH_SHA)
    if b[LE:LE+2]!=b'LE':
        raise ValueError('Not a DOS/32A LE executable')
    if tuple(struct.unpack_from('<6I',b,LE_VIRT))!=(CORE_VIRTUAL_SIZE,CODE_BASE,0x2047,1,CODE_PAGES,0):
        raise ValueError('Unexpected LE code object layout')
    if b[PRELOAD_HOOK:PRELOAD_HOOK+5] != relcall(PRELOAD_HOOK,0xE7160):
        raise ValueError('Expected internal model loader signature missing')
    if b[GEOMETRY_RAW:GEOMETRY_RAW+2]!=b'\x90\x90':
        raise ValueError('Chassis-preservation NOP missing')
    if b[0xE7500:0xE7508] != REQUIRED_WHEEL_MAGIC:
        raise ValueError('Wheel updater/diagnostic buffer signature missing')
    if b[MAIN_WHEEL_HOOK_RAW:MAIN_WHEEL_HOOK_RAW+5] != relcall(MAIN_WHEEL_HOOK_RAW,0xE71B0):
        raise ValueError('Main wheel hook missing')
    if b[DIRECT_WHEEL_HOOK_RAW:DIRECT_WHEEL_HOOK_RAW+5] != relcall(DIRECT_WHEEL_HOOK_RAW,0xE7200):
        raise ValueError('Direct wheel hook missing')
    if any(b[PRELOAD_NEW:CODE_LIMIT]):
        raise ValueError('Candidate preload cave is not empty')
    assert_no_fixups(b,PRELOAD_NEW,CODE_LIMIT-PRELOAD_NEW)


def patch(b: bytes, extra: list[str]) -> tuple[bytes,dict]:
    validate_core_patch(b)
    payload = emit_payload(extra)
    new=bytearray(b)
    new[PRELOAD_NEW:PRELOAD_NEW+len(payload)]=payload
    new[PRELOAD_HOOK:PRELOAD_HOOK+5]=relcall(PRELOAD_HOOK,PRELOAD_NEW)
    new_virtual=max(CORE_VIRTUAL_SIZE, ((PRELOAD_NEW+len(payload)-CODE_RAW+15)//16)*16)
    if new_virtual>CODE_PAGES*4096 or CODE_BASE+new_virtual>=0xB0000:
        raise ValueError('Requested names exceed mapped LE code pages')
    struct.pack_into('<I',new,LE_VIRT,new_virtual)
    for raw_start,raw_end in [(GEOMETRY_RAW,GEOMETRY_RAW+2),
                    (MAIN_WHEEL_HOOK_RAW,MAIN_WHEEL_HOOK_RAW+5),
                    (DIRECT_WHEEL_HOOK_RAW,DIRECT_WHEEL_HOOK_RAW+5),
                    (0xE7160,0xE71AC),(0xE71B0,0xE7538),
                    (LE_FLAGS,LE_FLAGS+4)]:
        assert new[raw_start:raw_end]==b[raw_start:raw_end],f'Modified protected common-patch byte region {raw_start:#x}'
    allowed=set(range(PRELOAD_NEW,PRELOAD_NEW+len(payload)))
    allowed.update(range(PRELOAD_HOOK,PRELOAD_HOOK+5))
    allowed.update(range(LE_VIRT,LE_VIRT+4))
    differences=[i for i,(x,y) in enumerate(zip(b,new)) if x!=y]
    if not set(differences)<=allowed:
        raise AssertionError('Unanticipated binary changes detected')
    manifest={'patch':'REND32A Multi-Car chassis preservation, model preload and per-car wheels',
        'core_patch_sha256':CORE_PATCH_SHA,'output_sha256':sha(new),'file_size':len(new),
        'extra_chassis':extra,'extra_chassis_count':len(extra),
        'builtin_loads':['roadcar','indycar'],'loader_hook_raw':hex(PRELOAD_HOOK),
        'new_loader_raw':hex(PRELOAD_NEW),'new_loader_guest':hex(PRELOAD_NEW-0x3BE20),
        'loader_raw_length':len(payload),'code_object_virtual_size':hex(new_virtual),
        'code_object_size_limit':hex(CODE_PAGES*4096),
        'le_pages_added':0,'le_relocation_records_added':0,'changed_byte_count':len(differences),
        'wheel_hook_bytes_unchanged':True,'chassis_nop_preserved':True,'inactive_preloader_retained_but_bypassed':True,
        'testing_status':'user-reported successful in-game test; broader regression coverage remains pending'}
    return bytes(new),manifest


def read_config(path:Path)->list[str]:
    data=json.loads(path.read_text(encoding='utf-8'))
    if isinstance(data,list):return data
    if not isinstance(data,dict):raise ValueError('JSON must contain a list or {"chassis":[...]}')
    names=data.get('chassis')
    if not isinstance(names,list):raise ValueError('JSON object must contain a "chassis" list')
    return names


def fixups_for_page(data: bytes, page: int) -> list[tuple[int, int]]:
    pt, rt = LE + 0x40D, LE + 0x71D
    start = u32(data, pt + (page - 1) * 4)
    end = u32(data, pt + page * 4)
    records = data[rt + start:rt + end]
    pos, result = 0, []
    while pos < len(records):
        if pos + 4 > len(records):
            raise ValueError("Truncated LE relocation")
        kind = tuple(records[pos:pos + 2])
        if kind == (7, 16): length = 9
        elif kind == (7, 0): length = 7
        else: raise ValueError(f"Unexpected LE relocation type: {kind}")
        if pos + length > len(records):
            raise ValueError("Truncated LE relocation record")
        off = struct.unpack_from("<H", records, pos + 2)[0]
        result.append((off, off + 4))
        pos += length
    return result


def assert_no_fixups(data: bytes, addr: int, size: int) -> None:
    for page in range((addr - CODE_RAW) // 4096 + 1,
                      (addr + size - 1 - CODE_RAW) // 4096 + 2):
        page_start = CODE_RAW + (page - 1) * 4096
        for a, b in fixups_for_page(data, page):
            if max(addr, page_start + a) < min(addr + size, page_start + b):
                raise ValueError(f"Patch overlaps LE relocation on page {page}")


def normalize_supported_input(source: bytes) -> tuple[bytes, bool]:
    """Validate a known input exactly and reconstruct the canonical stock bytes.

    The current common patch checksum is pinned to stock CART.EXE. When the
    known alternate is supplied, revert only its nine documented edit runs
    in memory; after generating the Multi-Car output, reinstate those edits.
    The source file on disk is never modified.
    """
    if len(source) != EXECUTABLE_SIZE:
        raise ValueError("Unsupported REND32A CART.EXE size")
    digest = sha(source)
    if digest == ORIGINAL_SHA:
        return source, False
    if digest != ALTERNATE_SHA:
        raise ValueError(
            "Unsupported REND32A CART.EXE SHA256: " + digest +
            ". Supported: stock " + ORIGINAL_SHA + ", alternate " + ALTERNATE_SHA
        )
    canonical = bytearray(source)
    for offset, stock_hex, variant_hex in ALTERNATE_BYTE_EDITS:
        stock, variant = bytes.fromhex(stock_hex), bytes.fromhex(variant_hex)
        if len(stock) != len(variant):
            raise ValueError("Invalid variant edit size at " + hex(offset))
        if canonical[offset:offset + len(variant)] != variant:
            raise ValueError("Alternate executable differs at " + hex(offset))
        canonical[offset:offset + len(stock)] = stock
    if sha(canonical) != ORIGINAL_SHA:
        raise ValueError("Alternate executable failed canonical SHA256 verification")
    return bytes(canonical), True


def reapply_alternate_edits(output: bytes) -> bytes:
    """Preserve all of the alternate's changed bytes; fail on any overlap."""
    modified = bytearray(output)
    for offset, stock_hex, variant_hex in ALTERNATE_BYTE_EDITS:
        stock, variant = bytes.fromhex(stock_hex), bytes.fromhex(variant_hex)
        if modified[offset:offset + len(stock)] != stock:
            raise ValueError("Multi-Car conflicts with alternate edit at " + hex(offset))
        modified[offset:offset + len(variant)] = variant
    return bytes(modified)


def reconstruct_core_patch(source: bytes) -> bytes:
    if len(source) != EXECUTABLE_SIZE or sha(source) != ORIGINAL_SHA:
        raise ValueError("Unsupported CART.EXE version. Expected the unmodified "
                         "1,109,095-byte REND32A executable; SHA256: " + ORIGINAL_SHA)
    delta = zlib.decompress(base64.b85decode("".join(_CORE_PATCH_DELTA)))
    output = bytearray(source)
    at = 0
    last_end = 0
    while at < len(delta):
        if len(delta) - at < 6:
            raise ValueError("Damaged embedded patch data")
        offset, count = struct.unpack_from("<IH", delta, at)
        at += 6
        if offset < last_end or offset + count > len(output) or at + count > len(delta):
            raise ValueError("Damaged embedded patch range")
        output[offset:offset + count] = delta[at:at + count]
        at += count
        last_end = offset + count
    output = bytes(output)
    if sha(output) != CORE_PATCH_SHA:
        raise ValueError("Reconstructed chassis/wheel patch failed SHA256 verification")
    return output



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Patch an original REND32A CART.EXE for multiple chassis.")
    parser.add_argument("exe", type=Path, help="Your unmodified REND32A CART.EXE")
    options = parser.add_mutually_exclusive_group()
    options.add_argument("--carset-dir", type=Path, help="Folder containing cars.3do and driver wrappers (auto-detect)")
    options.add_argument("--chassis", nargs="+", help="Chassis names, e.g. irl panoz reynard")
    options.add_argument("--config", type=Path, help="JSON file containing chassis names")
    parser.add_argument("--output", type=Path, help="Output EXE (default: CART_MULTICAR.EXE next to input)")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite an existing generated output, never original")
    args = parser.parse_args(argv)
    source = args.exe.resolve(strict=True)
    output = (args.output or source.with_name("CART_MULTICAR.EXE")).resolve()
    if source == output:
        raise ValueError("Refusing to overwrite original CART.EXE")
    if output.exists() and not args.overwrite:
        raise ValueError(f"{output.name} already exists; use --overwrite or --output")

    details = {}
    if args.carset_dir:
        names, details = discover_from_carset(args.carset_dir)
    elif args.chassis:
        names = uniq(args.chassis)
    elif args.config:
        names = uniq(read_config(args.config))
    else:
        names = ["irl", "panoz"]
        print("Using default additional chassis: irl, panoz. "
              "Use --carset-dir or --chassis for another season.")

    print("Checking original CART.EXE...")
    original_bytes, is_alternate = normalize_supported_input(source.read_bytes())
    if is_alternate:
        print("Recognized modified REND32A variant; preserving its existing changes.")
        print("CAUTION: Combined output for this variant has not been tested in-game.")
    core_patch = reconstruct_core_patch(original_bytes)
    patched, manifest = patch(core_patch, names)
    if is_alternate:
        patched = reapply_alternate_edits(patched)
        manifest['output_sha256'] = sha(patched)
        if names == ['irl', 'panoz'] and sha(patched) != ALTERNATE_DEFAULT_SHA:
            raise ValueError('Unexpected alternate output checksum')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(patched)
    if sha(output.read_bytes()) != manifest["output_sha256"]:
        raise ValueError("Written output failed verification")
    print("Generated:", output)
    print("Additional chassis:", ", ".join(names) if names else "(none)")
    print("SHA256:", manifest["output_sha256"])
    if details.get("missing_chassis_assets"):
        print("WARNING: Missing chassis 3DO files:", ", ".join(details["missing_chassis_assets"]))
    print("Experimental: Developer reports in-game success; broader compatibility remains unverified.")
    print("Keep the original. Copy generated file as CART.EXE only into a backed-up test installation.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, zlib.error) as exc:
        print("ERROR:", exc, file=sys.stderr)
        sys.exit(1)
