"""V30g: restore stock ICR2 wheel proxy chain.

The supplied stock roadcar has SUPEROBJ direct DYNAMIC references to
SFRONT/SREAR. Its wheel proxies are native MATERIAL MIP='wheel1' nodes
with a negative external pointer to FWHEEL/RWHEEL; each proxy also carries
an opaque material color word, 0x01080808, absent from older N3 generator
output. This revision preserves V30f's textured Wasp polygons/geometry, but
uses native wheel proxies and stock side-specific rotations.

We author the proxies in editable N3, then use the established compiler.
No stock or user-supplied binary has to be committed to the repository.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import shutil
import struct

from .stage2 import validate_source, validate_path

WHEEL_MATERIAL_COLOR = 0x01080808
WHEEL_F_MATERIAL_COLOR = 0x01080c08
STOCK_PROXY_SPEC = {
    "SFRONT": ("FWHEEL","wheel1",WHEEL_MATERIAL_COLOR),
    "SREAR": ("RWHEEL","wheel1",WHEEL_MATERIAL_COLOR),
    "SFRONTF": ("FWHEEL","wheel1f",WHEEL_F_MATERIAL_COLOR),
    "SREARF": ("RWHEEL","wheel1f",WHEEL_F_MATERIAL_COLOR),
}
WHEEL_PLACEMENTS = {
    "wasp_front_left": ("FWHEEL","SFRONT",(42700,17400,-256),1800,0),
    "wasp_front_right": ("FWHEEL","SFRONT",(42700,-17400,-256),1800,1800),
    "wasp_rear_left": ("RWHEEL","SREAR",(-15300,16800,-256),1800,0),
    "wasp_rear_right": ("RWHEEL","SREAR",(-15300,-16800,-256),1800,1800),
}


def replace_exact(source,old,new):
    if source.splitlines().count(old)!=1:
        raise ValueError(f"Missing expected V30f DYNAMIC statement {old}")
    return source.replace("\n"+old+"\n","\n"+new+"\n",1)


def make_shape(source):
    """Change only external names and per-side rotation, not wheel locations."""
    for name,(oldpart,newpart,(x,y,z),oldrot,newrot) in WHEEL_PLACEMENTS.items():
        before=(f'{name}: DYNAMIC {x}, {y}, {z}, {oldrot}, 0, 0, 1, '
                f'EXTERN "{oldpart}";')
        after=(f'{name}: DYNAMIC {x}, {y}, {z}, {newrot}, 0, 0, 1, '
               f'EXTERN "{newpart}";')
        source=replace_exact(source,before,after)
    # No direct wheel geometry references anywhere in reachable source.
    if 'EXTERN "FWHEEL"' in source or 'EXTERN "RWHEEL"' in source:
        raise ValueError("Direct wheel references remain in stock carshape")
    return source


def proxy_n3(geometry,mip,color):
    return (
        '3D VERSION 3.0;\n'
        '% ICR2_COORD_SCALE: 1\n'
        '% Stock-style ICR2 wheel proxy: MATERIAL wraps EXTERN wheel model.\n'
        f'root: MATERIAL MIP="{mip}", COLOR={color}, EXTERN "{geometry}";\n'
    )


def polygon_signature(model):
    def vertex(ref):
        v=model.vertices[ref]
        return (*v.xyz,v.uv if v.textured else None)
    return Counter(
        (p.kind,p.color,p.group,tuple(vertex(v) for v in p.refs[:-1]))
        for p in model.polygons.values()
    )


def check_shape(model,old):
    if polygon_signature(model)!=polygon_signature(old):
        raise ValueError("V30f carshape polygons, UVs, colors or textures changed")
    if model.records.get(model.root_offset)!=16:
        raise ValueError("Carshape no longer uses SUPEROBJ")
    if model.mip_names or model.materials:
        raise ValueError("Carshape must not embed a MIP/MATERIAL node")
    root_children=model.children[model.root_offset]
    if len(root_children)!=6 or set(root_children[1:])!=set(model.dynamics):
        raise ValueError("Expected five immediate SUPEROBJ DYNAMIC references")
    parts=Counter(model.dynamics[p].name for p in root_children[1:])
    if parts!=Counter({"SFRONT":2,"SREAR":2,"HELMET":1}):
        raise ValueError(f"Unexpected Wasp external names {parts}")
    expected=[(42700,17400,-256),(42700,-17400,-256),
              (-15300,16800,-256),(-15300,-16800,-256)]
    angles=[(0,0,0),(-2147483648,0,0),
            (0,0,0),(-2147483648,0,0)]
    for ptr,xyz,rotation in zip(root_children[1:5],expected,angles):
        d=model.dynamics[ptr]
        if d.xyz!=xyz or d.angles!=rotation:
            raise ValueError(f"Native wheel side placement/rotation invalid: {d}")
    if model.dynamics[root_children[5]].xyz!=(-600,0,12824):
        raise ValueError("Stock HELMET position changed")
    if sum(p.kind==2 for p in model.polygons.values())!=63 or any(
            p.group!=16 for p in model.polygons.values() if p.kind==2):
        raise ValueError("Carshape texture convention regressed")
    if sum(p.kind==5 for p in model.planes.values())!=80:
        raise ValueError("Previous upper surface and fin FACE gates regressed")
    return {"root":"SUPEROBJ","direct_external_parts":dict(parts),
            "wheel_rotations_signed_32bit":angles,
            "textured_carshape_polygons":63,"carshape_texture_group":16,
            "geometry_uv_and_polygon_order_unchanged":True}


def check_proxy(name,model,source,wheel,mip,color):
    if len(model.raw)<40 or model.records.get(model.root_offset)!=4:
        raise ValueError(f"{name}: root must be MATERIAL")
    if model.mip_names!=[mip] or model.external_names!=[wheel]:
        raise ValueError(f"{name}: bad MIP or geometry lookup")
    if model.children.get(model.root_offset)!=[-1]:
        raise ValueError(f"{name}: MATERIAL must point directly to EXTERN {wheel}")
    if struct.unpack_from("<i",model.body,model.root_offset+8)[0]!=color:
        raise ValueError(f"{name}: stock color word was not preserved")
    if len(model.polygons) or len(model.dynamics):
        raise ValueError(f"{name}: wheel proxy must not contain geometry")
    if len(model.mip_names)!=1 or len(model.materials)!=1:
        raise ValueError(f"{name}: requires named MATERIAL")
    return {"root_kind":"MATERIAL","mip":mip,"external":wheel,
            "material_color_word":color,"model_size_bytes":len(model.raw)}


def build(baseline:Path,output:Path):
    from three_do import Model
    if output.exists():
        raise FileExistsError(output)
    oldsrc=(baseline/"WASP.3D").read_text(encoding="utf-8")
    old=Model(baseline/"WASP.3do",associate_planes=False)
    shape_source=make_shape(oldsrc)
    shape,shape_validation=validate_source(shape_source,model_path=output/"WASP.3D")
    if shape_validation["parser_warnings"]:
        raise ValueError(shape_validation["parser_warnings"])
    shape_checks=check_shape(shape,old)
    proxies={}
    wrapper_data={}
    for name,(wheel,mip,color) in STOCK_PROXY_SPEC.items():
        code=proxy_n3(wheel,mip,color)
        model,report=validate_source(code,model_path=output/f"{name}.3D")
        # The compiler intentionally reports no local editable polygons for
        # a MATERIAL + EXTERN wrapper, just like stock SFRONT/SREAR binaries.
        expected=["No editable geometry: file may be an object placement / material wrapper"]
        if report["parser_warnings"]!=expected:
            raise ValueError(f"Unexpected {name} warnings: {report['parser_warnings']}")
        proxies[name]=check_proxy(name,model,code,wheel,mip,color)
        wrapper_data[name]=(code,model.raw)
    output.mkdir(parents=True)
    (output/"WASP.3D").write_text(shape_source,encoding="utf-8")
    (output/"WASP.3do").write_bytes(shape.raw)
    for name,(code,data) in wrapper_data.items():
        (output/(name+".3D")).write_text(code,encoding="utf-8")
        (output/(name+".3do")).write_bytes(data)
    for name in ("FWHEEL.3D","RWHEEL.3D","HELMET.3D",
                 "FWHEEL.3do","RWHEEL.3do","HELMET.3do",
                 "MARMON.3D","MARMON.3do","MARMON.mip"):
        src=baseline/name
        if not src.is_file():
            if name=="HELMET.3D":
                continue
            raise FileNotFoundError(src)
        if name.endswith(".3do") and validate_path(src)["parser_warnings"] not in (
                [],["No editable geometry: file may be an object placement / material wrapper"]):
            raise ValueError(f"Unexpected dependency structure {name}")
        shutil.copyfile(src,output/name)
    for name in ("FWHEEL.3do","RWHEEL.3do","HELMET.3do",
                 "MARMON.3do","MARMON.mip"):
        if (output/name).read_bytes()!=(baseline/name).read_bytes():
            raise ValueError(f"Dependency unexpectedly changed {name}")
    report={
        "version":"V30g",
        "stock_reference":"User-provided ROADCAR.3do and SFRONT/SREAR MATERIAL > EXTERN wheel proxies",
        "carshape":shape_checks,
        "wheel_proxy_checks":proxies,
        "reference_proxies_in_game":{"front":"SFRONT.3do","rear":"SREAR.3do"},
        "optional_alternate_wheel_proxies":["SFRONTF.3do","SREARF.3do"],
        "required_unmodified_wheel_models":["FWHEEL.3do","RWHEEL.3do"],
        "wheel_texture_dependency":"wheel1.mip (from carset/game assets, only if engine requires material)",
        "unchanged":"MARMON.3do, MARMON.mip, HELMET.3do, FWHEEL.3do, RWHEEL.3do",
        "checks":{"carshape_compile":shape_validation,
                  "native_proxy_count":len(proxies)},
        "files_sha256":{p.name:sha256(p.read_bytes()).hexdigest()
                        for p in output.glob("*.3do")},
        "needs_real_game_verification":True
    }
    (output/"v30g_manifest.json").write_text(json.dumps(report,indent=2)+"\n",
                                              encoding="utf-8")
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args(argv)
    manifest=build(args.baseline,args.output)
    print(json.dumps({
        "version":"V30g","native_wheel_proxy_names":list(manifest["wheel_proxy_checks"]),
        "superobj_names":manifest["carshape"]["direct_external_parts"],
        "model_hash":manifest["files_sha256"]["WASP.3do"]
    },indent=2))


if __name__=="__main__":
    main()
