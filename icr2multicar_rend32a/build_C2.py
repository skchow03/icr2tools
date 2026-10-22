"""Build C2 from the verified Build C executable by bypassing only the legacy chassis filter.
No change to the original FOUR V2 preloader or chassis NOP.
"""
from pathlib import Path
import argparse, hashlib, json, struct

ORIGINAL_C_SHA='283cd32216c889f00ab8247d3823185668c8c3b66d723a95cf0a23d295718f30'
FOUR_SHA='a8da86b044c64c5c457fcbb865bf771dfe111ef6826d4c351d396c27d97cff40'
STATIC=0xAB44C
SHIFT=0x3BE20
PATCH_RAW=STATIC+SHIFT
OLD=bytes.fromhex('8b 85 70 92 f6 ff')  # mov eax,[ebp-96d90h], first legacy chassis test
NEW=bytes.fromhex('eb 26 90 90 90 90')  # jmp +0x26 to 0xAB474 (validated wheel child loop)
HOOKS=[(0x1AFE7,0xAB390),(0x24232,0xAB3E0)]

def relcall(src,dst):return b'\xe8'+struct.pack('<i',dst-src-5)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build-c',type=Path,default=Path('CART_FOUR_V2_WHEEL_BUILD_C_EXPERIMENTAL.EXE'))
    p.add_argument('--four-v2',type=Path,default=Path('CART_FOUR_V2.EXE'))
    p.add_argument('--output',type=Path,default=Path('CART_FOUR_V2_WHEEL_BUILD_C2_ALL_CHASSIS_EXPERIMENTAL.EXE'))
    a=p.parse_args()
    c=a.build_c.read_bytes();four=a.four_v2.read_bytes()
    assert hashlib.sha256(c).hexdigest()==ORIGINAL_C_SHA, 'Unexpected Build C input: do not patch'
    assert hashlib.sha256(four).hexdigest()==FOUR_SHA, 'Unexpected FOUR V2 baseline: do not patch'
    assert len(c)==len(four)==1109095
    assert c[PATCH_RAW:PATCH_RAW+len(OLD)]==OLD,'Filter patch location unexpected'
    assert STATIC+2+0x26==0xAB474,'Wrong branch destination'
    assert c[0xAB474+SHIFT:0xAB478+SHIFT]==bytes.fromhex('31ff8b74'),'Wheel-child validation target changed'
    assert c[0xAB44A+SHIFT:0xAB44C+SHIFT]==bytes.fromhex('89f2'),'Root must remain in EDX'
    assert c[0xAB6E0+SHIFT:0xAB6E0+SHIFT+8]==b'ICW2\x02\x00\x00\x00'
    for site,adapter in HOOKS:
        assert c[site+SHIFT:site+SHIFT+5]==relcall(site,adapter),hex(site)
    # FOUR V2 preservation checks: chassis NOP and original texture preload bytes
    for start,end in [(0x80ACF,0x80AD1),(0x50970,0x50975),(0xE7160,0xE71AC)]:
        assert c[start:end]==four[start:end],hex(start)
    data=bytearray(c)
    data[PATCH_RAW:PATCH_RAW+len(NEW)]=NEW
    assert sum(x!=y for x,y in zip(c,data))<=6
    assert data[0xAB474+SHIFT:0xAB478+SHIFT]==bytes.fromhex('31ff8b74')
    a.output.write_bytes(data)
    result={'build':'C2 experimental: all valid nonselected chassis including legacy roadcar/indycar',
            'input_build_c_sha256':ORIGINAL_C_SHA,'four_v2_baseline_sha256':FOUR_SHA,
            'output_sha256':hashlib.sha256(data).hexdigest(),
            'size_bytes':len(data),'changed_instructions':{'guest_address':hex(STATIC),'raw_offset':hex(PATCH_RAW),'expected':OLD.hex(),'replacement':NEW.hex(),'jump_target':'0xAB474'},
            'hook_sites':['0x1AFE7','0x24232'],'diagnostic_trace_guest_address':'0xAB6E0',
            'note':'Static verification only. Experimental guest wheel writes are NOT memory guarded. No runtime tests.'}
    a.output.with_suffix('.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
