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
    """View-sort far wheels, then black chassis, yellow body, near wheels."""
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
        "% The far wheels go UNDER black frame; near wheels remain foreground.",
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
        "wasp_frame_and_body: LIST {wasp_black_frame, wasp_body_ysort};",
        f"wasp_vehicle_sort: BSPA {Y_PLANE}, "
        "wasp_positive_wheels, wasp_frame_and_body, wasp_negative_wheels;",
        "root: LIST {wasp_vehicle_sort};",
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


# Radiator's outer front cap is in the finished +X-forward game frame
# at x=42660 raw (original design x=0.39 ft). The previous x=0 BSPN was
# merely a painter SORT plane, so it could not back-face-cull this cap.
# Place a new *one-sided* front-face plane at x=42600, 60 raw units (0.12in)
# behind the radiator front. Positive X is the only visible viewing side.
RADIATOR_FRONT_X_RAW = 42660
RADIATOR_VIS_PLANE_X_RAW = 42600


def _attach_radiator_front_cull(game_source: str) -> str:
    """Cull the grille from behind, but retain only the near-side rim surfaces.

    The rim is a 6-segment extruded hexagon: triangles 1..12 form six
    consecutive pairs around the perimeter. Each pair gets its own FACE
    node using the actual outer surface winding, not the grille's +X plane.
    This restores side-visible black radiator frame without showing the
    opposite-side triangles through the yellow bonnet.
    """
    group = re.search(
        r"(?m)^radiator_face_geo: LIST \{([^}\n]+)\};$",game_source
    )
    if group is None:
        raise ValueError("No open-backed radiator model group found")
    elements = [x.strip() for x in group.group(1).split(",")]
    front = "radiator_face_p0000"
    rim_polys = [f"radiator_face_p{i:04}" for i in range(1, 13)]
    if elements != [front] + rim_polys:
        raise ValueError(f"Unexpected radiator front and rim members: {elements!r}")
    if "radiator_face_p0013:" in game_source:
        raise ValueError("Rear radiator cap must remain physically absent")

    # Preserve the bonnet/radiator BSPN painter sorting, but its radiator
    # branch now contains independently culled front and perimeter groups.
    nose_old = ("wasp_noseparts: BSPN "
                "(wasp_x_a, wasp_x_b, wasp_x_c), "
                "long_bonnet_geo, radiator_face_geo;")
    if game_source.count(nose_old) != 1:
        raise ValueError("Cannot locate nose sorting reference")
    # No need to edit the existing sorting reference: it continues to point
    # to radiator_face_geo, whose content is replaced below.

    side_names = [f"wasp_rad_rim_side{i}" for i in range(6)]
    replacement_list = [ "wasp_rad_front_only" ] + side_names
    game_source = (
        game_source[:group.start()]
        + "radiator_face_geo: LIST {" + ", ".join(replacement_list) + "};"
        + game_source[group.end():]
    )

    # Front hexagon remains culled by the +X-facing plane at X=42600,
    # 60 Papyrus units (0.12in) behind the grille face.
    lines = [
        "% Front radiator is one-sided; rim sections have independent normals.",
        f"wasp_rad_face_a: [<{RADIATOR_VIS_PLANE_X_RAW}, -1200, -3000>];",
        f"wasp_rad_face_b: [<{RADIATOR_VIS_PLANE_X_RAW}, 1200, -3000>];",
        f"wasp_rad_face_c: [<{RADIATOR_VIS_PLANE_X_RAW}, 0, -1000>];",
        "wasp_rad_front_only: FACE "
        "(wasp_rad_face_a, wasp_rad_face_b, wasp_rad_face_c), "
        "radiator_face_p0000;",
    ]
    # In every perimeter quad the first triangle follows the sequence
    # front_a -> front_b -> back_b, whose winding faces OUTWARD. The same
    # exterior FACE controls both triangles; no new triangles are added.
    for segment in range(6):
        first = 1 + 2*segment
        second = first + 1
        a = segment
        b = (segment + 1) % 6
        c = b + 6
        lines.append(
            f"wasp_rad_rim_pair{segment}: LIST "
            "{"+f"radiator_face_p{first:04}, radiator_face_p{second:04}"+"};"
        )
        lines.append(
            f"wasp_rad_rim_side{segment}: FACE "
            f"(radiator_face_v{a:04}, radiator_face_v{b:04}, "
            f"radiator_face_v{c:04}), wasp_rad_rim_pair{segment};"
        )

    if "wasp_rad_front_only:" in game_source:
        raise ValueError("Radiator culling has already been applied")
    return game_source + "\n" + "\n".join(lines) + "\n"


