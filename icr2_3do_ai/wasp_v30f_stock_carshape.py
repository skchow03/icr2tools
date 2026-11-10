"""V30f: stock-style ICR2 SUPEROBJ carshape and separate car appearance wrapper.

Derived from the validated V30e model. Geometry and texture UVs are preserved.
The user's roadcar.3do shows SUPEROBJ, 5 DYNAMIC children, 0 in-file MIPs,
no MATERIAL in the base shape and POLY[T] group 16.
"""
from __future__ import annotations
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import shutil
from .stage2 import validate_path, validate_source
from .marmon_mip_asset import SOURCE_SHA256


def replace_one(source, old, new):
    if source.splitlines().count(old) != 1:
        raise ValueError(f"Unexpected V30e declaration: {old[:90]}")
    return source.replace("\n" + old + "\n", "\n" + new + "\n", 1)


def stock_source(source):
    if "ICR2_CAR_TEXTURE_GROUP" in source:
        raise ValueError("Baseline already has a native car group")
    source=replace_one(source,
        "root: LIST {wasp_ground_shadow, wasp_marmon_material};",
        "wasp_primary: LIST {wasp_ground_shadow, wasp_vehicle_sort};\n"
        "root: SUPEROBJ wasp_primary, "
        "{wasp_front_left, wasp_front_right, wasp_rear_left, wasp_rear_right, wasp_driver_helmet};")
    source=replace_one(source,
        "wasp_vehicle_sort: BSPA (wasp_y_a, wasp_y_b, wasp_y_c), "
        "wasp_positive_wheels, wasp_frame_and_body, wasp_negative_wheels;",
        "wasp_vehicle_sort: LIST {wasp_frame_and_body};")
    source=replace_one(source,
        "wasp_pilot_depth: LIST {wasp_driver_center, wasp_driver_helmet};",
        "wasp_pilot_depth: LIST {wasp_driver_center};")
    mat='wasp_marmon_material: MATERIAL MIP="MARMON", GROUP=3, wasp_vehicle_sort;'
    source=replace_one(source,mat,
        "% The MARMON MIP is selected by an independent stock car appearance.")
    scale="% ICR2_COORD_SCALE: 1"
    if source.count(scale)!=1:
        raise ValueError("Source must use raw Papyrus units")
    source=source.replace(scale,scale+"\n% ICR2_CAR_TEXTURE_GROUP: 16",1)
    if 'MATERIAL MIP="MARMON"' in source:
        raise ValueError("Carshape still has internal MIP reference")
    return source


def appearance_source():
    # RECOLOR must be at the root MATERIAL's child; the compiler's EXTERN
    # table identifies the separate WASP geometry, as for ind96.3do.
    return """3D VERSION 3.0;
% ICR2_COORD_SCALE: 1
% Independent driver's appearance: user MARMON.mip over WASP.3do carshape.
base_geometry: DYNAMIC 0, 0, 0, 0, 0, 0, 1, EXTERN "WASP";
paint_colors: RECOLOR (33:33, 40:40, 148:148, 149:149, 158:158, 159:159);
root: MATERIAL MIP="MARMON", GROUP=3, paint_colors;
"""


def polygon_signature(model):
    def vertex(ref):
        v=model.vertices[ref]
        return (*v.xyz, v.uv if v.textured else None)
    return Counter((p.kind,p.color,tuple(vertex(v) for v in p.refs[:-1]))
                   for p in model.polygons.values())


