"""V30e texture assignment on the validated 1911 Marmon Wasp V30d assembly.

Map the user's 128x165 MARMON.mip atlas in native Papyrus U,V pixels.
Use unique texture-coordinate vertices per triangle to prevent UV seams at
bonnet/tail side-to-roof junctions. All V30c FACE gates and V30d geometry stay.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil

from .marmon_mip_asset import ATLAS_RECTS, SOURCE_SHA256, install_to
from .stage2 import validate_path, validate_source
from .wasp_v30_touchups import event_check

VERTEX = re.compile(r"(?m)^([A-Za-z]\w*): \[<(-?\d+), (-?\d+), (-?\d+)>\];$")
POLYGON = re.compile(r"(?m)^([A-Za-z]\w*): POLY <(\d+)> \{([^}\n]+)\};$")
BODY_U = {0:127, 1:47, 2:63, 3:78, 4:99, 5:112}
EXPECTED_TEXTURED = 63
FIN_X_MIN, FIN_X_MAX = -35576, -27895
FIN_Z_MIN, FIN_Z_MAX = 12078, 19703


def _coordinate_map(source):
    return {m[1]: tuple(int(m[i]) for i in (2,3,4))
            for m in VERTEX.finditer(source)}


def _polygon_map(source):
    return {m[1]: (int(m[2]), m[3].split(", "))
            for m in POLYGON.finditer(source)}


def _linear(value, begin, end, uv_begin, uv_end):
    if begin == end:
        raise ValueError("Texture projection has a zero-length axis")
    result = round(uv_begin+(value-begin)*(uv_end-uv_begin)/(end-begin))
    return max(min(uv_begin,uv_end),min(max(uv_begin,uv_end),result))


def _body_uv(component, original_vertex, xyz, face_index=None):
    index=int(original_vertex.rsplit("_v",1)[1])
    ring=index%6
    u=BODY_U[ring]
    x=xyz[0]
    if component=="long_bonnet":
        # Atlas has the car FRONT UP (v=0), rear/dashboard down (v=72).
        # The right-hand printed number in the supplied atlas has the
        # opposite orientation when transposed onto the +Y vertical side.
        # Reuse the left-number strip (still within the requested bonnet
        # rectangle) with inverted U across that side only. Distinct
        # per-face vertices permit this without a roof/shoulder UV seam.
        if face_index in (11,0) and ring in (5,0):
            u={5:63,0:47}[ring]
        v=_linear(x,41700,13013,0,72)
    elif component=="pointed_tail":
        v=_linear(x,-3000,-38248,74,127)
    else:
        raise ValueError(component)
    return u,v


def _radiator_uv(xyz):
    _,y,z=xyz
    # The radiator's 32 reads left-to-right from a front +X camera:
    # the camera-right direction is +Y in the game's coordinate frame.
    return (_linear(y,-6750,6750,0,47),
            _linear(z,244,11164,42,0))


def _fin_uv(xyz, facing_y):
    x,_,z=xyz
    if facing_y > 0:
        # Viewed from +Y, world -X points screen-right.
        u=_linear(x,FIN_X_MAX,FIN_X_MIN,104,127)
    else:
        # Viewed from -Y, world +X points screen-right.
        u=_linear(x,FIN_X_MIN,FIN_X_MAX,104,127)
    v=_linear(z,FIN_Z_MAX,FIN_Z_MIN,131,154)
    return u,v


def apply_texture(source):
    """Return textured source, per-polygon UV records and unchanged geometry."""
    source_coords=_coordinate_map(source)
    polygons=_polygon_map(source)
    if "wasp_marmon_material:" in source or "POLY [T]" in source:
        raise ValueError("The V30d baseline is not an untextured Wasp")
    declarations=[]
    written={}
    mapping={}
    for name in ("long_bonnet","pointed_tail"):
        faces=[]
        for span in range(3):
            # Two side quads per ring side, and six roof triangles.
            faces.extend(f"{name}_p{span*12+index:04}"
                         for index in range(3,13))
        assert len(faces)==30
        for poly in faces:
            color,refs=polygons[poly]
            if len(refs)!=3 or color not in (158,159):
                raise ValueError(f"Unexpected source exterior triangle {poly}")
            coords=[source_coords[r] for r in refs]
            uv=[_body_uv(name,r,xyz,face_index=int(poly.rsplit("_p",1)[1])%12)
                for r,xyz in zip(refs,coords)]
            declarations.extend(_textured_vertices(poly,coords,uv,refs,written))
            mapping[poly]={"source_refs":refs,"xyz":coords,"uv":uv,
                           "atlas":"bonnet" if name=="long_bonnet" else "tail"}
    radiator="radiator_face_p0000"
    color,refs=polygons[radiator]
    if color!=33 or len(refs)!=6:
        raise ValueError("Radiator front hexagon was modified")
    coords=[source_coords[r] for r in refs]
    uv=[_radiator_uv(xyz) for xyz in coords]
    declarations.extend(_textured_vertices(radiator,coords,uv,refs,written))
    mapping[radiator]={"source_refs":refs,"xyz":coords,"uv":uv,"atlas":"radiator"}

    old_fin="rounded_tail_fin_p0000"
    old_color,fin_refs=polygons[old_fin]
    if old_color!=159 or len(fin_refs)!=9:
        raise ValueError("Missing flat nine-point dorsal fin")
    fin_geo="rounded_tail_fin_geo: LIST {rounded_tail_fin_p0000};"
    if source.splitlines().count(fin_geo)!=1:
        raise ValueError("Unexpected single-fin geometry group")
    replacement=("rounded_tail_fin_geo: LIST "
                 "{wasp_marmon_fin_pos_gate, wasp_marmon_fin_neg_gate};")
    source=source.replace(fin_geo,replacement,1)
    for side in (1,-1):
        label="wasp_marmon_fin_pos" if side>0 else "wasp_marmon_fin_neg"
        refs=fin_refs if side>0 else list(reversed(fin_refs))
        coords=[source_coords[r] for r in refs]
        uv=[_fin_uv(xyz,side) for xyz in coords]
        declarations.extend(_textured_vertices(label,coords,uv,refs,written,
                                              color=159,standalone=True))
        # Each side uses an opposite directional FACE gate, so the number
        # remains legible from both car sides and does not self-overpaint.
        plane=fin_refs[:3] if side>0 else list(reversed(fin_refs[:3]))
        declarations.append(
            f"{label}_gate: FACE ({', '.join(plane)}), {label};"
        )
        mapping[label]={"source_refs":refs,"xyz":coords,"uv":uv,
                        "atlas":"fin","facing_y":side}

    # Replace only the original polygons that are texture-enabled.
    # Their names remain stable, so V30c native FACE nodes still wrap them.
    for poly, data in mapping.items():
        if poly.startswith("wasp_marmon_fin_"):
            continue
        old_color,old_refs=polygons[poly]
        old=f"{poly}: POLY <{old_color}> {{{', '.join(old_refs)}}};"
        if source.splitlines().count(old)!=1:
            raise ValueError(f"Unexpected original {poly} before texture conversion")
        uv_refs=written[poly]
        new=f"{poly}: POLY [T] <{old_color}> {{{', '.join(uv_refs)}}};"
        source=source.replace("\n"+old+"\n","\n"+new+"\n",1)

    old_root="root: LIST {wasp_ground_shadow, wasp_vehicle_sort};"
    if source.splitlines().count(old_root)!=1:
        raise ValueError("Could not locate the V30d root")
    source=source.replace(
        old_root,"root: LIST {wasp_ground_shadow, wasp_marmon_material};",1
    )
    declarations.insert(0,
        'wasp_marmon_material: MATERIAL MIP="MARMON", GROUP=3, wasp_vehicle_sort;')
    source+="\n% V30e user MARMON.mip atlas: typed UV vertices; preserved V30c FACE gates.\n"
    source+="\n".join(declarations)+"\n"
    if len(mapping)!=EXPECTED_TEXTURED:
        raise ValueError(f"Wrong texture polygon count: {len(mapping)}")
    for name,item in mapping.items():
        u0,v0,u1,v1=ATLAS_RECTS[item["atlas"]]
        if not all(u0<=u<=u1 and v0<=v<=v1 for u,v in item["uv"]):
            raise ValueError(f"UV coordinate escapes {item['atlas']}: {name}")
    return source,mapping


def _textured_vertices(poly,coords,uv,original_refs,written,
                       *,color=None,standalone=False):
    if poly in written:
        raise ValueError("Duplicate textured polygon")
    names=[]
    lines=[]
    for index,(xyz,(u,v)) in enumerate(zip(coords,uv)):
        name=f"wasp_tex_{poly}_v{index:02}"
        names.append(name)
        lines.append(f"{name}: [<{xyz[0]}, {xyz[1]}, {xyz[2]}>, T=<{u}, {v}>];")
    written[poly]=names
    if standalone:
        lines.append(f"{poly}: POLY [T] <{color}> {{{', '.join(names)}}};")
    return lines


def check_compiled(model,mapping):
    if list(model.mip_names)!=["MARMON"]:
        raise ValueError(f"Expected one MARMON material, got {model.mip_names}")
    textured=[p for p in model.polygons.values() if p.kind==2]
    if len(textured)!=EXPECTED_TEXTURED:
        raise ValueError(f"Expected {EXPECTED_TEXTURED} textured polygons, got {len(textured)}")
    for poly in textured:
        if model.polygon_materials.get(poly.offset)!="MARMON":
            raise ValueError(f"Missing MARMON material scope on textured {poly.offset}")
        coords=[model.vertices[v].xyz for v in poly.refs]
        uvs=[model.vertices[v].uv for v in poly.refs]
        if any(uv is None for uv in uvs):
            raise ValueError(f"Missing compiled UV on {poly.offset}")
        if len(set(coords)) < 3:
            raise ValueError(f"Degenerate textured polygon {poly.offset}")
    # Four radiating panels, fin and every roof culling gate remain unaffected.
    gates=[p for p in model.planes.values() if p.kind==5]
    if len(gates)!=80:
        raise ValueError(f"V30c 78 FACE gates and 2 fin directional gates expected, got {len(gates)}")
    fin_geo={tuple(sorted(item["xyz"])) for name,item in mapping.items()
             if item["atlas"]=="fin"}
    if len(fin_geo)!=1:
        raise ValueError("Fin faces don't share the original nine-point plane")
    side_test={}
    fin_polygons=[
        p for p in textured if p.color==159
        and len(set(p.refs))==9
        and tuple(sorted({model.vertices[v].xyz for v in p.refs})) in fin_geo
    ]
    if len(fin_polygons)!=2:
        raise ValueError(f"Expected two one-sided textured fin faces: {len(fin_polygons)}")
    for side in (-1,1):
        visible,_,_=model.switched_polygons(
            None,(-31700,side*100000,22000),bsp_mode="original")
        shown=set(visible)&{p.offset for p in fin_polygons}
        if len(shown)!=1:
            raise ValueError(f"Fin must show exactly one legible side from y={side}: {shown}")
        side_test[str(side)]=next(iter(shown))
    if side_test["-1"]==side_test["1"]:
        raise ValueError("Fin's back-side number was not independently un-mirrored")
    return {"textured_polygon_count":len(textured),"mip_names":list(model.mip_names),
            "native_FACE_count":len(gates),"fin_side_events":side_test,
            "atlas_ranges":ATLAS_RECTS}


def build(baseline:Path,output:Path):
    if output.exists():
        raise FileExistsError(output)
    old=(baseline/"WASP.3D").read_text(encoding="utf-8")
    source,mapping=apply_texture(old)
    model,compiled=validate_source(source,model_path=output/"WASP.3D")
    if compiled["parser_warnings"]:
        raise ValueError(compiled["parser_warnings"])
    texture_check=check_compiled(model,mapping)
    checks=[event_check(model,(x,y,z))
            for x in (-150000,-40000,40000,150000)
            for y in (-100000,-25000,25000,100000)
            for z in (-6500,28000)]
    output.mkdir(parents=True)
    (output/"WASP.3D").write_text(source,encoding="utf-8")
    (output/"WASP.3do").write_bytes(model.raw)
    mip=install_to(output)
    for ext in ("FWHEEL","RWHEEL","HELMET"):
        p=baseline/(ext+".3do")
        if validate_path(p)["parser_warnings"]:
            raise ValueError(f"Invalid external object {ext}")
        shutil.copyfile(p,output/p.name)
        src=baseline/(ext+".3D")
        if src.exists():
            shutil.copyfile(src,output/src.name)
    manifest={
        "version":"V30e",
        "source":"V30d with original user supplied MARMON MIP",
        "geometry_changes":"Only original flat fin split into opposite FACE-culled texture sides",
        "bonnet_uv":"U across cross-section; V 0 at radiator and 72 at dashboard",
        "tail_uv":"U across cross-section; V 74 at seat and 127 at pointed tip",
        "radiator_uv":"U 0..47 lateral; V 0..42 top-to-bottom",
        "fin_uv":"U 104..127; V 131..154, independent nonmirrored number each side",
        "material":"MARMON",
        "texture_file":mip.name,
        "texture_file_sha256":SOURCE_SHA256,
        "source_baseline_sha256":sha256(old.encode()).hexdigest(),
        "uv_mapping":mapping,
        "texture_validation":texture_check,
        "camera_painter_checks":len(checks),
        "compilation":compiled,
        "binary_sha256":{p.name:sha256(p.read_bytes()).hexdigest()
                         for p in output.glob("*.3do")},
        "in_game_check_required":True,
    }
    (output/"v30e_manifest.json").write_text(
        json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
    return manifest


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--baseline",required=True,type=Path)
    ap.add_argument("--output",required=True,type=Path)
    opts=ap.parse_args(argv)
    m=build(opts.baseline,opts.output)
    print(json.dumps({
        "texture":m["texture_file"],
        "source_sha256":m["texture_file_sha256"],
        "textured_polygons":m["texture_validation"]["textured_polygon_count"],
        "FACE_gates":m["texture_validation"]["native_FACE_count"],
        "WASP_sha256":m["binary_sha256"]["WASP.3do"],
    },indent=2))


if __name__=="__main__":
    main()
