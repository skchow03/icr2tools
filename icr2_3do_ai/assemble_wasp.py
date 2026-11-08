"""Assemble the 1911 Marmon Wasp as three N3 objects with real DYNAMIC wheel references.

This is a packaging/placement adapter. Geometry is generated and compiled by the
repository's existing Stage 2 and CAD compiler; this module invents no binary bytes.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil

from .stage2 import validate_source, validate_path


# Raw Papyrus coordinates (6000 / foot).
# Both wheel variants are defined in their own local coordinates at (0,0,0).
# Indy 500 2011 published specifications: 116-inch wheelbase and 187-inch
# overall length. Wheels have 34-inch OD: radius = 8500 raw ICR2 units.
# Front wheel x=2300 raw, radiator face x=2340 raw (0.08 inch difference).
# Rear center x=60300 raw => 58000 / 6000 * 12 = exactly 116 inches.
# Front tire leading x=-6200 raw, tail tip x=87300 raw => 93500 raw
# / 6000 * 12 = exactly 187 inches. The length is a fit to the reported
# specification, whereas the radiator/axle overlap is based on side photos.
WHEEL_PLACEMENTS = (
    ("front_left", "FWHEEL", (2300, -17400, 8500)),
    ("front_right", "FWHEEL", (2300, 17400, 8500)),
    ("rear_left", "RWHEEL", (60300, -16800, 8500)),
    ("rear_right", "RWHEEL", (60300, 16800, 8500)),
)
NOMINAL_WHEELBASE_IN = 116
NOMINAL_OVERALL_IN = 187
FRONT_RADIATOR_RAW_X = 2340
BODY_TAIL_RAW_X = 87300
TIRE_RADIUS_RAW = 8500
ROOT_RE = re.compile(r"(?m)^root:\s*LIST\s*\{([^{}]*)\};[ \t]*$")

# Stock retail car reference measured directly from the user-supplied binaries:
# indycar.3do has front centers (32284, ±17497, -2253), rear
# (-29426, ±16248, -2253); both stock wheels have radius 6503 raw units.
# So stock ground = -2253 - 6503 = -8756. Wasp tire radius=8500,
# giving new wheel-center Z=-256 for exactly matching ground contact.
# Stage2 recipe retains a convenient nose-to-tail (+X) design frame.
# Only final WASP.3D is rotated 180 degrees around Z and translated so
# +X is forward, x≈0 lies in the cockpit, and stock ground is z=-8756.
COCKPIT_DESIGN_X_RAW = 45000
STOCK_GROUND_RAW_Z = -8756
STOCK_WHEEL_RADIUS_RAW = 6503
STOCK_WHEEL_CENTER_RAW_Z = -2253
WASP_WHEEL_CENTER_RAW_Z = 8500 + STOCK_GROUND_RAW_Z
VERTEX_DECL_RE = re.compile(
    r'(?m)^([A-Za-z][A-Za-z0-9_]*:\s*\[<)\s*(-?\d+),\s*(-?\d+),\s*(-?\d+)(>\];)$'
)
DYNAMIC_DECL_RE = re.compile(
    r'(?m)^([A-Za-z][A-Za-z0-9_]*:\s*DYNAMIC\s+)'
    r'(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*(1),\s*(EXTERN\s+"[^"]+";)$'
)


def _game_coordinates(xyz):
    x, y, z = xyz
    return COCKPIT_DESIGN_X_RAW - x, -y, z + STOCK_GROUND_RAW_Z


def _game_source(source):
    """Rotate whole parent rigidly, keeping BSP planes and DYNAMICs in sync."""
    def vertex_repl(m):
        x,y,z = _game_coordinates(tuple(int(m.group(i)) for i in (2,3,4)))
        return f"{m.group(1)}{x}, {y}, {z}{m.group(5)}"
    source, vertex_n = VERTEX_DECL_RE.subn(vertex_repl,source)
    if vertex_n < 200:
        raise ValueError(f"Expected hundreds of body/BSP vertices, got {vertex_n}")

    def dynamic_repl(m):
        x,y,z = _game_coordinates(tuple(int(m.group(i)) for i in (2,3,4)))
        if tuple(int(m.group(i)) for i in (5,6,7)) != (0,0,0):
            raise ValueError("Unexpected wheel source rotation")
        # N3 angle units are tenths of a degree (1800 = half turn), not raw.
        return f"{m.group(1)}{x}, {y}, {z}, 1800, 0, 0, {m.group(8)}, {m.group(9)}"
    source, dynamic_n = DYNAMIC_DECL_RE.subn(dynamic_repl,source)
    if dynamic_n != 4:
        raise ValueError(f"Expected exactly 4 DYNAMIC children, got {dynamic_n}")
    return source + "\n% Game frame: forward +X, cockpit X=0, ground Z=-8756.\n"





# N3 BSPA sorts 3 layers as far/middle/near depending on the camera side.
# With these counter-clockwise planes, positive normals point toward +Y
# and +X respectively. The near-side body panels and wheels must always
# paint AFTER the main body and the far side.
Y_PLANE = "(wasp_y_a, wasp_y_b, wasp_y_c)"
X_PLANE = "(wasp_x_a, wasp_x_b, wasp_x_c)"
Y_WHEEL_PLANE = "(wheel_y_a, wheel_y_b, wheel_y_c)"


def _group(label: str, items: list[str]) -> str:
    if not items:
        raise ValueError(f"Empty named geometry group: {label}")
    return f'{label}: LIST {{{", ".join(items)}}};'


# The undercarriage paints BEFORE the yellow body even when the camera
# changes side. That is intentional for the 1995 ICR2 painter renderer.
CHASSIS_COMPONENTS = (
    "exposed_black_chassis_geo", "cockpit_floor_geo",
    "front_beam_axle_geo", "rear_chassis_extension_geo",
    "rear_beam_axle_geo",
    "front_leaf_fore_left_geo", "front_leaf_fore_right_geo",
    "front_leaf_aft_left_geo", "front_leaf_aft_right_geo",
    "rear_leaf_fore_left_geo", "rear_leaf_fore_right_geo",
    "rear_leaf_aft_left_geo", "rear_leaf_aft_right_geo",
)


def _sort_body_source(existing: str, wheel_symbols: list[str]) -> str:
    """Draw black chassis first, then camera-sort visible body and wheels."""
    parts = [v.strip() for v in existing.split(",")]
    if len(parts) != len(set(parts)):
        raise ValueError("Duplicate body components in source root")
    mandatory = {
        "radiator_face_geo", "long_bonnet_geo",
        "pointed_tail_geo", "rounded_tail_fin_geo",
    }
    if not mandatory <= set(parts):
        raise ValueError("Missing key bonnet/radiator/tail components")
    if not set(CHASSIS_COMPONENTS) <= set(parts):
        raise ValueError("Missing black chassis/suspension subcomponents")
    if len(wheel_symbols) != 4:
        raise ValueError("Expected four independently placed wheel references")

    frame = [p for p in parts if p in CHASSIS_COMPONENTS]
    pos, neg = [], []
    for part in parts:
        if part in CHASSIS_COMPONENTS:
            continue
        if "_right_" in part or part == "mirror_strut_right_geo":
            pos.append(part)
        elif "_left_" in part or part == "mirror_strut_left_geo":
            neg.append(part)
    if len(pos) != len(neg) or len(pos) != 6:
        raise ValueError("Expected five solid cockpit panels and one mirror strut per side")
    middle = [p for p in parts if p not in pos and p not in neg
              and p not in mandatory and p not in CHASSIS_COMPONENTS]
    if middle != ["mirror_housing_geo"]:
        raise ValueError(f"Unexpected mid-body components: {middle}")
    if sorted(frame) != sorted(CHASSIS_COMPONENTS):
        raise ValueError("Chassis component list differs from expected set")

    lines = [
        "% Camera-sorted body; black chassis intentionally paints before yellow.",
        "wasp_y_a: [<0, 0, 0>];",
        "wasp_y_b: [<0, 0, 6000>];",
        "wasp_y_c: [<6000, 0, 0>];",
        "wasp_x_a: [<45000, 0, 0>];",
        "wasp_x_b: [<45000, 6000, 0>];",
        "wasp_x_c: [<45000, 0, 6000>];",
        _group("wasp_black_frame", frame),
        _group("wasp_pos_sides", pos),
        _group("wasp_neg_sides", neg),
        _group("wasp_midparts", middle),
        _group("wasp_tailparts", ["pointed_tail_geo", "rounded_tail_fin_geo"]),
        f"wasp_noseparts: BSPN {X_PLANE}, long_bonnet_geo, radiator_face_geo;",
        f"wasp_body_xsort: BSPA {X_PLANE}, "
        "wasp_tailparts, wasp_midparts, wasp_noseparts;",
        f"wasp_body_ysort: BSPA {Y_PLANE}, "
        "wasp_pos_sides, wasp_body_xsort, wasp_neg_sides;",
        f"wasp_positive_wheels: BSPN {X_PLANE}, "
        f"{wheel_symbols[3]}, {wheel_symbols[1]};",
        f"wasp_negative_wheels: BSPN {X_PLANE}, "
        f"{wheel_symbols[2]}, {wheel_symbols[0]};",
        f"wasp_vehicle_sort: BSPA {Y_PLANE}, "
        "wasp_positive_wheels, wasp_body_ysort, wasp_negative_wheels;",
        "root: LIST {wasp_black_frame, wasp_vehicle_sort};",
    ]
    return "\n".join(lines)


def _sort_wheel_source(source: str) -> str:
    """BSP sort near yellow cover / hub over black tire, far cover behind it."""
    roots = list(ROOT_RE.finditer(source))
    if len(roots) != 1:
        raise ValueError(f"Expected one wheel root LIST, got {len(roots)}")
    m = roots[0]
    expected = {
        "black_firestone_tire_geo",
        "yellow_outer_cover_l_geo", "yellow_outer_cover_r_geo",
        "black_center_l_geo", "black_center_r_geo",
    }
    parts = set(p.strip() for p in m.group(1).split(","))
    if parts != expected:
        raise ValueError(f"Unexpected wheel components: {parts ^ expected}")
    extra = "\n".join([
        "% Rim/cover BSP: plus-Y side shows plus-Y cover last; vice versa.",
        "wheel_y_a: [<0, 0, 0>];",
        "wheel_y_b: [<0, 0, 6000>];",
        "wheel_y_c: [<6000, 0, 0>];",
        _group("wheel_pos_cover", ["yellow_outer_cover_r_geo",
                                    "black_center_r_geo"]),
        _group("wheel_neg_cover", ["yellow_outer_cover_l_geo",
                                    "black_center_l_geo"]),
        f"root: BSPA {Y_WHEEL_PLANE}, "
        "wheel_pos_cover, black_firestone_tire_geo, wheel_neg_cover;",
    ])
    return source[:m.start()] + extra + source[m.end():]



STOCK_SHADOW_Z_RAW = STOCK_GROUND_RAW_Z + 255     # stock indycar.3do -8501
STOCK_SHADOW_COLOR = 27                         # exact stock palette entry

# Eight polygons, just like the original stock 1995 IndyCar shadow.
# Main body patch plus nose, nose transverse patch, boat-tail patch and the
# four wheel contact patches. These are illustrative Wasp footprints.
SHADOW_POLYGONS = (
    ("body", (
        (13000, -4000), (13000, 4000), (10500, 8200), (6000, 9600),
        (-6000, 9500), (-33000, 5100), (-33000, -5100),
        (-6000, -9500), (6000, -9600), (10500, -8200),
    )),
    ("nose", ((13000,-4000), (44000,0), (13000,4000))),
    ("radiator", ((38000,-7200), (45500,-7200), (45500,7200), (38000,7200))),
    ("tail", ((-41500,-6000), (-32500,-6000), (-32500,6000), (-41500,6000))),
    ("front_left", ((36200,14200), (49300,14200), (49300,20800), (36200,20800))),
    ("front_right", ((36200,-20800), (49300,-20800), (49300,-14200), (36200,-14200))),
    ("rear_left", ((-22300,13400), (-8300,13400), (-8300,20300), (-22300,20300))),
    ("rear_right", ((-22300,-20300), (-8300,-20300), (-8300,-13400), (-22300,-13400))),
)


def _stock_style_shadow_source() -> str:
    """Generate the stock car's eight *flat*, ground-level polygon pattern."""
    lines = [
        "% Stock indycar.3do has eight flat shadow polygons at Z=-8501,",
        "% palette 27; copied conventions but tailored silhouette, not vertices.",
    ]
    names = []
    for component, points in SHADOW_POLYGONS:
        area2 = sum(a[0]*b[1] - b[0]*a[1]
                    for a,b in zip(points, points[1:]+points[:1]))
        if area2 <= 0:
            raise ValueError(f"Non-upward shadow polygon: {component}")
        verts = []
        for index, (x, y) in enumerate(points):
            symbol = f"wasp_shadow_{component}_v{index:02}"
            verts.append(symbol)
            lines.append(f"{symbol}: [<{x}, {y}, {STOCK_SHADOW_Z_RAW}>];")
        poly = f"wasp_shadow_{component}"
        names.append(poly)
        lines.append(f'{poly}: POLY <{STOCK_SHADOW_COLOR}> '
                     '{' + ", ".join(verts) + '};')
    lines.append(_group("wasp_ground_shadow", names))
    return "\n".join(lines)


