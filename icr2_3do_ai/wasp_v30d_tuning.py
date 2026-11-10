"""V30d Wasp: taper the tail's ground shadow and extend pilot torso/neck upward.

Input is a compiled and validated V30c package; never overwrite V29/V30c.
Only the shadow tail's four ground-plane vertices and the pilot's named
upper torso and neck vertices may change. HELMET DYNAMIC remains untouched.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil

from .stage2 import validate_source, validate_path
from .wasp_v30_touchups import event_check

_VERTEX_RE = re.compile(
    r"(?m)^([A-Za-z][A-Za-z0-9_]*): \[<(-?\d+), (-?\d+), (-?\d+)>\];$"
)
TAIL_SHADOW_POINTS = (
    (-38248, -150, -8501),
    (-33000, -5100, -8501),
    (-33000,  5100, -8501),
    (-38248,  150, -8501),
)
# Raw Papyrus coordinates: 6,000 units per foot; these are small, deliberate
# shape changes, not an entire driver translation or a helmet placement change.
TORSO_MID_RAISE = 180    # 0.36 in, softens upper body transition
TORSO_TOP_RAISE = 480    # 0.96 in, shoulders / torso upper rim
NECK_BOTTOM_RAISE = 240 # 0.48 in, retains significant torso/neck overlap
NECK_TOP_RAISE = 840    # 1.68 in, extends collar toward fixed HELMET sprite
EXPECTED_HELMET = (-600, 0, 12824)


def _named_vertices(source):
    return {
        m[1]: tuple(int(m[i]) for i in (2,3,4))
        for m in _VERTEX_RE.finditer(source)
    }


def _replace_vertex(source, name, old, new):
    old_line = f"{name}: [<{old[0]}, {old[1]}, {old[2]}>];"
    new_line = f"{name}: [<{new[0]}, {new[1]}, {new[2]}>];"
    if old == new or source.splitlines().count(old_line) != 1:
        raise ValueError(f"Unexpected baseline for {name}: {old}")
    return source.replace("\n"+old_line+"\n", "\n"+new_line+"\n", 1)


def tune_source(source):
    original = _named_vertices(source)
    expected_shadow = (
        (-41500, -6000, -8501),
        (-32500, -6000, -8501),
        (-32500,  6000, -8501),
        (-41500,  6000, -8501),
    )
    shadow_polygons = re.findall(
        r"(?m)^wasp_shadow_tail: POLY <(\d+)> \{([^}\n]+)\};$",source)
    expected_refs = [f"wasp_shadow_tail_v{i:02}" for i in range(4)]
    if shadow_polygons != [("27", ", ".join(expected_refs))]:
        raise ValueError("Unexpected original four-vertex tail shadow")
    # Physical tail ends at X=-38248 with ±150 raw half-width.
    # At X=-33000, the patch joins the body shadow at its existing ±5100 edge.
    for i, point in enumerate(TAIL_SHADOW_POINTS):
        name=f"wasp_shadow_tail_v{i:02}"
        if original.get(name) != expected_shadow[i]:
            raise ValueError(f"Unrecognized tail shadow silhouette {name}")
        source=_replace_vertex(source,name,original[name],point)

    movements={}
    for prefix, ring_deltas in (
        ("driver_torso", {**{i:TORSO_MID_RAISE for i in range(4,8)},
                          **{i:TORSO_TOP_RAISE for i in range(8,12)}}),
        ("driver_neck", {**{i:NECK_BOTTOM_RAISE for i in range(4)},
                         **{i:NECK_TOP_RAISE for i in range(4,8)}}),
    ):
        for index,dz in ring_deltas.items():
            name=f"{prefix}_v{index:04}"
            if name not in original:
                raise ValueError(f"Missing source vertex {name}")
            before=original[name]
            after=(before[0],before[1],before[2]+dz)
            source=_replace_vertex(source,name,before,after)
            movements[name]={"before":before,"after":after,"rise_raw":dz}

    actual=_named_vertices(source)
    if any(actual[f"wasp_shadow_tail_v{i:02}"]!=point
           for i,point in enumerate(TAIL_SHADOW_POINTS)):
        raise ValueError("New tapered shadow silhouette did not survive source edit")
    torso_top=[actual[f"driver_torso_v{i:04}"][2] for i in range(8,12)]
    neck_bottom=[actual[f"driver_neck_v{i:04}"][2] for i in range(4)]
    neck_top=[actual[f"driver_neck_v{i:04}"][2] for i in range(4,8)]
    if len(set(torso_top))!=1 or len(set(neck_bottom))!=1 or len(set(neck_top))!=1:
        raise ValueError("Driver top rings are not level")
    if not (neck_bottom[0]<torso_top[0]<neck_top[0]<EXPECTED_HELMET[2]):
        raise ValueError("Pilot collar geometry does not bridge upper torso to helmet")
    return source,{"shadow_tail_vertices":TAIL_SHADOW_POINTS,
                   "pilot_movements":movements,
                   "new_torso_top_z":torso_top[0],
                   "new_neck_bottom_z":neck_bottom[0],
                   "new_neck_top_z":neck_top[0],
                   "helmet_anchor":EXPECTED_HELMET}


def _check_compiled(model,source):
    vertex_map=_named_vertices(source)
    # The shadow is on the same height/palette as the 7 other original patches.
    tip=set(TAIL_SHADOW_POINTS)
    matches=[
        p for p in model.polygons.values()
        if p.color==27
        and {model.vertices[v].xyz for v in p.refs}==tip
    ]
    if len(matches)!=1:
        raise ValueError(f"Compiled tail shadow quadrilateral not found: {len(matches)}")
    shadow_z=-8501
    all_shadows=[p for p in model.polygons.values()
                 if p.color==27 and all(model.vertices[v].xyz[2]==shadow_z
                                       for v in p.refs)]
    if len(all_shadows)!=8:
        raise ValueError(f"Expected eight stock-style shadow patches, got {len(all_shadows)}")
    # No other shadow may protrude beyond the tapered tip or leave the tail seam.
    if not any(
        {(-33000,-5100,-8501),(-33000,5100,-8501)} <=
        {model.vertices[v].xyz for v in p.refs}
        for p in all_shadows
    ):
        raise ValueError("Tail taper base is disconnected")
    helmet=[d for d in model.dynamics.values() if d.name=="HELMET"]
    if len(helmet)!=1 or tuple(helmet[0].xyz)!=EXPECTED_HELMET:
        raise ValueError("Original stock helmet DYNAMIC was disturbed")
    # Native V30c face-culling nodes must remain unchanged in number.
    faces=sum(p.kind==5 for p in model.planes.values())
    if faces!=78:
        raise ValueError(f"One-sided V30c roof/cockpit FACE gates regressed: {faces}")
    return {"shadow_patches":len(all_shadows),"shadow_palette":27,
            "shadow_height":shadow_z,"helmet_anchor":EXPECTED_HELMET,
            "outward_roof_and_cockpit_face_gates":56}


def build(baseline:Path,output:Path):
    if output.exists():
        raise FileExistsError(output)
    source_file=baseline/"WASP.3D"
    old=source_file.read_text(encoding="utf-8")
    new,edits=tune_source(old)
    model,validation=validate_source(new,model_path=output/"WASP.3D")
    if validation["parser_warnings"]:
        raise ValueError(validation["parser_warnings"])
    structural=_check_compiled(model,new)
    painter=[event_check(model,(x,y,z))
             for x in (-150000,-40000,40000,150000)
             for y in (-100000,-25000,25000,100000)
             for z in (-6500,28000)]
    output.mkdir(parents=True)
    (output/"WASP.3D").write_text(new,encoding="utf-8")
    (output/"WASP.3do").write_bytes(model.raw)
    for name in ("FWHEEL","RWHEEL","HELMET"):
        b=baseline/(name+".3do")
        if validate_path(b)["parser_warnings"]:
            raise ValueError(f"Invalid {name} dependency")
        shutil.copyfile(b,output/b.name)
        editable=baseline/(name+".3D")
        if editable.exists():
            shutil.copyfile(editable,output/editable.name)
    manifest={
        "version":"V30d",
        "description":"Pointed/tapered tail ground shadow and raised torso/neck",
        "raw_units_per_foot":6000,
        "source_baseline":"V30c",
        "source_sha256_before":sha256(old.encode()).hexdigest(),
        "modifications":edits,
        "structural_checks":structural,
        "painter_camera_tests":painter,
        "compilation":validation,
        "binary_sha256":{p.name:sha256(p.read_bytes()).hexdigest()
                         for p in output.glob("*.3do")},
        "remaining_in_game_check":"helmet sprite chin gap and shadow silhouette"
    }
    (output/"v30d_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",
                                             encoding="utf-8")
    return manifest


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    opts=parser.parse_args(argv)
    m=build(opts.baseline,opts.output)
    print(json.dumps({
        "v30d_binary_sha256":m["binary_sha256"]["WASP.3do"],
        "shadow_patch_count":m["structural_checks"]["shadow_patches"],
        "new_torso_top_z":m["modifications"]["new_torso_top_z"],
        "new_neck_top_z":m["modifications"]["new_neck_top_z"],
        "checked_camera_positions":len(m["painter_camera_tests"])
    },indent=2))

if __name__=="__main__":
    main()
