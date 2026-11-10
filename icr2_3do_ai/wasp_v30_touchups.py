"""Apply V30 Wasp touchups to a validated V29 assembly without changing V29.

Compile with the repository's existing N3 compiler and binary parser.
"""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
from .stage2 import validate_path, validate_source

FRONT_X, REAR_X, OLD_FRONT_X = 43671, 41700, 42660
VERTEX = re.compile(r"(?m)^([A-Za-z][A-Za-z0-9_]*): \[<(-?\d+), (-?\d+), (-?\d+)>\];$")


def vertices(src):
    result = {}
    for m in VERTEX.finditer(src):
        if m[1] in result:
            raise ValueError(f"Duplicate N3 vertex: {m[1]}")
        result[m[1]] = tuple(int(m[i]) for i in (2, 3, 4))
    return result


def change(src, symbol, before, after):
    old, new = f"{symbol}: {before};", f"{symbol}: {after};"
    if old == new or src.splitlines().count(old) != 1:
        raise ValueError(f"Unexpected V29 declaration: {symbol}")
    return src.replace("\n"+old+"\n", "\n"+new+"\n", 1)


def edit(src):
    original = vertices(src)
    fmt = lambda xyz: "[<" + ", ".join(map(str, xyz)) + ">]"
    front = [original[f"radiator_face_v{i:04}"] for i in range(6)]
    rear = [original[f"radiator_face_v{i:04}"] for i in range(6, 12)]
    bonnet = [original[f"long_bonnet_v{i:04}"] for i in range(6)]
    if ({p[0] for p in front}, {p[0] for p in rear},
            {p[0] for p in bonnet}) != ({OLD_FRONT_X}, {REAR_X}, {REAR_X}):
        raise ValueError("Unknown radiator/bonnet baseline geometry")
    if rear == bonnet:
        raise ValueError("Radiator seam is already sealed")
    for i, p in enumerate(front):
        src = change(src, f"radiator_face_v{i:04}", fmt(p),
                     fmt((FRONT_X, p[1], p[2])))
    for i, (p, target) in enumerate(zip(rear, bonnet), 6):
        src = change(src, f"radiator_face_v{i:04}", fmt(p), fmt(target))
    # Keep the +X-only front FACE gate exactly 60 raw units behind the grille.
    for symbol in ("wasp_rad_face_a", "wasp_rad_face_b", "wasp_rad_face_c"):
        p = original[symbol]
        if p[0] != 42600:
            raise ValueError("Unexpected original grille FACE gate")
        src = change(src, symbol, fmt(p), fmt((FRONT_X-60, p[1], p[2])))
    # All outer body and roof layers belong inside the SAME X-dependent painter
    # branch. V30's final LIST overlay painted the helmet and front bonnet roof
    # over the tail's visible sidewall from rear/low cameras.
    src = change(src, "wasp_frame_and_body",
        "LIST {wasp_black_frame, wasp_body_ysort, wasp_upper_skin, wasp_ornaments, wasp_driver_helmet}",
        "LIST {wasp_black_frame, wasp_body_ysort}")
    src = change(src, "wasp_body_xsort",
        "BSPA (wasp_x_a, wasp_x_b, wasp_x_c), wasp_tailparts, wasp_driver_center, wasp_nose_shell",
        "BSPA (wasp_x_a, wasp_x_b, wasp_x_c), wasp_rear_depth, wasp_pilot_depth, wasp_front_depth")
    if "wasp_rear_depth:" in src:
        raise ValueError("V30 occlusion tree already declared")
    src += """
% V30 fixed: X sort ALL tail outer polygons including sidewalls, not just roof.
% The middle camera-dependent layer contains the helmet; the complete tail
% paints after it from behind, and the complete nose paints after it in front.
% Existing Y BSPA then paints near-side cockpit sidewalls last.
wasp_rear_depth: LIST {wasp_tailparts, wasp_tail_roof_geo, rounded_tail_fin_geo};
wasp_pilot_depth: LIST {wasp_driver_center, wasp_driver_helmet};
wasp_front_depth: LIST {wasp_nose_shell, wasp_bonnet_roof_geo, wasp_mirror_strut_sort, radiator_face_geo};
"""
    result = vertices(src)
    assert [result[f"radiator_face_v{i:04}"] for i in range(6,12)] == bonnet
    return src


