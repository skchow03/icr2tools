#!/usr/bin/env python3
"""Reproducibly build TWO untested, REND32A-native per-draw wheel patch experiments.
Requires GNU binutils (as/ld/objcopy); no game execution or Windows memory writes.
"""
from pathlib import Path
import hashlib, json, struct, subprocess
from build_rend32a_preload_v2 import assert_no_fixups, fixups_for_page

ROOT=Path(__file__).resolve().parent
BASE=ROOT/'CART_FOUR_V2.EXE'
BASE_SHA='a8da86b044c64c5c457fcbb865bf771dfe111ef6826d4c351d396c27d97cff40'
LE=0x6e68
SHIFT=0x3be20
CAVE=0xe71b0
NEW_VIRT=0x9b800
STATIC_CAVE=0xab390
STATIC_TRACE=0xab6e0
TRACE_RAW=STATIC_TRACE+SHIFT
SIZE=56
FLAGS=LE+0xc4+8
MAIN=0x1afe7
DIRECT=0x24232

def relcall(src,dst):return b'\xe8'+struct.pack('<i',dst-src-5)

def check_fixup(b,static_operand):
    raw=static_operand+SHIFT
    page=(raw-0x4be20)//4096+1
    at=raw-(0x4be20+(page-1)*4096)
    assert any(a<=at and at+4<=z for a,z in fixups_for_page(b,page)), hex(static_operand)

def assemble(label):
    obj=ROOT/f'patch_{label}.o'
    elf=ROOT/f'patch_{label}.elf'
    raw=ROOT/f'patch_{label}.bin'
    args=['as','--32']
    if label=='B':args+=['--defsym','SINGLE=1']
    subprocess.run(args+['-o',str(obj),str(ROOT/'wheel_patch_bc.S')],check=True)
    subprocess.run(['ld','-m','elf_i386',f'-Ttext={STATIC_CAVE:#x}','-e','hook_main','-o',str(elf),str(obj)],check=True)
    subprocess.run(['objcopy','-O','binary','--only-section=.text',str(elf),str(raw)],check=True)
    return raw.read_bytes()

def main():
    src=BASE.read_bytes()
    assert len(src)==1_109_095 and hashlib.sha256(src).hexdigest()==BASE_SHA,'wrong FOUR V2 baseline'
    assert src[LE:LE+2]==b'LE'
    assert struct.unpack_from('<6I',src,LE+0xc4)==(0x9b500,0x10000,0x2045,1,0x9c,0)
    assert NEW_VIRT<=0x9c000 and 0x10000+NEW_VIRT<0xb0000
    assert struct.unpack_from('<I',src,LE+0xc4+24+4)[0]==0xb0000
    assert src[0xe7160:0xe71ac]!=bytes(0x4c)
    assert src[0x80acf:0x80ad1]==b'\x90\x90'
    assert src[CAVE:0xe7620]==bytes(0xe7620-CAVE),'code cave overlaps existing payload'
    assert_no_fixups(src,CAVE,0xe7620-CAVE)
    for addr in [MAIN,DIRECT]:
        assert src[addr+SHIFT:addr+SHIFT+5]==relcall(addr,0x47690)
        assert_no_fixups(src,addr+SHIFT,5)
    # All five PIC lookup operands refer to *original loader-relocated* absolute address operands.
    for addr in [0x44c9e,0x14950,0x1496b,0x476b1,0x476c3]:check_fixup(src,addr)
    results={}
    for label in ('B','C'):
        payload=assemble(label)
        assert len(payload)==904
        assert payload[0:5]==relcall(STATIC_CAVE,0x47690),'main adapter must call original tire selector'
        assert payload[0x50:0x55]==relcall(STATIC_CAVE+0x50,0x47690),'direct adapter must call original tire selector'
        assert payload[0x350:0x358]==b'ICW2\x02\x00\x00\x00','trace buffer lost'
        assert struct.unpack_from('<I',payload,0x350+0x20)[0]==0xffffffff
        assert struct.unpack_from('<I',payload,0x350+0x24)[0]==0xffffffff
        assert len(payload)<=NEW_VIRT-(CAVE-0x4be20)
        result=bytearray(src)
        struct.pack_into('<I',result,LE+0xc4,NEW_VIRT)
        struct.pack_into('<I',result,FLAGS,0x2047)
        result[CAVE:CAVE+len(payload)]=payload
        result[MAIN+SHIFT:MAIN+SHIFT+5]=relcall(MAIN,STATIC_CAVE)
        result[DIRECT+SHIFT:DIRECT+SHIFT+5]=relcall(DIRECT,STATIC_CAVE+0x50)
        assert result[0xe7160:0xe71ac]==src[0xe7160:0xe71ac]
        assert result[0x50970:0x50975]==src[0x50970:0x50975]
        assert result[0x80acf:0x80ad1]==src[0x80acf:0x80ad1]
        assert len(result)==len(src)
        permitted=set(range(CAVE,CAVE+len(payload)))
        for a in [MAIN,DIRECT]:permitted.update(range(a+SHIFT,a+SHIFT+5))
        permitted.update(range(LE+0xc4,LE+0xc8))
        permitted.update(range(FLAGS,FLAGS+4))
        diffs=[i for i,(a,b) in enumerate(zip(src,result)) if a!=b]
        assert set(diffs)<=permitted,hex(next(iter(set(diffs)-permitted))) if set(diffs)-permitted else ''
        name=f'CART_FOUR_V2_WHEEL_BUILD_{label}_EXPERIMENTAL.EXE'
        (ROOT/name).write_bytes(result)
        results[label]={'name':name,'sha256':hashlib.sha256(result).hexdigest(),'file_size':len(result),'diff_count':len(diffs),'mode':('first valid non-legacy chassis, one car index latched' if label=='B' else 'all valid non-legacy chassis for each draw')}
        print(label,results[label])
    assert results['B']['sha256']!=results['C']['sha256']
    manifest={'date':'2026-10-18','status':'static build only; NOT game-tested','baseline_sha256':BASE_SHA,'exe_size':len(src),'virt_before':'0x9B500','virt_after':hex(NEW_VIRT),'code_page_count_unchanged':156,'code_flags_before':'0x2045','code_flags_after':'0x2047','new_code_static':'0xAB390','new_code_raw':hex(CAVE),'new_code_length':904,'trace_address_ghidra':hex(STATIC_TRACE),'trace_length':SIZE,'trace_magic':'ICW2','hook_main':hex(MAIN),'hook_direct':hex(DIRECT),'relocated_operands_verified':[hex(x) for x in [0x44c9e,0x14950,0x1496b,0x476b1,0x476c3]],'known_risks':['guest pointer dereferences remain unvalidated in DOSBox','code-object write permission change may fail','selected-car wheel path is intentionally excluded','one model resource may be shared among different cars','model root table entries may be temporarily replaced during damage'], 'builds':results}
    (ROOT/'WHEEL_BC_MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')

if __name__=='__main__': main()
