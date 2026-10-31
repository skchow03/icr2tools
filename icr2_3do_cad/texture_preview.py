"""Papyrus ICR2 8-bit MIP reader and UV-mapped raster preview.

MIP layout follows skchow03/icr2tools/icr2_core/mip/mips.py.
MIP offsets are relative to the four-byte-size-stripped body. The declared
MIP size may include or exclude the leading four-byte length field, depending
on the producing tool. Each level contains a repeated top/bottom scanline
around its indexed pixels. Odd dimensions round up at *each successive* mip
level, not from the original size.
The renderer uses polygon UVs as raw texel coordinates (not UV [0,1]).
This is a diagnostic renderer, not a reproduction of ICR2's fixed-point scanlines.
"""
from __future__ import annotations
from pathlib import Path
import math
import struct

try:
    import numpy as np
    from PIL import Image, ImageTk
    ENABLED = True
except ImportError:
    np = None
    Image = ImageTk = None
    ENABLED = False


class TextureError(ValueError):
    pass


def load_mip(path):
    """Return a list of indexed PIL images, highest resolution first.

    Both uncompressed 8-bit indices and all LOD offsets are validated.
    The indexed color values are kept intact for later palette lookup.
    """
    if not ENABLED:
        raise TextureError('Texture preview requires Pillow and NumPy')
    raw = Path(path).read_bytes()
    if len(raw) < 36:
        raise TextureError('MIP header is truncated')
    size, unused, width, height, count, average = struct.unpack_from('<6i', raw)
    # Papyrus/ICR2 files authored by some tools put the *body* length in
    # this field, excluding the size dword itself (e.g. ind96.mip).
    # Other tools, including our earlier test fixture, count all file bytes.
    if size not in (len(raw), len(raw)-4):
        raise TextureError(f'MIP declared size {size} does not match file length {len(raw)}'
                           f' or body length {len(raw)-4}')
    if not (1 <= width <= 4096 and 1 <= height <= 4096 and 1 <= count <= 16):
        raise TextureError('Invalid MIP dimensions or level count')
    header_end = 24 + 12 * count
    if header_end > len(raw):
        raise TextureError('MIP level table is truncated')
    result = []
    w,h = width,height
    previous_end = header_end
    for level in range(count):
        if level:
            # Apply a ceil-halving to the PREVIOUS level, not width/(2**n).
            # For example, 165 -> 83 -> 42 -> 21 -> 11 -> 6 -> 3.
            w=max(1,(w+1)//2)
            h=max(1,(h+1)//2)
        # Offset stored at byte 32+12*level, relative to raw[4:].
        # It skips the duplicate top row; the referenced byte is the first
        # pixel of the actual image. Never sample the buffering scanline.
        relative_offset = struct.unpack_from('<i', raw, 32 + 12*level)[0]
        absolute_offset = 4 + relative_offset
        end = absolute_offset + w*h
        if absolute_offset < previous_end or end > len(raw):
            raise TextureError(f'MIP level {level} has invalid pixel offset or size '
                               f'({w}x{h}, offset {absolute_offset})')
        pixels = np.frombuffer(raw, dtype=np.uint8, count=w*h, offset=absolute_offset)
        result.append(Image.fromarray(pixels.reshape(h,w).copy(), mode='P'))
        previous_end = end
    return result


def _cross2(a,b,c):
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def triangulate(pts):
    """Screen-space ear clipping, retaining the original polygon vertex order.

    Works for convex or simple concave polygons. For a malformed/self-crossing
    polygon, fall back to a fan, matching 'best effort' rather than dropping it.
    """
    n=len(pts)
    if n < 3: return []
    area=sum(pts[i][0]*pts[(i+1)%n][1]-pts[(i+1)%n][0]*pts[i][1] for i in range(n))
    if abs(area) < 1e-7:
        return [(0,i,i+1) for i in range(1,n-1)]
    orientation = 1 if area>0 else -1
    remaining=list(range(n)); triangles=[]
    for _ in range(n*n):
        if len(remaining)<=3: break
        clipped=False
        for k in range(len(remaining)):
            a=remaining[(k-1)%len(remaining)]
            b=remaining[k]
            c=remaining[(k+1)%len(remaining)]
            cr=_cross2(pts[a],pts[b],pts[c])
            if orientation*cr<=1e-8: continue
            enclosed=False
            for v in remaining:
                if v in (a,b,c):continue
                q=pts[v]
                if (orientation*_cross2(pts[a],pts[b],q)>=-1e-8 and
                    orientation*_cross2(pts[b],pts[c],q)>=-1e-8 and
                    orientation*_cross2(pts[c],pts[a],q)>=-1e-8):
                    enclosed=True;break
            if enclosed:continue
            triangles.append((a,b,c)); remaining.pop(k);clipped=True;break
        if not clipped:break
    if len(remaining)==3:triangles.append(tuple(remaining))
    if len(triangles)!=n-2:
        return [(0,i,i+1) for i in range(1,n-1)]
    return triangles


def rasterize_polygon(texture, palette, vertices, canvas_size, *, perspective=False,
                      repeat=False, brightness=1.0, sample_scale=1.0):
    """Render a UV polygon to an RGBA tile, preserving the caller's paint order.

    ``sample_scale`` reduces only texture *sampling*: it never changes geometry,
    vertex picking, BSP visibility, UV coordinates or the output tile bounds.
    The reduced tile is enlarged using nearest-neighbor sampling, appropriate
    for an old indexed-color game. A value of 1 preserves full-detail output.
    """
    if not ENABLED or len(vertices)<3:return None
    wcanvas,hcanvas=canvas_size
    if wcanvas<=0 or hcanvas<=0:return None
    sample_scale=float(sample_scale)
    if not 0.2<=sample_scale<=1.0:
        raise ValueError('sample_scale must be between 0.2 and 1.0')
    triangles=triangulate([(float(v[0]),float(v[1])) for v in vertices])
    if not triangles:return None
    x0=max(0,int(math.floor(min(v[0] for v in vertices))))
    y0=max(0,int(math.floor(min(v[1] for v in vertices))))
    x1=min(wcanvas,int(math.ceil(max(v[0] for v in vertices)))+1)
    y1=min(hcanvas,int(math.ceil(max(v[1] for v in vertices)))+1)
    if x1<=x0 or y1<=y0:return None
    full_w,full_h=x1-x0,y1-y0
    if full_w*full_h>5_000_000:return None
    small_w=max(1,math.ceil(full_w*sample_scale))
    small_h=max(1,math.ceil(full_h*sample_scale))
    img=np.zeros((small_h,small_w,4),dtype=np.uint8)
    pixels=np.asarray(texture,dtype=np.uint8)
    rgb_palette=np.asarray(palette,dtype=np.uint8)
    if brightness!=1.0:
        rgb_palette=np.clip(rgb_palette.astype(np.float32)*brightness,0,255).astype(np.uint8)
    tx_h,tx_w=pixels.shape
    # Rasterize only the triangle's local bounding rectangle, not the full
    # polygon tile. Reusing float32 coordinate grids cuts memory allocation.
    for ai,bi,ci in triangles:
        a,b,c=(vertices[i] for i in (ai,bi,ci))
        den=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(den)<1e-9:continue
        bx0=max(0,int(math.floor((min(a[0],b[0],c[0])-x0)*sample_scale)))
        by0=max(0,int(math.floor((min(a[1],b[1],c[1])-y0)*sample_scale)))
        bx1=min(small_w,int(math.ceil((max(a[0],b[0],c[0])-x0)*sample_scale))+1)
        by1=min(small_h,int(math.ceil((max(a[1],b[1],c[1])-y0)*sample_scale))+1)
        if bx1<=bx0 or by1<=by0:continue
        ys=(y0+(np.arange(by0,by1,dtype=np.float32)+0.5)/sample_scale)[:,None]
        xs=(x0+(np.arange(bx0,bx1,dtype=np.float32)+0.5)/sample_scale)[None,:]
        wa=((b[1]-c[1])*(xs-c[0])+(c[0]-b[0])*(ys-c[1]))/den
        wb=((c[1]-a[1])*(xs-c[0])+(a[0]-c[0])*(ys-c[1]))/den
        wc=1-wa-wb
        ok=(wa>=-1e-6)&(wb>=-1e-6)&(wc>=-1e-6)
        if not ok.any():continue
        # Compute UV *only for covered samples*, avoiding large temporary
        # u/v arrays in mostly transparent bounding boxes.
        wa=wa[ok];wb=wb[ok];wc=wc[ok]
        if perspective:
            za=1/max(1e-8,a[2]);zb=1/max(1e-8,b[2]);zc=1/max(1e-8,c[2])
            inv=wa*za+wb*zb+wc*zc
            inv=np.where(abs(inv)>1e-12,inv,1e-12)
            u=(wa*za*a[3]+wb*zb*b[3]+wc*zc*c[3])/inv
            v=(wa*za*a[4]+wb*zb*b[4]+wc*zc*c[4])/inv
        else:
            u=wa*a[3]+wb*b[3]+wc*c[3]
            v=wa*a[4]+wb*b[4]+wc*c[4]
        ui=np.floor(u+0.5).astype(np.int32)
        vi=np.floor(v+0.5).astype(np.int32)
        if repeat:
            ui%=tx_w;vi%=tx_h
        else:
            np.clip(ui,0,tx_w-1,out=ui);np.clip(vi,0,tx_h-1,out=vi)
        tile=img[by0:by1,bx0:bx1]
        tile[ok,:3]=rgb_palette[pixels[vi,ui]]
        tile[ok,3]=255
    if not np.any(img[:,:,3]):return None
    out=Image.fromarray(img,mode='RGBA')
    if sample_scale<1:
        out=out.resize((full_w,full_h),resample=Image.Resampling.NEAREST)
    return out,x0,y0