def event_check(model, eye):
    events=[]
    model.switched_polygons(None,eye,bsp_mode="original",events=events)
    helmet=[i for i,e in enumerate(events) if e[0]=="dynamic" and model.dynamics[e[1]].name=="HELMET"]
    grille=[]; tail=[]; mirror=[]; tail_sides=[]; bonnet_roof=[]; near_cockpit=[]
    for i,e in enumerate(events):
        if e[0]!="polygon": continue
        poly=model.polygons[e[1]]
        pts=[model.vertices[v].xyz for v in poly.refs]
        if poly.color==33 and len(set(poly.refs))==6 and all(p[0]==FRONT_X for p in pts): grille.append(i)
        if poly.color==158 and pts and all(p[0]<=-3000 for p in pts) and min(p[2] for p in pts)>=12000: tail.append(i)
        if poly.color in (158,40) and pts and all(13300<=p[0]<=16000 for p in pts) and min(p[2] for p in pts)>14500: mirror.append(i)
        if (poly.color in (158,159) and pts
                and all(p[0]<=-3000 for p in pts)
                and any(abs(p[1])>3500 for p in pts)
                and min(p[2] for p in pts)<13000):
            tail_sides.append(i)
        if (poly.color==158 and pts
                and all(p[0]>=13013 for p in pts)
                and any(p[2]>=11900 for p in pts)):
            bonnet_roof.append(i)
    if len(helmet)!=1 or not tail or not tail_sides or not bonnet_roof:
        raise ValueError(f"Missing helmet/tail in {eye}: {helmet}, {len(tail)}")
    h=helmet[0]
    if eye[0]>0:
        if len(grille)!=1 or not max(tail)<h<grille[0] or max(tail_sides)>=h:
            raise ValueError(f"Incorrect forward painter sequence {eye}: tail {tail}, head {h}, grille {grille}")
        if mirror and max(mirror)>=grille[0]:
            raise ValueError(f"Mirrors paint through forward grille at {eye}")
    else:
        if (grille or min(tail)<=h or min(tail_sides)<=h
                or max(bonnet_roof)>=min(tail_sides)
                or (mirror and max(mirror)>=h)):
            raise ValueError(f"Incorrect rear painter sequence {eye}: head {h}, tail {tail}, grille {grille}")
    return {"camera":list(eye),"helmet_event":h,"grille_events":grille,"tail_roof_events":len(tail),"tail_side_events":len(tail_sides),"bonnet_roof_events":len(bonnet_roof),"mirror_events":len(mirror)}


def build(baseline:Path,output:Path):
    if output.exists(): raise FileExistsError(output)
    old=(baseline/"WASP.3D").read_text(encoding="utf-8")
    src=edit(old)
    model,validation=validate_source(src,model_path=output/"WASP.3D")
    if validation["parser_warnings"]: raise ValueError(validation["parser_warnings"])
    checks=[event_check(model,(x,y,z)) for x in (-150000,-40000,40000,150000)
            for y in (-100000,-25000,25000,100000) for z in (-6500,28000)]
    output.mkdir(parents=True)
    (output/"WASP.3D").write_text(src,encoding="utf-8")
    (output/"WASP.3do").write_bytes(model.raw)
    for name in ("FWHEEL","RWHEEL","HELMET"):
        path=baseline/(name+".3do")
        if validate_path(path)["parser_warnings"]: raise ValueError(f"Invalid {name}")
        shutil.copyfile(path,output/path.name)
        n3=baseline/(name+".3D")
        if n3.is_file(): shutil.copyfile(n3,output/n3.name)
    manifest={"version":"V30","source":"V29 edited N3 assembly",
        "radiator_front_game_x":FRONT_X,"radiator_rear_seam_game_x":REAR_X,
        "seam":"6 exact matching radiator/bonnet vertices",
        "view_sort":"single BSPA rear-tail-side-and-roof, sprite-helmet, front-bonnet-and-radiator within Y-sorted body",
        "validated_compilation":validation,"painter_camera_tests":checks,
        "input_v29_source_sha256":sha256(old.encode()).hexdigest(),
        "binary_sha256":{p.name:sha256(p.read_bytes()).hexdigest() for p in output.glob("*.3do")},
        "requires_in_game_check":True}
    (output/"v30_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    return manifest


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--baseline",required=True,type=Path)
    ap.add_argument("--output",required=True,type=Path)
    args=ap.parse_args(argv)
    result=build(args.baseline,args.output)
    print(json.dumps({"hashes":result["binary_sha256"],"checked_cameras":len(result["painter_camera_tests"])},indent=2))

if __name__=="__main__": main()