def _omit_radiator_rear_cap(source: str) -> str:
    """Keep front radiator face & edge shell, omit ONLY its rear hexagon."""
    cap = "radiator_face_p0013"
    source, drop = re.subn(
        rf"(?m)^{cap}: POLY <0> \{{[^}}\n]+\}};\n", "", source
    )
    if drop != 1:
        raise ValueError(f"Expected precisely one {cap} declaration, got {drop}")
    group_match = re.search(r"(?m)^radiator_face_geo: LIST \{([^}\n]+)\};$",source)
    if group_match is None:
        raise ValueError("Cannot locate radiator LIST geometry")
    entries = [p.strip() for p in group_match.group(1).split(",")]
    if entries[-1] != cap or len(entries) != 14:
        raise ValueError("Radiator cap geometry has changed unexpectedly")
    entries.pop()
    source = source[:group_match.start()] + (
        "radiator_face_geo: LIST {" + ", ".join(entries) + "};"
    ) + source[group_match.end():]
    if "radiator_face_p0000: POLY" not in source:
        raise ValueError("Radiator forward face was accidentally removed")
    return source


def _attach_shadow_root(game_source: str) -> str:
    key = "root: LIST {wasp_black_frame, wasp_vehicle_sort};"
    if game_source.count(key) != 1:
        raise ValueError("Expected one black-frame + vehicle root LIST")
    value = (_stock_style_shadow_source() + "\n" +
             "root: LIST {wasp_ground_shadow, wasp_black_frame, "
             "wasp_vehicle_sort};")
    return game_source.replace(key, value)


