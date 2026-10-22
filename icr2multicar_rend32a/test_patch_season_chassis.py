"""Static tests: do NOT execute DOSBox or change a game installation."""
from __future__ import annotations
import hashlib
import os
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

import patch_season_chassis as p

BASE_PATH = Path(__file__).resolve().parent
TEST_C2 = (BASE_PATH / 'test_input_C2.EXE')
if not TEST_C2.is_file():
    TEST_C2 = Path('/mnt/data/community_C2_repro_check/CART_FOUR_V2_WHEEL_BUILD_C2_ALL_CHASSIS_EXPERIMENTAL.EXE')


@unittest.skipUnless(TEST_C2.is_file(), 'Copy verified C2 EXE to test_input_C2.EXE for executable-level tests')
class TestPatchBinary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c2 = TEST_C2.read_bytes()
        assert p.sha(cls.c2)==p.C2_SHA

    def test_list_7_names(self):
        names=p.uniq(['IRL.3DO','panoz','dallara','reynard','lola','penske','swift'])
        out,m=p.patch(self.c2,names)
        self.assertEqual(m['extra_chassis_count'],7)
        self.assertEqual(len(out),len(self.c2))
        self.assertEqual(out[p.PRELOAD_HOOK:p.PRELOAD_HOOK+5],p.relcall(p.PRELOAD_HOOK,p.PRELOAD_NEW))
        self.assertEqual(out[p.GEOMETRY_RAW:p.GEOMETRY_RAW+2],b'\x90\x90')
        self.assertEqual(out[0xe71b0:0xe7538],self.c2[0xe71b0:0xe7538])
        self.assertEqual(out[0xe7160:0xe71ac],self.c2[0xe7160:0xe71ac])
        offset=p.PRELOAD_NEW+64
        for i,n in enumerate(names):
            slot=out[offset+i*16:offset+(i+1)*16]
            self.assertEqual(slot.split(b'\0',1)[0].decode('ascii'),n+'.3do')
        self.assertTrue(all(x==0 for x in out[p.PRELOAD_NEW+len(p.emit_payload(names)):p.CODE_LIMIT]))

    def test_expand_code_virtual_size(self):
        names=[f'm{i:07d}' for i in range(130)]
        out,m=p.patch(self.c2,names)
        size=p.u32(out,p.LE_VIRT)
        self.assertGreater(size,p.VIRTUAL_SIZE_C2)
        self.assertEqual(out[p.LE_FLAGS:p.LE_FLAGS+4],self.c2[p.LE_FLAGS:p.LE_FLAGS+4])
        self.assertLessEqual(size,0x9c000)
        self.assertEqual(m['extra_chassis_count'],130)

    def test_zero_and_max(self):
        out,m=p.patch(self.c2,[])
        self.assertEqual(m['extra_chassis_count'],0)
        self.assertEqual(out[p.PRELOAD_NEW+21:p.PRELOAD_NEW+28],bytes.fromhex('bf0000000085ff'))
        names=[f'm{i:07d}' for i in range(138)]
        out,m=p.patch(self.c2,names)
        self.assertEqual(p.u32(out,p.LE_VIRT),0x9c000)
        self.assertEqual(p.PRELOAD_NEW+len(p.emit_payload(names)),p.CODE_LIMIT)
        with self.assertRaisesRegex(ValueError,'at most 138'):
            p.patch(self.c2,names+['overcap'])

    def test_bad_baseline_rejected(self):
        with self.assertRaisesRegex(ValueError,'exact verified C2'):
            p.patch(bytes(len(self.c2)),['irl'])


class TestInputSanitization(unittest.TestCase):
    def test_names_and_builtin_dedup(self):
        self.assertEqual(p.uniq(['ROADCAR','indycar.3do','IRL','irl.3do','PANOZ']),['irl','panoz'])
        self.assertEqual(p.parse_name('ABCD1234.3DO'),'abcd1234')
        for bad in ('9letterss','../escape','.','subfolder/car','name with spaces','éxample','', 'name.3do.exe'):
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                p.parse_name(bad)

    def test_pic_loader_structure(self):
        code=p.emit_payload(['irl','panoz'])
        self.assertEqual(code[:5],p.relcall(p.PRELOAD_NEW,p.LOADER))
        self.assertEqual(code[5:9],bytes.fromhex('60 83 ec 10'))
        self.assertEqual(code[9:15],bytes.fromhex('e8 00 00 00 00 5e'))
        disp=struct.unpack_from('<i',code,17)[0]
        self.assertEqual(14+disp,64)
        self.assertEqual(code[21:26],bytes.fromhex('bf02000000'))
        self.assertEqual(code[47:52],bytes.fromhex('83c41061c3'))
        self.assertEqual(code[64:80].split(b'\0',1)[0],b'irl.3do')

    def test_config_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=Path(tmp)/'a.json'
            a.write_text('{"chassis":["irl","panoz"]}')
            self.assertEqual(p.uniq(p.read_config(a)),['irl','panoz'])
            a.write_text('["lola","reynard"]')
            self.assertEqual(p.read_config(a),['lola','reynard'])

    def test_carset_33_wrappers(self):
        source=Path(os.getenv('ICR2_TEST_ASSETS_DIR','/mnt/data'))
        if not (source/'cars.3do').is_file() or not (source/'cit74.3do').is_file():
            self.skipTest('Project 3DO files not mounted')
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            shutil.copy2(source/'cars.3do', folder/'CARS.3DO')
            collection=p.parse_3do(folder/'CARS.3DO')
            drivers=collection['object_names']
            for driver in drivers:
                name=p.parse_name(driver)
                wrapper=bytearray((source/'cit74.3do').read_bytes())
                # Header contains the first 8-byte external reference, Indycar.
                original_offset=wrapper.index(b'indycar')
                if name == 'cit74':
                    wrapper[original_offset:original_offset+8]=b'irl\0\0\0\0\0'
                elif name == 'ind95':
                    wrapper[original_offset:original_offset+8]=b'panoz\0\0\0'
                (folder/(name+'.3do')).write_bytes(wrapper)
            shutil.copy2(source/'irl.3do', folder/'irl.3do')
            shutil.copy2(source/'panoz.3do', folder/'panoz.3do')
            names,meta=p.discover_from_carset(folder)
            self.assertEqual(meta['number_cars'],33)
            self.assertEqual(meta['number_unique_driver_wrappers'],33)
            self.assertEqual(names,['panoz','irl'])  # ind95 before cit74 in cars.3do
            self.assertEqual(meta['missing_chassis_assets'],[])


if __name__=='__main__':unittest.main(verbosity=2)