def check_shape(model, old):
    if model.records[model.root_offset]!=16:
        raise ValueError("Carshape root is not SUPEROBJ")
    if model.mip_names or model.materials or model.polygon_materials:
        raise ValueError("A stock-style carshape has no embedded MIP MATERIAL")
    if polygon_signature(model)!=polygon_signature(old):
        raise ValueError("Geometry, color, UV or polygon type changed from V30e")
    textured=[p for p in model.polygons.values() if p.kind==2]
    if len(textured)!=63 or any(p.group!=16 for p in textured):
        raise ValueError("Carshape must have 63 group-16 textured polygons")
    if sum(p.kind==5 for p in model.planes.values())!=80:
        raise ValueError("V30c FACE culling gates changed")
    root=model.children[model.root_offset]
    if len(root)!=6 or model.records.get(root[0])!=11:
        raise ValueError("SUPEROBJ must contain primary LIST and five externals")
    dynamics=model.dynamics
    if len(dynamics)!=5 or set(root[1:])!=set(dynamics):
        raise ValueError("Exactly five DYNAMIC nodes must be direct SUPEROBJ references")
    names=Counter(dynamics[ptr].name for ptr in root[1:])
    if names!=Counter({"FWHEEL":2,"RWHEEL":2,"HELMET":1}):
        raise ValueError(f"Unexpected external wheel/helmet names {names}")
    cameras=[]
    for eye in ((150000,0,18000),(-150000,0,18000),
                (0,150000,18000),(0,-150000,18000),
                (100000,-100000,-6500),(-100000,100000,-6500)):
        events=[]
        model.switched_polygons(None,eye,bsp_mode="original",events=events)
        positions=[e[1] for e in events if e[0]=="dynamic"]
        if len(positions)!=5 or len(set(positions))!=5:
            raise ValueError(f"Lost or duplicated external part from {eye}")
        cameras.append({"eye":list(eye),"dynamic_events":5,
                        "polygon_events":sum(e[0]=="polygon" for e in events)})
    return {"root":"SUPEROBJ","mip_count":0,"material_count":0,
            "poly_t_group":16,"textured_polygons":63,"face_nodes":80,
            "external_parts":dict(names),"sample_cameras":cameras,
            "polygon_geometry_uv_identical_to_v30e":True}


def build(baseline:Path,output:Path):
    from three_do import Model
    from car_appearance import read_car_appearance
    if output.exists():
        raise FileExistsError(output)
    oldsource=(baseline/"WASP.3D").read_text(encoding="utf-8")
    old=Model(baseline/"WASP.3do",associate_planes=False)
    source=stock_source(oldsource)
    model,info=validate_source(source,model_path=output/"WASP.3D")
    if info["parser_warnings"]:
        raise ValueError(info["parser_warnings"])
    shape=check_shape(model,old)
    paint=appearance_source()
    wrapper,wi=validate_source(paint,model_path=output/"MARMON.3D")
    if wi["parser_warnings"]:
        raise ValueError(wi["parser_warnings"])
    output.mkdir(parents=True)
    for name,contents in (("WASP.3D",source),("MARMON.3D",paint)):
        (output/name).write_text(contents,encoding="utf-8")
    (output/"WASP.3do").write_bytes(model.raw)
    (output/"MARMON.3do").write_bytes(wrapper.raw)
    app=read_car_appearance(output/"MARMON.3do")
    if (app.geometry_name,app.texture_name)!=("WASP","MARMON"):
        raise ValueError(f"Appearance wrapper not wired to WASP/MARMON: {app}")
    if not app.mapping or any(a!=b for a,b in app.mapping.items()):
        raise ValueError("Appearance recolor mapping was not identity")
    mip=baseline/"MARMON.mip"
    if not mip.is_file() or sha256(mip.read_bytes()).hexdigest()!=SOURCE_SHA256:
        raise ValueError("Original user-supplied MARMON.mip hash differs")
    shutil.copyfile(mip,output/mip.name)
    for name in ("FWHEEL","RWHEEL","HELMET"):
        p=baseline/(name+".3do")
        if validate_path(p)["parser_warnings"]:
            raise ValueError(f"Invalid unchanged {name} external")
        shutil.copyfile(p,output/p.name)
        edit=baseline/(name+".3D")
        if edit.exists():
            shutil.copyfile(edit,output/edit.name)
    manifest={"version":"V30f","source_v30e_sha256":sha256(oldsource.encode()).hexdigest(),
              "reference_roadcar_structure":{"root":"SUPEROBJ","mips":0,
              "textured_group":16,"superobj_external_count":5},
              "carshape":shape,
              "appearance":{"root":"MATERIAL > RECOLOR",
                  "external_geometry":app.geometry_name,
                  "mip":app.texture_name,"identity_recolor_count":len(app.mapping)},
              "user_mip_sha256":SOURCE_SHA256,
              "validation":{"carshape":info,"wrapper":wi},
              "sha256":{p.name:sha256(p.read_bytes()).hexdigest()
                         for p in output.glob("*.3do")},
              "game_test_required":True,
              "caveat":"Stock SUPEROBJ puts external parts outside prior BSP painter hierarchy; check helmet/tail occlusion in game."}
    (output/"v30f_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",
                                            encoding="utf-8")
    return manifest


def main(argv=None):
    ap=argparse.ArgumentParser()
    ap.add_argument("--baseline",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args(argv)
    m=build(args.baseline,args.output)
    print(json.dumps({"version":m["version"],"carshape":m["carshape"],
                      "appearance":m["appearance"],
                      "sha256":m["sha256"]},indent=2))


if __name__=="__main__":
    main()
