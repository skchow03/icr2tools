#!/usr/bin/env python3
"""REND32A texture preload v2: EXTERNAL TEST BUILD (not tested in DOSBox).

Source: unmodified 1,109,095-byte CART.EXE, SHA256 pinned.
Corrects the previous test's code cave being OUTSIDE the LE code-object virtual size.
Expands object 1 virtual size from 0x9B301 to 0x9B500, within the same existing 156 pages
and short of object 2's base. Adds a minimal hook smoke test before THREE / FOUR tests.
"""
import argparse, hashlib, json, struct
from pathlib import Path

SIZE=1_109_095
SHA256='e22effeb75105a3155212eb25d88b2e2cd127d521b72d0fa122adbd32e7a721c'
LE=0x6E68
CODE_RAW=0x4BE20
CODE_BASE=0x10000
CODE_VIRTUAL_OLD=0x9B301
CODE_VIRTUAL_NEW=0x9B500
CODE_PAGES=0x9C
DATA_BASE=0xB0000
VIRTUAL_SIZE_AT=LE+0xC4
HOOK=0x50970
LOADER=0xA840C
CAVE=0xE7160
GEOMETRY=0x80ACF
SECOND=0x56A80


def relcall(src,target):
    return b'\xE8'+struct.pack('<i', target-(src+5))


def fixups_for_page(data,page):
    pt=LE+0x40D; rt=LE+0x71D
    a=struct.unpack_from('<I',data,pt+(page-1)*4)[0]
    b=struct.unpack_from('<I',data,pt+page*4)[0]
    rec=data[rt+a:rt+b]; p=0; out=[]
    while p<len(rec):
        first,second=rec[p:p+2]
        if (first,second)==(7,16): n=9
        elif (first,second)==(7,0): n=7
        else: raise ValueError(f'Unexpected LE relocation type on page {page}: {(first,second)}')
        if p+n>len(rec): raise ValueError('truncated fixup')
        ofs=struct.unpack_from('<H',rec,p+2)[0]
        out.append((ofs,ofs+4))
        p+=n
    return out


