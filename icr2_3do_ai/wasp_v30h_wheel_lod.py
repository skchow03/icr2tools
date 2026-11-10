"""V30h diagnostic: make custom Wasp wheel geometry use stock RES root.

The user's observation that damaged-car tires appear narrows suspicion to
normal-car wheel geometry/scene integration. User-supplied stock FWHEEL/RWHEEL
have a 3-branch RES root (thresholds 280000, 113750, 0); V30g's custom
Wasp wheels have a raw BSPA root. This build preserves *all* wheel polygons,
colors, radius, UVs, anchors and geometry, changing only the root hierarchy
to stock RES with three branches pointing to the same detailed wheel graph.

Using identical detail at all three distances isolates root compatibility.
Optimize LODs only after the game confirms whether this makes wheels visible.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import shutil

from .stage2 import validate_source, validate_path

ROOT_BEFORE=(
    "root: BSPA (wheel_y_a, wheel_y_b, wheel_y_c), "
    "wheel_pos_cover, black_firestone_tire_geo, wheel_neg_cover;"
)
ROOT_AFTER=(
    "% V30h: same detailed wheel graph at all three stock RES distances.\n"
    "wasp_wheel_detail: BSPA (wheel_y_a, wheel_y_b, wheel_y_c), "
    "wheel_pos_cover, black_firestone_tire_geo, wheel_neg_cover;\n"
    "wheel_lod_anchor: [<0, 0, 0>];\n"
    "root: SWITCH DISTANCE (wheel_lod_anchor) > "
    "{(280000 ? wasp_wheel_detail), (113750 ? wasp_wheel_detail), "
    "(0 ? wasp_wheel_detail)};"
)
STOCK_DISTANCE_THRESHOLDS=(280000,113750,0)


def wheel_source(source):
    if source.splitlines().count(ROOT_BEFORE)!=1:
        raise ValueError("Wheel source isn't the V30g BSPA-root baseline")
    return source.replace("\n"+ROOT_BEFORE+"\n","\n"+ROOT_AFTER+"\n",1)


def polygon_signature(model):
    def v(k):
        p=model.vertices[k]
        return (p.xyz,p.uv,p.textured)
    return Counter((p.kind,p.color,p.group,tuple(v(x) for x in p.refs[:-1]))
                   for p in model.polygons.values())


def check_wheel(model,original):
    if model.records.get(model.root_offset)!=13:
        raise ValueError("Custom wheel must have a stock-like RES root")
    sw=model.switches.get(model.root_offset)
    if sw is None or tuple(th for th,_ in sw.branches)!=STOCK_DISTANCE_THRESHOLDS:
        raise ValueError("Root RES thresholds differ from stock")
    if len({ptr for th,ptr in sw.branches})!=1:
        raise ValueError("Diagnostic must reuse the same detailed wheel at each LOD")
    anchor=model.vertices.get(sw.anchor)
    if anchor is None or anchor.xyz!=(0,0,0):
        raise ValueError("Wheel LOD anchor must remain wheel-local origin")
    ptr=sw.branches[0][1]
    if model.records.get(ptr)!=8:
        raise ValueError("RES points to something other than the original BSPA")
    if polygon_signature(model)!=polygon_signature(original):
        raise ValueError("Wheel XYZ, UV, geometry, palette or winding has changed")
    if len(model.polygons)!=114:
        raise ValueError("Unexpected custom wheel polygon count")
    tests=[]
    for distance in (10000,120000,300000):
        polygons,_,selected=model.switched_polygons(
            distance,(100000,40000,30000),bsp_mode="original")
        if len(polygons)<100:
            raise ValueError(f"At distance {distance}, too few polygons: {len(polygons)}")
        if len(selected)!=1 or selected[0][1]!=ptr:
            raise ValueError(f"Invalid RES choice at distance {distance}: {selected}")
        tests.append({"distance":distance,"visible_polygons":len(polygons),
                      "chosen_branch":selected[0][0]})
    return {"root":"RES","thresholds":list(STOCK_DISTANCE_THRESHOLDS),
            "detail_graph":"original BSPA","polygons":len(model.polygons),
            "geometry_byte_semantics_equal":True,"three_lod_distance_tests":tests}


def build(baseline:Path,output:Path):
    from three_do import Model
    if output.exists():
        raise FileExistsError(output)
    new_files={}
    checks={}
    for name in ("FWHEEL","RWHEEL"):
        n3=(baseline/(name+".3D")).read_text(encoding="utf-8")
        original=Model(baseline/(name+".3do"),associate_planes=False)
        new=wheel_source(n3)
        model,validation=validate_source(new,model_path=output/(name+".3D"))
        if validation["parser_warnings"]:
            raise ValueError(f"{name}: {validation['parser_warnings']}")
        checks[name]=check_wheel(model,original)
        new_files[name]=(new,model.raw)
    output.mkdir(parents=True)
    for name,(source,binary) in new_files.items():
        (output/(name+".3D")).write_text(source,encoding="utf-8")
        (output/(name+".3do")).write_bytes(binary)
    # The original V30g carshape, all four wheel wrappers, livery, helmet and
    # wheel1 references are intentionally byte identical.
    for name in ("WASP.3do","WASP.3D","MARMON.3do","MARMON.3D",
                 "MARMON.mip","HELMET.3do",
                 "SFRONT.3do","SREAR.3do","SFRONT.3D","SREAR.3D",
                 "SFRONTF.3do","SREARF.3do","SFRONTF.3D","SREARF.3D"):
        path=baseline/name
        if path.is_file():
            shutil.copyfile(path,output/name)
        elif name in ("SFRONTF.3do","SREARF.3do","SFRONTF.3D",
                    "SREARF.3D"):
            continue
        else:
            raise FileNotFoundError(path)
    for name in ("WASP.3do","MARMON.3do","MARMON.mip","HELMET.3do",
                 "SFRONT.3do","SREAR.3do"):
        if (output/name).read_bytes()!=(baseline/name).read_bytes():
            raise ValueError(f"Unexpected modification to original {name}")
    if validate_path(output/"WASP.3do")["parser_warnings"]:
        raise ValueError("Stock-style body geometry changed or failed parsing")
    manifest={"version":"V30h","purpose":"Custom wheel root RES compatibility diagnosis",
      "user_observation":"Stock damaged-car model shows wheels; normal Wasp did not",
      "wheel_checks":checks,
      "unchanged":"WASP carshape, driver livery, SFRONT/SREAR wrappers, helmet",
      "stock_distance_thresholds":list(STOCK_DISTANCE_THRESHOLDS),
      "user_supplied_stock_comparison":"Stock wheel geometry root is RES, Wasp V30g wheels root BSPA",
      "not_proven":"Real game visibility and damage-model loading path",
      "test_order":"Try only FWHEEL/RWHEEL replacements first; if no wheels, try user-supplied stock wheel meshes",
      "files_sha256":{p.name:sha256(p.read_bytes()).hexdigest()
                      for p in output.glob("*.3do")}}
    (output/"v30h_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",
                                               encoding="utf-8")
    return manifest


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args(argv)
    r=build(args.baseline,args.output)
    print(json.dumps({"version":r["version"],
                      "wheel_checks":r["wheel_checks"],
                      "wheel_hashes":{k:v for k,v in r["files_sha256"].items()
                                      if k in ("FWHEEL.3do","RWHEEL.3do")}},indent=2))


if __name__=="__main__":
    main()