def _attach_shadow_root(game_source: str) -> str:
    key = "root: LIST {wasp_vehicle_sort};"
    if game_source.count(key) != 1:
        raise ValueError("Expected one black-frame + vehicle root LIST")
    value = (_stock_style_shadow_source() + "\n" +
             "root: LIST {wasp_ground_shadow, wasp_vehicle_sort};")
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
        _attach_radiator_front_cull(
            _game_source(_omit_radiator_rear_cap(wasp_text))
        )
    )

    # Real N3 compiler and parser verify all parent source records and external names.
    model, result = validate_source(wasp_text, model_path=output / "WASP.3D")
    if model.records[model.root_offset] != 11:
        raise ValueError("WASP root should be LIST shadow/BSPA")
    root_children = model.children.get(model.root_offset, [])
    if [model.records.get(i) for i in root_children] != [11, 8]:
        raise ValueError("WASP root not shadow, BSPA in that order")
    shadow_geo, car_sort = root_children
    vehicle_bsp = model.children.get(car_sort, [])
    if len(vehicle_bsp) != 3:
        raise ValueError("Vehicle sorter should have 3 camera-dependent layers")
    # Binary BSPA child pointer order is [far, near, middle]. The middle
    # is always an ordered LIST: black frame, then yellow body.
    middle_candidates = [p for p in vehicle_bsp if model.records.get(p) == 11]
    if len(middle_candidates) != 1:
        raise ValueError("Vehicle BSPA missing ordered black-frame/paint group")
    body_layer = middle_candidates[0]
    layer_children = model.children.get(body_layer, [])
    if [model.records.get(i) for i in layer_children] != [11, 8]:
        raise ValueError("Frame/paint must render as chassis LIST then body BSPA")
    frame_geo, painted_geo = layer_children
    if len(model.children[shadow_geo]) != 8:
        raise ValueError("Wasp shadow must have exactly 8 polygons")
    for off in model.children[shadow_geo]:
        p = model.polygons[off]
        zvals = {model.vertices[v].xyz[2] for v in p.refs}
        if p.color != 27 or zvals != {STOCK_SHADOW_Z_RAW}:
            raise ValueError("Shadow color/height differs from stock car")
    if len(model.children[frame_geo]) != 13:
        raise ValueError("Chassis must have 13 named, first-drawn components")

    # All seven one-sided FACE nodes must be present in the REAL compiled
    # N3: one front grille, six surface-oriented two-triangle rim sectors.
    radiator_front_caps = [
        p.offset for p in model.polygons.values()
        if p.color == 0 and len(set(p.refs)) == 6
        and all(model.vertices[v].xyz[0] == RADIATOR_FRONT_X_RAW
                for v in p.refs)
    ]
    if len(radiator_front_caps) != 1:
        raise ValueError(f"Radiator front hexagon missing: {radiator_front_caps}")
    radiator_front_offset = radiator_front_caps[0]
    face_nodes = [p for p in model.planes.values() if p.kind == 5]
    if len(face_nodes) != 7:
        raise ValueError(f"Expected 7 radiator FACE nodes, got {len(face_nodes)}")

    front_face_nodes = [
        p for p in face_nodes
        if p.equation[0] > 0 and p.equation[1] == p.equation[2] == 0
        and abs(-p.equation[3]/p.equation[0] - RADIATOR_VIS_PLANE_X_RAW)<0.001
    ]
    if len(front_face_nodes) != 1:
        raise ValueError("Front grille must have one +X-only FACE plane")
    front_face_node = front_face_nodes[0]
    if model.children.get(front_face_node.offset) != [radiator_front_offset]:
        raise ValueError("Grille FACE must wrap only the radiator hexagon")

    rim_groups = []
    rim_faces = []
    for face in face_nodes:
        if face.offset == front_face_node.offset:
            continue
        child = model.children.get(face.offset, [])
        if len(child) != 1 or model.records.get(child[0]) != 11:
            raise ValueError("Every radiator rim FACE must wrap one pair LIST")
        offsets = tuple(model.children[child[0]])
        if len(offsets) != 2 or any(off not in model.polygons for off in offsets):
            raise ValueError("Rim FACE must wrap exactly two surface triangles")
        rim_groups.append((face, offsets))
        rim_faces.extend(offsets)
    if len(rim_groups) != 6 or len(set(rim_faces)) != 12:
        raise ValueError("Six unique radiator rim pairs not present")

    # Determine a source polygon's outward-facing side from its normal,
    # not from presumed numeric offsets. The exact outer face normals are
    # tied to the six physical faces of the hexagonal radiator housing.
    def side_counts(polys, camera_side):
        active = set(polys)
        rim_visible = [off for off in rim_faces if off in active]
        near_groups = [
            (face, members) for face,members in rim_groups
            if face.equation[1] * camera_side > 0
        ]
        far_groups = [
            (face, members) for face,members in rim_groups
            if face.equation[1] * camera_side < 0
        ]
        near_faces = {off for face, members in near_groups for off in members}
        far_faces = {off for face, members in far_groups for off in members}
        return rim_visible,near_faces,far_faces

    # Camera tests cover low side views and elevated obliques.
    # Front cap depends solely on X>42600. The near-side exterior frame
    # must appear at both Y sides, while far-side triangles are absent.
    visibility_checks = {}
    for side in (-1, 1):
        for x in (100000, RADIATOR_VIS_PLANE_X_RAW+10,
                  RADIATOR_VIS_PLANE_X_RAW-10, 0, -100000):
            for z in (3500, 12000):
                camera = (x, side*90000, z)
                polys,_stats,_lod = model.switched_polygons(
                    None,camera,bsp_mode="original")
                visible = set(polys)
                front_expected = x > RADIATOR_VIS_PLANE_X_RAW
                if (radiator_front_offset in visible) != front_expected:
                    raise ValueError(f"Front radiator cull failed at {camera}")
                rim_visible, near_faces, far_faces = side_counts(polys,side)
                if len(near_faces) < 4 or len(far_faces) < 4:
                    raise ValueError("Bad exterior normal distribution in rim FACE nodes")
                if not (set(rim_visible) & near_faces):
                    raise ValueError(f"Near-side radiator frame missing at {camera}")
                if set(rim_visible) & far_faces:
                    raise ValueError(f"Far-side radiator frame leaks at {camera}")
                visibility_checks[f"{camera}"] = {
                    "front_cap": front_expected,
                    "near_side_frame_count": len(set(rim_visible) & near_faces),
                    "far_side_frame_count": 0,
                    "visible_rim_triangles": len(rim_visible),
                }

    face_eq = front_face_node.equation
    radiator_polygon_offsets = tuple([radiator_front_offset]+rim_faces)

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

    # Confirm actual compiled painter sequence from BOTH lateral cameras.
    # Shadow -> far wheel pair -> black chassis -> yellow body ->
    # near wheel pair. This prevents opposite-side tires painting across
    # chassis surfaces, which was visible in the user's in-game screenshot.
    bsp_tests = {}
    expected_frame_polygons = 114
    for side in (-1, 1):
        events = []
        model.switched_polygons(
            None, (0, side * 300000, 30000),
            bsp_mode="original", events=events,
        )
        dynamic_positions = [
            (i, model.dynamics[event[1]].xyz[1])
            for i, event in enumerate(events) if event[0] == "dynamic"
        ]
        polygons = [
            (i, model.polygons[event[1]])
            for i, event in enumerate(events) if event[0] == "polygon"
        ]
        if len(dynamic_positions) != 4 or len(polygons) < 300:
            raise ValueError("Compiled BSP omitted a wheel or main body surface")
        if [p.color for _i,p in polygons[:8]] != [STOCK_SHADOW_COLOR]*8:
            raise ValueError("Stock-style shadow must paint first")
        # The black chassis polygons immediately follow the 8 shadows
        # in POLYGON-only order; the far wheel DYNAMICs are interleaved
        # before the chassis polygons but produce external polygons.
        frame_polys = polygons[8:8+expected_frame_polygons]
        if len(frame_polys) != expected_frame_polygons or any(
                p.color != 0 for _i,p in frame_polys):
            raise ValueError("The entire 114-polygon chassis must paint as one black layer")
        frame_start = frame_polys[0][0]
        frame_end = frame_polys[-1][0]
        painted_polys = polygons[8+expected_frame_polygons:]
        if not painted_polys:
            raise ValueError("Painted yellow body absent")
        first_yellow = min(i for i,p in painted_polys if p.color in (158,159))
        last_yellow = max(i for i,p in painted_polys if p.color in (158,159))
        far_wheels = [i for i,y in dynamic_positions if y*side < 0]
        near_wheels = [i for i,y in dynamic_positions if y*side > 0]
        if (len(far_wheels) != 2 or len(near_wheels) != 2
                or max(far_wheels) >= frame_start
                or frame_end >= first_yellow
                or last_yellow >= min(near_wheels)):
            raise ValueError(
                f"Wrong camera-side painter order y={side}: "
                f"far={far_wheels}, frame={frame_start}-{frame_end}, "
                f"yellow={first_yellow}-{last_yellow}, near={near_wheels}"
            )

        # Verify source palette of the 2 mirrored windshield-mirror
        # struts (8 polygons each) was repainted to body yellow.
        mirrored_strut_polys = [
            p for _i,p in painted_polys if p.color == 158
        ]
        if len(mirrored_strut_polys) < 16:
            raise ValueError("Expected two yellow eight-polygon mirror struts")
        bsp_tests[str(side)] = {
            "stock_style_shadow_first": True,
            "shadow_polygon_count": 8,
            "shadow_palette_index": 27,
            "shadow_raw_z": STOCK_SHADOW_Z_RAW,
            "far_wheels_before_black_chassis": True,
            "black_chassis_before_yellow_body": True,
            "near_wheels_after_body": True,
            "far_wheel_events": far_wheels,
            "frame_event_range": [frame_start, frame_end],
            "near_wheel_events": near_wheels,
            "frame_polygon_count": expected_frame_polygons,
            "radiator_rear_cap_removed": True,
            "mirror_struts_palette": 158,
            "body_polygon_events": len(polygons),
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
        "Far wheels paint before black frame; frame before yellow; near wheels last.\n"
        "Both mirror supports are yellow palette index 158.\n"
        "Rear radiator cap omitted; black frame always draws before colored body.\n"
        "Grille is +X-only; six radiator rim FACE planes keep near side visible.\n",
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
        "radiator_front_culling": {
            "front_cap_plane_kind": "FACE",
            "front_plane_x_raw": RADIATOR_VIS_PLANE_X_RAW,
            "front_cap_x_raw": RADIATOR_FRONT_X_RAW,
            "front_cap_visible_only_from_positive_x": True,
            "rim_section_count": 6,
            "rim_surface_facing_planes": 6,
            "rim_triangle_count": 12,
            "radiator_polygon_count": len(radiator_polygon_offsets),
            "camera_visibility_tests": visibility_checks,
            "front_face_normal_signed_equation": list(face_eq),
        },
        "painter_layer_order": ["shadow", "far_side_wheels",
                                "black_chassis", "painted_body",
                                "near_side_wheels"],
        "mirror_strut_palette": 158,
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
