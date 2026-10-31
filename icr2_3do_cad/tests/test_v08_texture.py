"""Focused MIP header, UV and integration regressions for v0.8."""
from __future__ import annotations
import struct
import unittest
import tempfile
from pathlib import Path
import numpy as np
from three_do import Model
from texture_preview import load_mip, rasterize_polygon, triangulate, TextureError

BASE=Path(__file__).resolve().parents[1]

def create_test_mip(path,w=128,h=64,count=4):
    # Replicates the layout in skchow03/icr2tools/mips.py img_to_mip:
    # 24-byte fixed header + 12*levels + one duplicated row before/after.
    widths=[];heights=[]
    for i in range(count):
        widths.append(max(1,(w+(1<<i)//2)//(1<<i)))
        heights.append(max(1,(h+(1<<i)//2)//(1<<i)))
    header=24+count*12
    result=bytearray(header)
    offsets=[]
    for i in range(count):
        image=np.zeros((heights[i],widths[i]),dtype=np.uint8)
        yy,xx=np.indices(image.shape)
        if i==0:
            image=((xx//8+yy//8)%2*60+40).astype(np.uint8)
        else:
            image[:]=(90+i*10)
        # file offset relative to byte 4
        offsets.append(len(result)+widths[i]-4)
        result.extend(image[0].tobytes());result.extend(image.tobytes());result.extend(image[-1].tobytes())
    struct.pack_into('<6i',result,0,len(result),0,w,h,count,90)
    for i in range(count):
        struct.pack_into('<i',result,24+12*i,widths[i]-1)
        struct.pack_into('<B',result,28+12*i,0)
        struct.pack_into('<3B',result,29+12*i,255,255,255)
        struct.pack_into('<i',result,32+12*i,offsets[i])
    Path(path).write_bytes(result)

class MipDecoderTests(unittest.TestCase):
    def test_multiple_mip_levels_and_dimensions(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'test.mip';create_test_mip(p)
            frames=load_mip(p)
            self.assertEqual([im.size for im in frames],[(128,64),(64,32),(32,16),(16,8)])
            self.assertEqual(frames[0].getpixel((0,0)),40)
            self.assertEqual(frames[0].getpixel((8,0)),100)
            self.assertEqual(frames[0].getpixel((0,8)),100)
            self.assertEqual(frames[2].getpixel((0,0)),110)
    def test_actual_game_mip_header_and_odd_height_levels(self):
        # ind96.mip from the user's ICR2 assets. Size excludes the first dword,
        # and each mip's height is calculated by sequential ceil-halving.
        real_mip=BASE/'fixtures'/'ind96.mip'
        self.assertTrue(real_mip.exists())
        frames=load_mip(real_mip)
        self.assertEqual([im.size for im in frames],
                         [(128,165), (64,83), (32,42), (16,21),
                          (8,11), (4,6), (2,3)])
        # Verify representative visible image values, not the duplicate row.
        raw=real_mip.read_bytes()
        for idx,im in enumerate(frames):
            off=4+struct.unpack_from('<i',raw,32+12*idx)[0]
            self.assertEqual(im.getpixel((0,0)),raw[off])
            self.assertEqual(im.getpixel((im.width-1,im.height-1)),
                             raw[off+im.width*im.height-1])

    def test_body_length_header_is_accepted(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'test.mip';create_test_mip(p)
            raw=bytearray(p.read_bytes())
            struct.pack_into('<i',raw,0,len(raw)-4)
            p.write_bytes(raw)
            self.assertEqual(len(load_mip(p)),4)

    def test_corrupt_mip_is_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'bad.mip';create_test_mip(p)
            data=bytearray(p.read_bytes());struct.pack_into('<i',data,32,10_000_000);p.write_bytes(data)
            with self.assertRaises(TextureError):load_mip(p)

class RasterTests(unittest.TestCase):
    def setUp(self):
        self.palette=[(i,i,0) for i in range(256)]
        self.image=np.tile(np.arange(16,dtype=np.uint8)[None,:],(16,1))
    def test_flat_uv_mapping(self):
        # A 16x16 display maps to 16 texels in U and V.
        verts=[(0,0,1,0,0),(16,0,1,15,0),(16,16,1,15,15),(0,16,1,0,15)]
        out=rasterize_polygon(self.image,self.palette,verts,(40,40))
        self.assertIsNotNone(out)
        img,x,y=out
        self.assertEqual((x,y),(0,0))
        self.assertEqual(img.getpixel((0,0)),(0,0,0,255))
        self.assertEqual(img.getpixel((8,8)),(8,8,0,255))
    def test_perspective_uv_is_not_affine(self):
        verts=[(0,0,1,0,0),(20,0,10,15,0),(0,20,10,0,15)]
        affine=rasterize_polygon(self.image,self.palette,verts,(30,30),perspective=False)[0]
        proper=rasterize_polygon(self.image,self.palette,verts,(30,30),perspective=True)[0]
        self.assertNotEqual(affine.getpixel((8,4)),proper.getpixel((8,4)))
    def test_concave_polygon_triangulates(self):
        verts=[(0,0),(14,0),(14,14),(7,7),(0,14)]
        self.assertEqual(len(triangulate(verts)),3)
    def test_irregular_nonplanar_uv_polygon(self):
        verts=[(0,0,2,0,0),(30,0,2,15,0),(30,20,4,15,15),
               (15,15,6,8,10),(0,20,3,0,15)]
        result=rasterize_polygon(self.image,self.palette,verts,(40,30),perspective=True)
        self.assertIsNotNone(result)
        self.assertEqual(result[0].getpixel((5,5))[3],255)
    def test_paint_layer_alpha(self):
        verts=[(5,5,1,0,0),(15,5,1,15,0),(5,15,1,0,15)]
        im,x,y=rasterize_polygon(self.image,self.palette,verts,(20,20))
        self.assertEqual(im.getpixel((0,0))[3],255)
        self.assertEqual(im.getpixel((9,9))[3],0)

class ModelTextureTests(unittest.TestCase):
    def test_unmodified_file_roundtrip(self):
        m=Model(BASE/'fixtures'/'roadcar.3do')
        self.assertTrue(any(poly.kind==2 for poly in m.polygons.values()))
        self.assertEqual(m.mip_names,[])
        self.assertEqual(m.polygon_materials,{})
        data,report=m.build_modified_bytes()
        self.assertEqual(data,m.raw)
    def test_named_material_associations_through_list(self):
        # Build a miniature 3DO: a MATERIAL points to a LIST containing POLY[T].
        body=bytearray(180)
        vertex_offset=(100,120,140)
        for off,xyz in zip(vertex_offset,((0,0,0),(10,0,0),(0,10,0))):
            struct.pack_into('<4i2H',body,off,0,*xyz,0,0)
        struct.pack_into('<4i',body,0,-2147483644,0,0,32) # MATERIAL index 0 -> LIST @32
        struct.pack_into('<3i',body,32,-2147483637,1,44) # LIST count 1
        struct.pack_into('<7i',body,44,-2147483646,3,1,2,100,120,140)
        header=struct.pack('<5i',len(body),0,1,0,0)+b'testmip\x00'
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'test.3do';p.write_bytes(header+body)
            m=Model(p)
            self.assertEqual(m.mip_names,['testmip'])
            self.assertEqual(m.polygon_materials[44],'testmip')

if __name__=='__main__':unittest.main()