def assert_no_fixups(data,addr,size):
    for page in range((addr-CODE_RAW)//4096+1,(addr+size-1-CODE_RAW)//4096+2):
        pg_raw=CODE_RAW+(page-1)*4096
        for x,y in fixups_for_page(data,page):
            if max(addr,pg_raw+x)<min(addr+size,pg_raw+y):
                raise ValueError(f'Patch at {addr:#x} overlaps LE fixup on page {page}')


def validate_source(b):
    if len(b)!=SIZE or hashlib.sha256(b).hexdigest()!=SHA256:
        raise ValueError('Wrong source: use uploaded original unmodified CART.EXE (SHA256 pinned)')
    if b[LE:LE+2]!=b'LE':raise ValueError('Not an LE executable')
    assert struct.unpack_from('<6I',b,VIRTUAL_SIZE_AT)==(CODE_VIRTUAL_OLD,CODE_BASE,0x2045,1,CODE_PAGES,0)
    assert struct.unpack_from('<I',b,LE+0xC4+24+4)[0]==DATA_BASE
    assert b[HOOK-5:HOOK+5]==bytes.fromhex('B8 1C 03 00 00 E8 97 7A 05 00')
    assert b[GEOMETRY:GEOMETRY+2]==b'\x89\x02'
    assert b[SECOND:SECOND+2]==b'\x89\x10'
    assert b[LOADER:LOADER+5]==bytes.fromhex('53 52 83 EC 14')
    assert b[CAVE:CAVE+128]==bytes(128)
    for a,n in ((HOOK,5),(GEOMETRY,2),(CAVE,128)):
        assert_no_fixups(b,a,n)
    for addr in (HOOK,CAVE,LOADER):
        page=(addr-CODE_RAW)//4096
        page_id=int.from_bytes(b[LE+0xF4+page*4:LE+0xF4+page*4+3],'big')
        assert page_id==page+1
    assert CODE_BASE+CODE_VIRTUAL_NEW<DATA_BASE
    assert CAVE+128<=CODE_RAW+CODE_VIRTUAL_NEW
    assert CODE_VIRTUAL_NEW<=CODE_PAGES*4096


def make_trampoline(models):
    buf=bytearray()
    def emit(chunk):buf.extend(chunk)
    def call(dest): emit(relcall(CAVE+len(buf),dest))
    call(LOADER)                  # Preserve original Roadcar load
    if models:
        emit(b'\x60')             # pushad: includes roadcar return in EAX
        emit(b'\x83\xec\x10')  # 16 bytes of stack space
        for name in models:
            text=(name+'.3do\0').encode('ascii').ljust(12,b'\x00')
            assert len(text)==12
            emit(b'\xc7\x04\x24'+text[0:4])
            emit(b'\xc7\x44\x24\x04'+text[4:8])
            emit(b'\xc7\x44\x24\x08'+text[8:12])
            emit(b'\x8d\x04\x24')   # lea eax,[esp] -> string address
            call(LOADER)
        emit(b'\x83\xc4\x10\x61') # add esp,16; popad
    emit(b'\xc3')                  # return to post-call original function
    return bytes(buf)


def generate(b,models):
    payload=make_trampoline(models)
    assert len(payload)<=128
    out=bytearray(b)
    struct.pack_into('<I',out,VIRTUAL_SIZE_AT,CODE_VIRTUAL_NEW)
    out[GEOMETRY:GEOMETRY+2]=b'\x90\x90'
    out[HOOK:HOOK+5]=relcall(HOOK,CAVE)
    out[CAVE:CAVE+len(payload)]=payload
    assert len(out)==len(b)
    assert struct.unpack_from('<I',out,VIRTUAL_SIZE_AT)[0]==CODE_VIRTUAL_NEW
    assert out[HOOK:HOOK+5]==relcall(HOOK,CAVE)
    assert out[CAVE:CAVE+len(payload)]==payload
    assert out[SECOND:SECOND+2]==b'\x89\x10'
    allowed=set(range(VIRTUAL_SIZE_AT,VIRTUAL_SIZE_AT+4))|set(range(GEOMETRY,GEOMETRY+2))|set(range(HOOK,HOOK+5))|set(range(CAVE,CAVE+len(payload)))
    unexpected=[i for i,(x,y) in enumerate(zip(b,out)) if x!=y and i not in allowed]
    assert not unexpected
    return bytes(out),len(payload)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('original_exe',type=Path)
    parser.add_argument('--output-dir',type=Path,default=Path('rend32a_preload_v2'))
    a=parser.parse_args()
    b=a.original_exe.read_bytes(); validate_source(b)
    a.output_dir.mkdir(parents=True,exist_ok=True)
    manifest={'source':str(a.original_exe.name),'source_sha256':SHA256,
              'virtual_code_size_before':hex(CODE_VIRTUAL_OLD),
              'virtual_code_size_after':hex(CODE_VIRTUAL_NEW),
              'virtual_object_end_before':hex(CODE_RAW+CODE_VIRTUAL_OLD),
              'virtual_object_end_after':hex(CODE_RAW+CODE_VIRTUAL_NEW),
              'injection_file_offset':hex(CAVE),'tests':{}}
    for label,names in [('SMOKE',()),('THREE',('irl',)),('FOUR',('irl','panoz'))]:
        exe,size=generate(b,names)
        path=a.output_dir/f'CART_{label}_V2.EXE'
        path.write_bytes(exe)
        manifest['tests'][label]={'preload_extra_models':names,'code_length':size,'sha256':hashlib.sha256(exe).hexdigest()}
        print(f'{label}: {path.name} / {size} payload bytes / SHA256 {hashlib.sha256(exe).hexdigest()}')
    (a.output_dir/'MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Static LE checks passed. DOSBox execution UNTESTED.')

if __name__=='__main__': main()