def assemble(body_dir: Path, front_dir: Path, rear_dir: Path, output: Path):
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite {output}")
    for directory in (body_dir, front_dir, rear_dir):
        if not (directory / "model.3D").is_file() or not (directory / "model.3do").is_file():
            raise FileNotFoundError(f"Expected validated Stage 2 model files in {directory}")

    body = (body_dir / "model.3D").read_text(encoding="utf-8")
    if "wheel_FL_locator" in body or "wheel_RL_locator" in body:
        raise ValueError("Body recipe still includes wheel cubes; remove them first")
    front_x = WHEEL_PLACEMENTS[0][2][0]
    rear_x = WHEEL_PLACEMENTS[2][2][0]
    wheelbase_in = (rear_x - front_x) / 6000 * 12
    length_in = (BODY_TAIL_RAW_X - (front_x - TIRE_RADIUS_RAW)) / 6000 * 12
    radiator_to_front_axle_in = (front_x - FRONT_RADIATOR_RAW_X) / 6000 * 12
    if abs(wheelbase_in - NOMINAL_WHEELBASE_IN) > 0.001:
        raise ValueError(f"Wheelbase mismatch: {wheelbase_in} inches")
    if abs(length_in - NOMINAL_OVERALL_IN) > 0.001:
        raise ValueError(f"Overall length mismatch: {length_in} inches")
    if abs(radiator_to_front_axle_in) > 1:
        raise ValueError("Front axle not aligned with radiator front")

    roots = list(ROOT_RE.finditer(body))
    if len(roots) != 1:
        raise ValueError(f"Expected one root LIST in body source, found {len(roots)}")

    m = roots[0]
    wheel_symbols = []
    placement_lines = []
    for name, target, (x, y, z) in WHEEL_PLACEMENTS:
        symbol = "wasp_" + name
        wheel_symbols.append(symbol)
        placement_lines.append(
            f'{symbol}: DYNAMIC {x}, {y}, {z}, 0, 0, 0, 1, EXTERN "{target}";'
        )

    existing = m.group(1).strip()
    new_root = _sort_body_source(existing, wheel_symbols)
    wasp_text = (
        body[:m.start()] +
        '\n% Four reusable wheels and BSP-sorted body / front-rear geometry.\n' +
        '\n'.join(placement_lines) + '\n' + new_root +
        body[m.end():]
    )
    wasp_text = _attach_shadow_root(
        _game_source(_omit_radiator_rear_cap(wasp_text))
    )

    # Real N3 compiler and parser verify all parent source records and external names.
    model, result = validate_source(wasp_text, model_path=output / "WASP.3D")
    if model.records[model.root_offset] != 11:
        raise ValueError("WASP root should be ordered LIST shadow/frame/BSPA")
    root_children = model.children.get(model.root_offset, [])
    if [model.records.get(i) for i in root_children] != [11, 11, 8]:
        raise ValueError("WASP root not shadow, chassis, BSPA in that order")
    shadow_geo, frame_geo, car_sort = root_children
    if len(model.children[shadow_geo]) != 8:
        raise ValueError("Wasp shadow must have exactly 8 polygons")
    for off in model.children[shadow_geo]:
        p = model.polygons[off]
        zvals = {model.vertices[v].xyz[2] for v in p.refs}
        if p.color != 27 or zvals != {STOCK_SHADOW_Z_RAW}:
            raise ValueError("Shadow color/height differs from stock car")
    if len(model.children[frame_geo]) != 13:
        raise ValueError("Chassis must have 13 named, first-drawn components")
    radiator_back_x_raw = _game_coordinates((3300, 0, 0))[0]
    if any(p.color == 0 and len(p.refs) == 6
           and all(model.vertices[v].xyz[0] == radiator_back_x_raw
                   for v in p.refs)
           for p in model.polygons.values()):
        raise ValueError("Radiator rear cap still reachable")
    if set(model.external_names) != {"FWHEEL", "RWHEEL"}:
        raise ValueError(f"Incorrect external filenames: {model.external_names}")
    if len(model.dynamics) != 4:
        raise ValueError(f"Expected four DYNAMIC wheel objects; found {len(model.dynamics)}")
    placements = {(tuple(obj.xyz), obj.name) for obj in model.dynamics.values()}
    expected = {(_game_coordinates(loc), ref) for _name, ref, loc in WHEEL_PLACEMENTS}
    for dyn in model.dynamics.values():
        if dyn.angles != (-(1 << 31), 0, 0):
            raise ValueError(f"Wheel orientation incorrect: {dyn.name} {dyn.angles}")
    if placements != expected:
        raise ValueError(f"Wrong wheel instance placements: {placements!r}")
    game_front = _game_coordinates(WHEEL_PLACEMENTS[0][2])
    game_rear = _game_coordinates(WHEEL_PLACEMENTS[2][2])
    if not game_front[0] > 0 > game_rear[0]:
        raise ValueError(f"Front car orientation reversed: {game_front}, {game_rear}")
    if not game_front[2] == game_rear[2] == WASP_WHEEL_CENTER_RAW_Z:
        raise ValueError("Wasp wheel centers do not share stock-compatible height")
    if game_front[2] - TIRE_RADIUS_RAW != STOCK_GROUND_RAW_Z:
        raise ValueError("Wasp tires do not meet stock ICR2 wheel-ground height")
    if game_front[0] - game_rear[0] != 58000:
        raise ValueError("Post-rotation wheelbase no longer 116 inches")
    # Cockpit opening spans x=6.10..8.98 feet in design coordinates.
    if not (36600 < COCKPIT_DESIGN_X_RAW < 53880):
        raise ValueError("Game origin must lie within the cockpit opening")

    # Verify real compiled traversal from each lateral camera:
    # eight flat ground shadows -> complete black chassis ->
    # far wheel instances -> painted body -> near wheel instances.
    bsp_tests = {}
    expected_frame_polygons = 114      # 5 capped boxes + 8 uncapped leaf pieces
    for side in (-1, 1):
        events = []
        model.switched_polygons(
            None, (0, side * 300000, 30000),
            bsp_mode="original", events=events,
        )
        ordered = [
            (i, model.dynamics[event[1]].xyz[1])
            for i, event in enumerate(events) if event[0] == "dynamic"
        ]
        polygon_positions = [
            (i, model.polygons[event[1]])
            for i, event in enumerate(events) if event[0] == "polygon"
        ]
        if len(ordered) != 4 or len(polygon_positions) < 300:
            raise ValueError("BSP order omitted a wheel or body polygon")
        if [p.color for _,p in polygon_positions[:8]] != [STOCK_SHADOW_COLOR]*8:
            raise ValueError("Stock-style shadow must render first")
        if [p.color for _,p in polygon_positions[8:8+expected_frame_polygons]] != [0]*expected_frame_polygons:
            raise ValueError("Every black chassis polygon must draw before the body")
        after_frame = polygon_positions[8+expected_frame_polygons:]
        first_yellow = min(i for i,p in after_frame if p.color in (158,159))
        last_yellow = max(i for i,p in after_frame if p.color in (158,159))
        if polygon_positions[8+expected_frame_polygons-1][0] >= first_yellow:
            raise ValueError("Chassis painted on top of colored bodywork")
        far = [i for i,y in ordered if y*side < 0]
        near = [i for i,y in ordered if y*side > 0]
        if (len(far) != 2 or len(near) != 2
                or max(far) >= first_yellow
                or last_yellow >= min(near)):
            raise ValueError(
                f"Wheel/paint BSP order wrong from side {side}: "
                f"far={far}, first/last yellow={first_yellow}/{last_yellow}, near={near}"
            )
        bsp_tests[str(side)] = {
            "stock_style_shadow_first": True,
            "shadow_polygon_count": 8,
            "shadow_palette_index": 27,
            "shadow_raw_z": STOCK_SHADOW_Z_RAW,
            "black_chassis_before_body": True,
            "frame_polygon_count": expected_frame_polygons,
            "radiator_rear_cap_removed": True,
            "far_wheels_before_body": True,
            "near_wheels_after_body": True,
            "body_polygon_events": len(polygon_positions),
        }

    output.mkdir(parents=True, exist_ok=False)
    (output / "WASP.3D").write_text(wasp_text, encoding="utf-8")
    (output / "WASP.3do").write_bytes(model.raw)

    for obj_name, directory in (("FWHEEL", front_dir), ("RWHEEL", rear_dir)):
        ordered_source = _sort_wheel_source(
            (directory / "model.3D").read_text(encoding="utf-8")
        )
        ordered_model, _ = validate_source(
            ordered_source, model_path=output / (obj_name + ".3D")
        )
        if re.search(r'POLY\\s*<(?:47|48|49)>', ordered_source):
            raise ValueError(f"Non-safe dark gray colors remain in {obj_name}")
        if ordered_model.records[ordered_model.root_offset] != 8:
            raise ValueError(f"{obj_name} root is not BSPA")
        (output / (obj_name + ".3D")).write_text(
            ordered_source, encoding="utf-8"
        )
        (output / (obj_name + ".3do")).write_bytes(ordered_model.raw)

    checks = {}
    for name in ("WASP", "FWHEEL", "RWHEEL"):
        binary = output / (name + ".3do")
        check = validate_path(binary)
        if check["parser_warnings"]:
            raise RuntimeError(f"Parser warnings in {name}: {check['parser_warnings']}")
        checks[name] = check

    for recname, directory in (
        ("body_recipe.json", body_dir),
        ("front_wheel_recipe.json", front_dir),
        ("rear_wheel_recipe.json", rear_dir),
    ):
        shutil.copy2(directory / "recipe.json", output / recname)

    (output / "README.txt").write_text(
        "1911 MARMON WASP - THREE-OBJECT ICR2 N3 ASSEMBLY\n"
        "================================================\n"
        "Edit WASP.3D (main body), FWHEEL.3D (front wheel) and RWHEEL.3D (rear wheel).\n"
        "Place WASP.3do, FWHEEL.3do and RWHEEL.3do together in the same model folder.\n"
        "WASP.3do holds four DYNAMIC external references, two to each wheel model.\n"
        "No wheel cubes remain in the parent; wheels originate at their own axle center.\n"
        "GAME ORIENTATION: forward is +X, origin inside cockpit, Z=-8756 at ground.\n"
        "Wasp wheel centers Z=-256; 34in radius tires touch stock ICR2 ground.\n"
        "Wheel positions, raw Papyrus units (6000 per foot):\n" +
        "".join(
            f"  {name}: {target} at {tuple(_game_coordinates(loc))}\n"
            for name, target, loc in WHEEL_PLACEMENTS
        ) +
        "Axles and leaf springs are body geometry, not separate wheel geometry.\n"
        "Body U-shaped cockpit walls are solid, made of five joined facets per side.\n"
        "Tire size 34x4.5 inches, steel wheel covers nominal 25 inches; polygonal.\n"
        "Wheel and body BSPA sorting is authored; in-game BSP and LOD testing remain.\n"
        "Black is reserved common palette index 0; no MIP textures.\n"
        "Shadow: eight flat polygons, palette 27 at raw Z=-8501, stock ICR2 convention.\n"
        "Rear radiator cap omitted; black frame always drawn before colored body.\n",
        encoding="utf-8",
    )
    manifest = {
        "description": "Marmon Wasp body plus external front and rear wheels",
        "wheel_placements": [
            {"name": name, "external": target, "translation_raw": list(loc)}
            for name, target, loc in WHEEL_PLACEMENTS
        ],
        "external_names": list(model.external_names),
        "stock_icr2_reference": {
            "positive_x_forward": True,
            "stock_front_center_raw": [32284, 17497, -2253],
            "stock_rear_center_raw": [-29426, 16248, -2253],
            "stock_wheel_radius_raw": STOCK_WHEEL_RADIUS_RAW,
            "stock_ground_raw_z": STOCK_GROUND_RAW_Z,
            "wasp_wheel_center_raw_z": WASP_WHEEL_CENTER_RAW_Z,
            "wasp_front_center_game_raw": list(game_front),
            "wasp_rear_center_game_raw": list(game_rear),
            "cockpit_center_design_raw_x": COCKPIT_DESIGN_X_RAW,
            "rotation_about_vertical_n3_tenths_degrees": 1800,
            "measured_from": "user-supplied stock indycar.3do, fwheel.3do, rwheel.3do",
        },
        "dimensions": {
            "wheelbase_inches": wheelbase_in,
            "overall_length_inches": length_in,
            "radiator_front_to_front_axle_inches": radiator_to_front_axle_in,
            "documented_source": "INDYCAR/IMS 2011 centennial specifications",
            "radiator_axle_alignment": "photograph-guided estimate; not a published measurement",
        },
        "source_files": ["WASP.3D", "FWHEEL.3D", "RWHEEL.3D"],
        "binary_files": ["WASP.3do", "FWHEEL.3do", "RWHEEL.3do"],
        "validation": checks,
        "stock_style_shadow": {
            "polygon_count": 8,
            "palette_index": 27,
            "raw_z": STOCK_SHADOW_Z_RAW,
            "stock_ground_raw_z": STOCK_GROUND_RAW_Z,
            "offset_above_ground_raw": 255,
            "source": "user-provided stock indycar.3do shadow POLY group",
        },
        "radiator_rear_cap_removed": True,
        "chassis_painted_first": True,
        "bsp_camera_sides": bsp_tests,
        "body_with_placements": result,
        "sha256": {
            p.name: sha256(p.read_bytes()).hexdigest()
            for p in output.iterdir() if p.suffix.lower() == ".3do"
        },
    }
    (output / "assembly_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--body", type=Path, required=True)
    ap.add_argument("--front", type=Path, required=True)
    ap.add_argument("--rear", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args(argv)
    result = assemble(args.body, args.front, args.rear, args.output)
    print(json.dumps({
        "components": "WASP+FWHEEL+RWHEEL",
        "binary_polygons": {name: r["polygons"] for name, r in result["validation"].items()},
        "external_names": result["external_names"],
        "placements": result["wheel_placements"],
    }, indent=2))


if __name__ == "__main__":
    main()
