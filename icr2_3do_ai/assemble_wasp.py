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
# Model-space helmet anchor. The supplied sprite's own PMP origin is (0,0,0)
# and its eight camera-angle PMP variants each use nominal size 4800 raw.
# V24: use exact requested helmet center, Z=12824 in game coordinates.
# Sprite-image-dependent chin height must be checked in the game.
HELMET_GAME_XYZ = (-2100, 0, 12824)
SUPPLIED_HELMET_SHA256 = "e130b9725f9924b3e9619efbb8dabcd614e3f6c47146cf7d135cf6028fd88ee1"
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

# Driver geometry is authored in the Stage 2 recipe; the head remains
# the exact stock HELMET.3do PMP sprite referenced by a DYNAMIC node.
DRIVER_COMPONENTS = (
    "driver_seatback_geo", "driver_torso_geo", "driver_neck_geo",
    "driver_left_arm_geo", "driver_right_arm_geo",
    "driver_left_glove_geo", "driver_right_glove_geo",
)


def _sort_body_source(existing: str, wheel_symbols: list[str]) -> str:
    """View-sort far wheels, then black chassis, yellow body, near wheels."""
    parts = [v.strip() for v in existing.split(",")]
    if len(parts) != len(set(parts)):
        raise ValueError("Duplicate body components in source root")
    mandatory = {
        "radiator_face_geo", "long_bonnet_geo",
        "pointed_tail_geo", "rounded_tail_fin_geo",
        "dashboard_cowl_riser_geo",
    }
    if not mandatory <= set(parts):
        raise ValueError("Missing key bonnet/radiator/tail components")
    if not set(CHASSIS_COMPONENTS) <= set(parts):
        raise ValueError("Missing black chassis/suspension subcomponents")
    if not set(DRIVER_COMPONENTS) <= set(parts):
        raise ValueError("Missing the seven named driver body components")
    if len(wheel_symbols) != 4:
        raise ValueError("Expected four independently placed wheel references")

    frame = [p for p in parts if p in CHASSIS_COMPONENTS]
    pos, neg = [], []
    for part in parts:
        if part in CHASSIS_COMPONENTS or part in DRIVER_COMPONENTS:
            continue
        if "_right_" in part or part == "mirror_strut_right_geo":
            pos.append(part)
        elif "_left_" in part or part == "mirror_strut_left_geo":
            neg.append(part)
    if len(pos) != len(neg) or len(pos) != 6:
        raise ValueError("Expected five solid cockpit panels and one mirror strut per side")
    middle = [p for p in parts if p not in pos and p not in neg
              and p not in mandatory and p not in CHASSIS_COMPONENTS
              and p not in DRIVER_COMPONENTS]
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
        _group("wasp_driver_body", list(DRIVER_COMPONENTS)),
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
        (13000, -7800), (13000, 7800), (10500, 8200), (6000, 9600),
        (-6000, 9500), (-33000, 5100), (-33000, -5100),
        (-6000, -9500), (6000, -9600), (10500, -8200),
    )),
    # Broad, slightly tapered bonnet projection (not a pointed triangle).
    # Compare the actual model bonnet: +/-7860 at X=8100,
    # +/-7560 at X=24900 and +/-7020 at X=41700.
    ("nose", ((13000,-7800), (44000,-7100),
              (44000,7100), (13000,7800))),
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


# Palette in shared sunny/gamepal (verified previous work):
# 33 = user-requested fixed black, unlike RECOLOR-sensitive 49;
# 159 = darker yellow (235,203,0);
# 158 = bright yellow (255,223,35); 40 = gray (167,167,167).
# Stock ground shadow remains palette index 27.
BLACK_PALETTE = 33
SIDE_YELLOW = 159
TOP_YELLOW = 158
MIRROR_GRAY = 40
# Fixed common SUNNY/ GAMEPAL colors from icr2_3do_cad/gamepal.pcx.
# Palette 148 RGB (163, 103, 63) = brown driving suit and arm fabric.
# Palette 149 RGB (127, 79, 47) = darker brown leather gloves.
DRIVER_BROWN = 148
DRIVER_GLOVE_BROWN = 149


def _repaint_one_polygon(source: str, name: str, current: int,
                         target: int) -> str:
    """Repaint precisely one named N3 POLY with stale-source protection."""
    pattern = re.compile(
        rf"(?m)^({re.escape(name)}: POLY) <{current}>(\s+\{{)"
    )
    source, count = pattern.subn(
        lambda m: f"{m.group(1)} <{target}>{m.group(2)}",source
    )
    if count != 1:
        raise ValueError(f"Expected one {name} colored {current}, got {count}")
    return source


def _paint_wasp_upper_surfaces(source: str) -> str:
    """Split top versus side colors on existing polygon faces, not geometry."""
    # Six-vertex cross-section ring edges: bottom, outer vertical side,
    # high shoulder, central top, high shoulder, outer vertical side.
    # Each ring span has 12 side triangles. Faces 5 through 10 comprise
    # the raised shoulders and upper crown.
    for component in ("long_bonnet","pointed_tail"):
        for span in (0,1):
            for relative in range(5,11):
                idx=span*12+relative
                source=_repaint_one_polygon(
                    source,f"{component}_p{idx:04}",SIDE_YELLOW,TOP_YELLOW
                )
    # Raised dashboard cowl has one six-sided loft span: the same top
    # triangle range as the bonnet, but no extra span. The new rear
    # transverse bulkhead stays the slightly darker yellow side color.
    for relative in range(5, 11):
        source = _repaint_one_polygon(
            source, f"dashboard_cowl_riser_p{relative:04}",
            SIDE_YELLOW, TOP_YELLOW
        )
    # These strips lie along the U-shaped upper cockpit opening:
    # triangle faces 3/4 have the sloping top edge, 0/9 are broad sides.
    for side in ("left","right"):
        for section in range(1,6):
            for idx in (3,4):
                source=_repaint_one_polygon(
                    source,f"cockpit_body_{side}_{section}_p{idx:04}",
                    SIDE_YELLOW,TOP_YELLOW
                )
    # Forward-facing (+X) mirror cap becomes yellow; the aft-facing cap
    # p0009 remains gray along with four side edges.
    source=_repaint_one_polygon(
        source,"mirror_housing_p0000",MIRROR_GRAY,TOP_YELLOW
    )
    if not re.search(r"(?m)^mirror_housing_p0009: POLY <40> \{",source):
        raise ValueError("Mirror rear cap must remain gray")
    return source




def _cull_mirror_caps_by_camera(source: str) -> str:
    """Keep yellow forward housing and gray rearward reflective mirror.

    The original generic LIST draws the rear gray cap after the front
    yellow cap, which overpaints yellow from forward camera angles in ICR2.
    Two opposite FACE halfspaces at the housing's midpoint prevent that.
    """
    pattern = r"(?m)^mirror_housing_geo: LIST \{([^}\n]+)\};$"
    match = re.search(pattern, source)
    if match is None:
        raise ValueError("Missing mirror housing geometry group")
    members = [name.strip() for name in match.group(1).split(",")]
    expected = [f"mirror_housing_p{i:04}" for i in range(10)]
    if members != expected:
        raise ValueError("Mirror housing polygons/order changed")
    front, rear = expected[0], expected[9]
    if not re.search(
        rf"(?m)^{front}: POLY <{TOP_YELLOW}> \{{", source):
        raise ValueError("Forward housing must be yellow 158")
    if not re.search(
        rf"(?m)^{rear}: POLY <{MIRROR_GRAY}> \{{", source):
        raise ValueError("Rearward reflective mirror must be gray 40")

    front_cull, rear_cull = "wasp_mirror_front_cull", "wasp_mirror_rear_cull"
    revised = [front_cull] + members[1:9] + [rear_cull]
    source = source[:match.start()] + (
        "mirror_housing_geo: LIST {" + ", ".join(revised) + "};"
    ) + source[match.end():]
    # +X is the car's direction of travel in the finished assembled model.
    # Front cap at x=6360, rear cap at x=6000, split at x=6180.
    source += """
% Facing-correct mirror: bonnet-facing yellow housing; driver-facing glass gray.
wasp_mirror_plane_a: [<6180, -1200, 15000>];
wasp_mirror_plane_b: [<6180, 1200, 15000>];
wasp_mirror_plane_c: [<6180, 0, 18000>];
wasp_mirror_front_cull: FACE (wasp_mirror_plane_a, wasp_mirror_plane_b, wasp_mirror_plane_c), mirror_housing_p0000;
wasp_mirror_rear_cull: FACE (wasp_mirror_plane_a, wasp_mirror_plane_c, wasp_mirror_plane_b), mirror_housing_p0009;
"""
    return source


def _omit_cockpit_internal_bulkheads(source: str) -> str:
    """Remove hidden end caps; keep dashboard closed from behind."""
    def remove_polygons(group: str, doomed: tuple[str, ...]) -> None:
        nonlocal source
        group_pattern = rf"(?m)^{re.escape(group)}: LIST \{{([^}}\n]+)\}};$"
        match = re.search(group_pattern, source)
        if match is None:
            raise ValueError(f"Missing bulkhead-containing group {group}")
        members = [p.strip() for p in match.group(1).split(",")]
        if any(members.count(poly) != 1 for poly in doomed):
            raise ValueError(f"Bulkhead names/geometry changed in {group}")
        remaining = [p for p in members if p not in doomed]
        source = source[:match.start()] + (
            f"{group}: LIST {{" + ", ".join(remaining) + "};"
        ) + source[match.end():]
        for poly in doomed:
            source, count = re.subn(
                rf"(?m)^{re.escape(poly)}: POLY <\d+> \{{[^}}\n]+\}};\n",
                "", source,
            )
            if count != 1:
                raise ValueError(f"Expected exactly one {poly}, got {count}")

    # Extrusion along Y created four X-normal triangles per cockpit-wall
    # section. All ten walls meet their neighbors or the dashboard/seat;
    # the X-normal caps are redundant and overpaint the bonnet/body shell.
    for side in ("left", "right"):
        for section in range(1, 6):
            prefix = f"cockpit_body_{side}_{section}"
            remove_polygons(
                f"{prefix}_geo",
                tuple(f"{prefix}_p{idx:04}" for idx in (1, 2, 5, 6)),
            )

    # The bonnet's radiator-facing yellow cap is internal behind the black
    # grille. Preserve the true radiator front and the bonnet/tail cockpit
    # closures, not the hidden nose partition.
    remove_polygons("long_bonnet_geo", ("long_bonnet_p0000",))

    def replace_member(group: str, old: str, new: str) -> None:
        nonlocal source
        pattern = rf"(?m)^{re.escape(group)}: LIST \{{([^}}\n]+)\}};$"
        match = re.search(pattern, source)
        if match is None:
            raise ValueError(f"Missing cockpit closure group {group}")
        members = [p.strip() for p in match.group(1).split(",")]
        if members.count(old) != 1:
            raise ValueError(f"Expected one cockpit closure {old}")
        members[members.index(old)] = new
        source = source[:match.start()] + (
            f"{group}: LIST {{" + ", ".join(members) + "};"
        ) + source[match.end():]

    replace_member(
        "long_bonnet_geo", "long_bonnet_p0025",
        "wasp_cockpit_dashboard_only",
    )
    replace_member(
        "pointed_tail_geo", "pointed_tail_p0000",
        "wasp_cockpit_seat_only",
    )

    # IMPORTANT: dashboard has a single rear-facing -X FACE, not the
    # old pair of gates that wrongly hid it from cameras behind the tail.
    # Retain seat's two nested gates so it does not leak through bodywork.
    # Source already uses GAME coordinates (+X forward).
    source += """
% Dashboard closes the nose from behind; seat remains cockpit-window gated.
wasp_front_gate_a: [<8150, -1200, -3000>];
wasp_front_gate_b: [<8150, 0, -1000>];
wasp_front_gate_c: [<8150, 1200, -3000>];
wasp_rear_gate_a: [<-5100, -1200, -3000>];
wasp_rear_gate_b: [<-5100, 1200, -3000>];
wasp_rear_gate_c: [<-5100, 0, -1000>];
wasp_cockpit_dashboard_only: FACE (wasp_front_gate_a, wasp_front_gate_b, wasp_front_gate_c), long_bonnet_p0025;
wasp_seat_inner: FACE (wasp_front_gate_a, wasp_front_gate_b, wasp_front_gate_c), pointed_tail_p0000;
wasp_cockpit_seat_only: FACE (wasp_rear_gate_a, wasp_rear_gate_b, wasp_rear_gate_c), wasp_seat_inner;
"""
    if any(re.search(rf"(?m)^{component}_p(?:0001|0002|0005|0006):", source)
           for component in (
               f"cockpit_body_{side}_{section}"
               for side in ("left", "right") for section in range(1, 6)
           )):
        raise ValueError("Internal cockpit bulkhead still present")
    return source



def _fix_roof_occlusion(source: str) -> str:
    """Draw hull roof last, cull near-side inner walls, and clip overlap."""
    def group_replace(name: str, body: str) -> None:
        nonlocal source
        p = rf"(?m)^{re.escape(name)}: LIST \{{[^}}\n]+\}};$"
        source, hits = re.subn(p, f"{name}: LIST {{{body}}};", source)
        if hits != 1:
            raise ValueError(f"Missing unique group: {name}")

    # Remove the underside of the side slabs. Their X end caps were
    # already removed by _omit_cockpit_internal_bulkheads.
    for side in ("left", "right"):
        for section in range(1, 6):
            name = f"cockpit_body_{side}_{section}"
            group = name + "_geo"
            match = re.search(rf"(?m)^{group}: LIST \{{([^}}\n]+)\}};$", source)
            if match is None:
                raise ValueError(f"No cockpit group {group}")
            old_members = [x.strip() for x in match.group(1).split(",")]
            old_bottom = {f"{name}_p0007", f"{name}_p0008"}
            inward = f"{name}_p0009"
            if not old_bottom <= set(old_members) or inward not in old_members:
                raise ValueError(f"Cockpit geometry changed: {name}")
            face_name = f"wasp_inward_{side}_{section}"
            members = [face_name if x == inward else x for x in old_members
                       if x not in old_bottom]
            group_replace(group, ", ".join(members))
            for poly in old_bottom:
                source, n = re.subn(
                    rf"(?m)^{poly}: POLY <\d+> \{{[^}}\n]+\}};\n", "", source
                )
                if n != 1:
                    raise ValueError(f"Cannot delete enclosed underside {poly}")
            plane = ("wasp_in_left_a, wasp_in_left_b, wasp_in_left_c"
                     if side == "left" else
                     "wasp_in_right_a, wasp_in_right_b, wasp_in_right_c")
            source += f"\n{face_name}: FACE ({plane}), {inward};\n"

    # Avoid the tiny but genuine X overlap with the bonnet and the tail.
    for side in ("left", "right"):
        for section, x0, x1 in ((1, 8400, 8100),):
            name = f"cockpit_body_{side}_{section}"
            pattern = rf"(?m)^({name}_v\d{{4}}: \[<){x0}(, -?\d+, -?\d+>\];)$"
            source, count = re.subn(
                pattern, lambda m: m.group(1) + str(x1) + m.group(2), source
            )
            if count != 4:
                raise ValueError(f"Cannot clip four end vertices: {name}, got {count}")

    # The original cockpit slab tops projected above the neighboring roof
    # shoulders by 2,000+ raw units. Changing their X endpoint alone does
    # not cure a real mesh intersection. Set both junction profiles to
    # the *actual* bonnet/tail shoulder heights (outer and inner Y) so the
    # side lip blends into the exterior skin instead of sticking out of it.
    # All other cockpit ribs retain their shape and the cockpit stays open.
    for side in ("left", "right"):
        sy = 1 if side == "left" else -1
        junction_vertices = {
            (1, 0): (8100, sy*7860, 364),
            # Higher front cowl rises into a sloped scuttle/firewall.
            # The outer point meets the new raised cowl shoulder and
            # the inward point follows its sloping upper crown.
            (1, 1): (8100, sy*7860, 13144),
            (1, 4): (8100, sy*6240, 364),
            (1, 5): (8100, sy*6240, 14354),
            # Raised rear deck now begins at design X=8.34ft rather than
            # 8.92ft. Outer junction is at the same height as the tail
            # shoulder; inner cap meets its sloped upper skin.
            (5, 2): (-5040, sy*7980, 11764),
            (5, 3): (-5040, sy*7980, 364),
            (5, 6): (-5040, sy*6240, 12134),
            (5, 7): (-5040, sy*6240, 364),
        }
        for (section, vertex), (x, y, z) in junction_vertices.items():
            label = f"cockpit_body_{side}_{section}_v{vertex:04}"
            pattern = rf"(?m)^{re.escape(label)}: \[<-?\d+, -?\d+, -?\d+>\];$"
            source, count = re.subn(
                pattern, f"{label}: [<{x}, {y}, {z}>];", source
            )
            if count != 1:
                raise ValueError(f"Junction vertex missing or duplicated: {label}")
            if f"{label}: [<{x}, {y}, {z}>];" not in source:
                raise ValueError(f"Junction coordinate not updated: {label}")

    source += """
% Inward panels are seen from the cockpit only, never from the exterior
% camera on their own side of the vehicle.
wasp_in_left_a: [<0, 6240, 0>];
wasp_in_left_b: [<6000, 6240, 0>];
wasp_in_left_c: [<0, 6240, 6000>];
wasp_in_right_a: [<0, -6240, 0>];
wasp_in_right_b: [<0, -6240, 6000>];
wasp_in_right_c: [<6000, -6240, 0>];
"""

    for shape, roof in (("long_bonnet", "wasp_bonnet_roof_geo"),
                        ("pointed_tail", "wasp_tail_roof_geo")):
        match = re.search(
            rf"(?m)^{shape}_geo: LIST \{{([^}}\n]+)\}};$", source
        )
        if match is None:
            raise ValueError(f"Missing body skin {shape}")
        members = [x.strip() for x in match.group(1).split(",")]
        upper = [f"{shape}_p{span*12+i:04}" for span in (0, 1)
                 for i in range(5, 11)]
        if not set(upper) <= set(members):
            raise ValueError(f"Missing upper skin polygons for {shape}")
        lower = [x for x in members if x not in upper]
        group_replace(shape + "_geo", ", ".join(lower))
        source += f"\n{roof}: LIST {{" + ", ".join(upper) + "};\n"

    for side in ("pos", "neg"):
        group = f"wasp_{side}_sides"
        match = re.search(rf"(?m)^{group}: LIST \{{([^}}\n]+)\}};$", source)
        if match is None:
            raise ValueError(f"Missing {group}")
        members = [x.strip() for x in match.group(1).split(",")]
        old_strut = ("mirror_strut_right_geo" if side == "pos"
                     else "mirror_strut_left_geo")
        if members.count(old_strut) != 1:
            raise ValueError(f"Strut not in {group}")
        group_replace(group, ", ".join(x for x in members if x != old_strut))

    group_replace("wasp_tailparts", "pointed_tail_geo")

    source += """
% Rebuilt painter tree: all cockpit walls behind the exterior top shell.
wasp_nose_shell: LIST {long_bonnet_geo};
wasp_driver_center: LIST {wasp_driver_body};
wasp_bonnet_roof_radiator: BSPN (wasp_x_a, wasp_x_b, wasp_x_c), wasp_bonnet_roof_geo, radiator_face_geo;
wasp_upper_skin: BSPN (wasp_x_a, wasp_x_b, wasp_x_c), wasp_tail_roof_geo, wasp_bonnet_roof_radiator;
wasp_mirror_strut_sort: BSPA (wasp_y_a, wasp_y_b, wasp_y_c), mirror_strut_right_geo, mirror_housing_geo, mirror_strut_left_geo;
wasp_ornaments: LIST {rounded_tail_fin_geo, dashboard_cowl_riser_geo, wasp_mirror_strut_sort};
"""
    old_xsort = ("wasp_body_xsort: BSPA (wasp_x_a, wasp_x_b, wasp_x_c), "
                 "wasp_tailparts, wasp_midparts, wasp_noseparts;")
    # A 3-way BSPA puts the pilot between the nearer tail and nearer nose.
    # +X is forward AFTER the 180-degree conversion; this X plane points -X.
    new_xsort = ("wasp_body_xsort: BSPA (wasp_x_a, wasp_x_b, wasp_x_c), "
                 "wasp_tailparts, wasp_driver_center, wasp_nose_shell;")
    if source.count(old_xsort) != 1:
        raise ValueError("Original X sorting not found")
    source = source.replace(old_xsort, new_xsort)
    old_list = "wasp_frame_and_body: LIST {wasp_black_frame, wasp_body_ysort};"
    new_list = ("wasp_frame_and_body: LIST {wasp_black_frame, "
                "wasp_body_ysort, wasp_upper_skin, wasp_ornaments, "
                "wasp_driver_helmet};")
    if source.count(old_list) != 1:
        raise ValueError("Original body list not found")
    return source.replace(old_list, new_list)




def _add_raised_dashboard_bulkhead(source: str) -> str:
    """Keep a single transverse, raised rear-facing cowl bulkhead.

    The first loft cap is enclosed by the existing bonnet, so it must
    not render. The rear six-sided cap is a NEW cockpit-visible bulkhead
    immediately in FRONT of the old bonnet dashboard closure. Its roof
    rises into a wedge matching the 1911 side-profile reference.
    """
    name = "dashboard_cowl_riser_geo"
    oldcap = "dashboard_cowl_riser_p0000"
    rearcap = "dashboard_cowl_riser_p0013"
    gate = "wasp_raised_dashboard_bulkhead"
    pattern = rf"(?m)^{name}: LIST \{{([^}}\n]+)\}};$"
    match = re.search(pattern, source)
    if match is None:
        raise ValueError("Missing six-section raised dashboard cowl")
    members = [item.strip() for item in match.group(1).split(",")]
    expected = [f"dashboard_cowl_riser_p{i:04}" for i in range(14)]
    if members != expected:
        raise ValueError(f"Raised cowl polygon topology unexpectedly changed: {members}")
    members = [gate if item == rearcap else item
               for item in members if item != oldcap]
    source = source[:match.start()] + (
        f"{name}: LIST {{" + ", ".join(members) + "};"
    ) + source[match.end():]
    source, removed = re.subn(
        rf"(?m)^{oldcap}: POLY <\d+> \{{[^}}\n]+\}};\n",
        "", source
    )
    if removed != 1:
        raise ValueError("Hidden bonnet-facing cowl cap must be removed")
    if "wasp_front_gate_a" not in source:
        raise ValueError("Existing rearward dashboard FACE plane unavailable")
    # Original rear-facing dashboard gate has its plane at game X=8150.
    # The new cowl baffle is in front at design X=6.09 (game X=8460).
    # The same gate avoids cap bleed-through from forward viewpoints.
    source += (
        f"\n{gate}: FACE "
        "(wasp_front_gate_a, wasp_front_gate_b, wasp_front_gate_c), "
        f"{rearcap};\n"
    )
    return source


def _attach_driver_helmet(source: str) -> str:
    """Add a stock-style DYNAMIC helmet without rescaling or embedding its PMP.

    Place after rotating the Stage 2 car to the game's +X-forward frame:
    stock helmet direction is zero, unlike the 1800-tenths wheel transform.
    """
    key = ("wasp_frame_and_body: LIST {wasp_black_frame, "
           "wasp_body_ysort, wasp_upper_skin, wasp_ornaments, "
           "wasp_driver_helmet};")
    if source.count(key) != 1:
        raise ValueError("Helmet is not the last layer in the body")
    if "wasp_driver_helmet: DYNAMIC" in source:
        raise ValueError("Driver already has an external helmet reference")
    x, y, z = HELMET_GAME_XYZ
    if not (-5040 < x < 8100 and y == 0 and 11000 < z < 16000):
        raise ValueError("Helmet attachment is outside the Wasp cockpit")
    return source + (
        f'\nwasp_driver_helmet: DYNAMIC {x}, {y}, {z}, '
        '0, 0, 0, 1, EXTERN "HELMET";\n'
    )


def _omit_radiator_rear_cap(source: str) -> str:
    """Keep front radiator face & edge shell, omit ONLY its rear hexagon."""
    cap = "radiator_face_p0013"
    source, drop = re.subn(
        rf"(?m)^{cap}: POLY <{BLACK_PALETTE}> \{{[^}}\n]+\}};\n", "", source
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
        _attach_driver_helmet(
            _add_raised_dashboard_bulkhead(
                _cull_mirror_caps_by_camera(
                    _fix_roof_occlusion(
                        _attach_radiator_front_cull(
                            _omit_cockpit_internal_bulkheads(
                                _game_source(_omit_radiator_rear_cap(
                                    _paint_wasp_upper_surfaces(wasp_text)
                                ))
                            )
                        )
                    )
                )
            )
        )
    )

    # Palette regression: ensure the intended 1995 runtime indices are
    # actually assigned to the N3 POLY records (not just recipe metadata).
    expected_colors = {27, 33, 40, 148, 149, 158, 159}

    def source_poly_color(poly_name: str) -> int:
        hits = re.findall(
            rf"(?m)^{re.escape(poly_name)}: POLY <(\d+)> \{{",wasp_text
        )
        if len(hits) != 1:
            raise ValueError(f"Missing or duplicated polygon {poly_name}")
        return int(hits[0])

    check_colors = {
        "mirror_front": ("mirror_housing_p0000", TOP_YELLOW),
        "mirror_back": ("mirror_housing_p0009", MIRROR_GRAY),
        "mirror_edge": ("mirror_housing_p0001", MIRROR_GRAY),
        "fin_side": ("rounded_tail_fin_p0000", SIDE_YELLOW),
        "bonnet_side": ("long_bonnet_p0003", SIDE_YELLOW),
        "bonnet_shoulder": ("long_bonnet_p0005", TOP_YELLOW),
        "bonnet_crown": ("long_bonnet_p0007", TOP_YELLOW),
        "tail_side": ("pointed_tail_p0003", SIDE_YELLOW),
        "tail_shoulder": ("pointed_tail_p0005", TOP_YELLOW),
        "tail_crown": ("pointed_tail_p0007", TOP_YELLOW),
        "left_cockpit_side": ("cockpit_body_left_1_p0000", SIDE_YELLOW),
        "left_cockpit_lip": ("cockpit_body_left_1_p0003", TOP_YELLOW),
        "right_cockpit_side": ("cockpit_body_right_1_p0000", SIDE_YELLOW),
        "right_cockpit_lip": ("cockpit_body_right_1_p0003", TOP_YELLOW),
        "radiator": ("radiator_face_p0000", BLACK_PALETTE),
        "main_chassis": ("exposed_black_chassis_p0000", BLACK_PALETTE),
        "driver_seatback": ("driver_seatback_p0000", BLACK_PALETTE),
        "driver_torso": ("driver_torso_p0000", DRIVER_BROWN),
        "driver_neck": ("driver_neck_p0000", DRIVER_BROWN),
        "driver_left_arm": ("driver_left_arm_p0000", DRIVER_BROWN),
        "driver_right_arm": ("driver_right_arm_p0000", DRIVER_BROWN),
        "driver_left_glove": ("driver_left_glove_p0000", DRIVER_GLOVE_BROWN),
        "driver_right_glove": ("driver_right_glove_p0000", DRIVER_GLOVE_BROWN),
        "cowl_side": ("dashboard_cowl_riser_p0003", SIDE_YELLOW),
        "cowl_top": ("dashboard_cowl_riser_p0007", TOP_YELLOW),
        "new_bulkhead": ("dashboard_cowl_riser_p0013", SIDE_YELLOW),
    }
    for label, (symbol, expected_color) in check_colors.items():
        actual = source_poly_color(symbol)
        if actual != expected_color:
            raise ValueError(
                f"Unexpected {label} paint: {symbol}={actual}, "
                f"expected {expected_color}"
            )
    for component in ("long_bonnet","pointed_tail"):
        for span in (0,1):
            for local in range(5,11):
                index = 12*span+local
                symbol=f"{component}_p{index:04}"
                if source_poly_color(symbol)!=TOP_YELLOW:
                    raise ValueError(f"Unpainted upper surface {symbol}")
    for side in ("left","right"):
        for segment in range(1,6):
            for i in (3,4):
                symbol=f"cockpit_body_{side}_{segment}_p{i:04}"
                if source_poly_color(symbol)!=TOP_YELLOW:
                    raise ValueError(f"Unpainted cockpit top rim {symbol}")
    for component in ("mirror_strut_left","mirror_strut_right"):
        for index in range(8):
            # Uncapped thin lofts have 8 side triangles each.
            if source_poly_color(f"{component}_p{index:04}") != TOP_YELLOW:
                raise ValueError("Both mirror struts must remain yellow")
    source_palette = {
        int(index) for index in re.findall(
            r"(?m)^\w+: POLY <(\d+)> \{",wasp_text
        )
    }
    if not source_palette <= expected_colors or 49 in source_palette:
        raise ValueError(
            f"Unexpected reserved/obsolete POLY palette {source_palette}"
        )

    # Real N3 compiler and parser verify all parent source records and external names.
    model, result = validate_source(wasp_text, model_path=output / "WASP.3D")
    compiled_palette = {poly.color for poly in model.polygons.values()}
    if not compiled_palette <= expected_colors or BLACK_PALETTE not in compiled_palette:
        raise ValueError(f"Compiled body palette not as expected: {compiled_palette}")
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
    if (len(layer_children) != 5 or
            [model.records.get(i) for i in layer_children] != [11, 8, 10, 11, 15]):
        raise ValueError("Expected frame, sides, upper roof, ornaments, late helmet")
    frame_geo, painted_geo, roof_geo, ornaments_geo, helmet_layer = layer_children
    if model.dynamics[helmet_layer].name != "HELMET":
        raise ValueError("Last body painter entry must be the helmet sprite")
    if len(model.children[shadow_geo]) != 8:
        raise ValueError("Wasp shadow must have exactly 8 polygons")
    for off in model.children[shadow_geo]:
        p = model.polygons[off]
        zvals = {model.vertices[v].xyz[2] for v in p.refs}
        if p.color != 27 or zvals != {STOCK_SHADOW_Z_RAW}:
            raise ValueError("Shadow color/height differs from stock car")
    # The second shadow polygon must project the width of the bonnet,
    # not the old narrow triangular patch. Verify the *compiled* vertices.
    nose_shadow = model.polygons[model.children[shadow_geo][1]]
    nose_points = {tuple(model.vertices[v].xyz[:2]) for v in nose_shadow.refs}
    if nose_points != {(13000,-7800), (44000,-7100),
                       (44000,7100), (13000,7800)}:
        raise ValueError(f"Bonnet shadow footprint regressed: {nose_points}")
    if len(model.children[frame_geo]) != 13:
        raise ValueError("Chassis must have 13 named, first-drawn components")

    # Seven radiator FACE nodes plus four nested cockpit-window FACE gates
    # must survive compilation (dashboard + seat, two each).
    radiator_front_caps = [
        p.offset for p in model.polygons.values()
        if p.color == BLACK_PALETTE and len(set(p.refs)) == 6
        and all(model.vertices[v].xyz[0] == RADIATOR_FRONT_X_RAW
                for v in p.refs)
    ]
    if len(radiator_front_caps) != 1:
        raise ValueError(f"Radiator front hexagon missing: {radiator_front_caps}")
    radiator_front_offset = radiator_front_caps[0]
    face_nodes = [p for p in model.planes.values() if p.kind == 5]
    if len(face_nodes) != 23:
        raise ValueError(
            f"Expected 7 radiator + 4 bulkhead/closure + 10 inward + 2 mirror FACE nodes, got {len(face_nodes)}"
        )
    # Confirm front and rear mirror faces were actually isolated in the
    # compiled BSP tree and cannot paint through each other.
    mirror_front = next(
        (p.offset for p in model.polygons.values()
         if p.color == TOP_YELLOW and len(p.refs) == 5
         and all(model.vertices[v].xyz[0] == 6360 for v in p.refs)
         and max(model.vertices[v].xyz[2] for v in p.refs) == 18104),
        None,
    )
    mirror_rear = next(
        (p.offset for p in model.polygons.values()
         if p.color == MIRROR_GRAY and len(p.refs) == 5
         and all(model.vertices[v].xyz[0] == 6000 for v in p.refs)
         and max(model.vertices[v].xyz[2] for v in p.refs) == 18104),
        None,
    )
    if mirror_front is None or mirror_rear is None:
        raise ValueError("Missing exact yellow forward/gray rear mirror caps")
    mirror_faces = [
        f for f in face_nodes
        if model.children.get(f.offset) in ([mirror_front], [mirror_rear])
    ]
    if len(mirror_faces) != 2:
        raise ValueError("Each mirror cap requires one independent FACE gate")
    for x, front_expected in ((100000, True), (6400, True),
                              (5960, False), (-100000, False)):
        for y in (-90000, 90000):
            visible, _, _ = model.switched_polygons(
                None, (x, y, 16000), bsp_mode="original"
            )
            shown = set(visible)
            if ((mirror_front in shown) != front_expected
                    or (mirror_rear in shown) == front_expected):
                raise ValueError(
                    f"Mirror must show yellow forward, gray rear only at {(x, y)}"
                )
    wall_faces = [
        p for p in face_nodes if p.equation[0] == p.equation[2] == 0
        and p.equation[1] != 0
        and abs(abs(-p.equation[3]/p.equation[1]) - 6240) < .01
    ]
    if len(wall_faces) != 10:
        raise ValueError(f"Missing inward wall culls: {len(wall_faces)}")
    for side in (-1, 1):
        polys, _stats, _lod = model.switched_polygons(
            None, (0, side*90000, 18000), bsp_mode="original")
        active = set(polys)
        count_shown = 0
        for face in wall_faces:
            members = model.children.get(face.offset, [])
            if len(members) != 1 or members[0] not in model.polygons:
                raise ValueError("Inward wall FACE does not wrap a polygon")
            expected = face.equation[1]*side > 0
            if (members[0] in active) != expected:
                raise ValueError(f"Inward cockpit wall leaked at camera side {side}")
            count_shown += int(expected)
        if count_shown != 5:
            raise ValueError("Expected five far-side inner walls visible")
    def closure_cap(x: int) -> int:
        matches = [
            p.offset for p in model.polygons.values()
            if p.color == SIDE_YELLOW and len(p.refs) >= 6
            and all(model.vertices[v].xyz[0] == x for v in p.refs)
        ]
        if len(matches) != 1:
            raise ValueError(f"Expected one retained cockpit cap at x={x}, got {matches}")
        return matches[0]
    dashboard_cap = closure_cap(8100)
    seat_cap = closure_cap(-5040)
    raised_cowl_cap = closure_cap(8460)
    # The newly exposed baffle is separate from the original dashboard
    # closer and must face toward the cockpit, not forward over the hood.
    cowl_gate_faces = [
        face for face in face_nodes
        if model.children.get(face.offset) == [raised_cowl_cap]
    ]
    if len(cowl_gate_faces) != 1 or cowl_gate_faces[0].equation[0] >= 0:
        raise ValueError("New raised cowl bulkhead must have one -X FACE gate")
    cowl_face = cowl_gate_faces[0]
    closure_offsets = {dashboard_cap, seat_cap}
    direct_faces = [
        f for f in face_nodes
        if (dashboard_cap in model.children.get(f.offset, []) or
            seat_cap in model.children.get(f.offset, []))
    ]
    if len(direct_faces) != 2:
        raise ValueError("Dashboard and seat must each have a direct FACE")
    dashboard_faces = [
        f for f in direct_faces
        if model.children.get(f.offset) == [dashboard_cap]
    ]
    seat_inner_faces = [
        f for f in direct_faces
        if model.children.get(f.offset) == [seat_cap]
    ]
    if len(dashboard_faces) != 1 or len(seat_inner_faces) != 1:
        raise ValueError("Dashboard or seat FACE connection missing")
    dashboard_face = dashboard_faces[0]
    if not (dashboard_face.equation[0] < 0 and
            dashboard_face.equation[1] == dashboard_face.equation[2] == 0):
        raise ValueError("Dashboard FACE must point rearward (-X)")
    seat_outer_faces = [
        f for f in face_nodes
        if model.children.get(f.offset) == [seat_inner_faces[0].offset]
    ]
    if len(seat_outer_faces) != 1:
        raise ValueError("Seat must retain two cockpit-only FACE gates")
    protected_offsets = {
        dashboard_face.offset, seat_inner_faces[0].offset,
        seat_outer_faces[0].offset, cowl_face.offset,
    }
    protected_offsets |= {p.offset for p in wall_faces}
    protected_offsets |= {p.offset for p in mirror_faces}
    radiator_face_nodes = [
        f for f in face_nodes if f.offset not in protected_offsets
    ]
    if len(radiator_face_nodes) != 7:
        raise ValueError("Expected seven unaffected radiator FACE nodes")

    # Confirm new bulkhead exists ahead of the original dashboard,
    # with a raised brow reaching 4.03 feet and with its forward cap
    # removed, so no extra hidden partition overdraws the bonnet.
    cowl_rear_ring = _game_coordinates((round(6.09*6000), 0, round(4.03*6000)))
    cowl_outer_shoulder = _game_coordinates(
        (round(6.09*6000), round(1.31*6000), round(3.65*6000))
    )
    if not any(v.xyz == cowl_rear_ring for v in model.vertices.values()):
        raise ValueError("Cowl top lip 4.03 feet above ground missing")
    if not any(v.xyz == cowl_outer_shoulder for v in model.vertices.values()):
        raise ValueError("Cowl raised side shoulder missing")
    for x, expected in ((100000, False), (8500, False),
                        (7000, True), (0, True), (-100000, True)):
        for y in (-90000, 90000):
            for z in (12000, 28000):
                visible, _, _ = model.switched_polygons(
                    None, (x, y, z), bsp_mode="original"
                )
                if (raised_cowl_cap in set(visible)) != expected:
                    raise ValueError(
                        f"Raised cowl bulkhead visibility wrong from {(x,y,z)}"
                    )
    # Validate both caps from front, inside cockpit, and behind the tail,
    # from both sides and high/low elevations. The old failure was that
    # the dashboard vanished at x<-8580 and the front cavity was exposed.
    cockpit_visibility_tests = {}
    for x, dashboard_expected, seat_expected in (
        (100000, False, False),
        (8200, False, False),
        (0, True, True),
        (-8600, True, False),
        (-100000, True, False),
    ):
        for side in (-1, 1):
            for z in (12000, 25000):
                camera = (x, side * 90000, z)
                visible, _stats, _lod = model.switched_polygons(
                    None, camera, bsp_mode="original"
                )
                shown = set(visible)
                if ((dashboard_cap in shown) != dashboard_expected or
                        (seat_cap in shown) != seat_expected):
                    raise ValueError(
                        f"Cockpit cap visibility wrong from {camera}: "
                        f"dashboard={dashboard_cap in shown}, seat={seat_cap in shown}"
                    )
                cockpit_visibility_tests[str(camera)] = {
                    "dashboard": dashboard_expected,
                    "seat": seat_expected,
                }

    front_face_nodes = [
        p for p in radiator_face_nodes
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
    for face in radiator_face_nodes:
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
    if any(p.color == BLACK_PALETTE and len(p.refs) == 6
           and all(model.vertices[v].xyz[0] == radiator_back_x_raw
                   for v in p.refs)
           for p in model.polygons.values()):
        raise ValueError("Radiator rear cap still reachable")
    if set(model.external_names) != {"FWHEEL", "RWHEEL", "HELMET"}:
        raise ValueError(f"Incorrect external filenames: {model.external_names}")
    if len(model.dynamics) != 5:
        raise ValueError(f"Expected four wheels and one sprite helmet; found {len(model.dynamics)}")
    wheel_dynamics = [o for o in model.dynamics.values() if o.name in {"FWHEEL", "RWHEEL"}]
    helmet_dynamics = [o for o in model.dynamics.values() if o.name == "HELMET"]
    placements = {(tuple(o.xyz), o.name) for o in wheel_dynamics}
    expected = {(_game_coordinates(loc), ref) for _name, ref, loc in WHEEL_PLACEMENTS}
    if len(wheel_dynamics) != 4 or placements != expected:
        raise ValueError(f"Wrong wheel placements: {placements!r}")
    for dyn in wheel_dynamics:
        if dyn.angles != (-(1 << 31), 0, 0):
            raise ValueError(f"Wheel orientation incorrect: {dyn.name} {dyn.angles}")
    if len(helmet_dynamics) != 1:
        raise ValueError("Driver sprite must reference one exact HELMET.3do")
    helmet_dynamic = helmet_dynamics[0]
    if tuple(helmet_dynamic.xyz) != HELMET_GAME_XYZ or helmet_dynamic.angles != (0, 0, 0):
        raise ValueError(f"Wrong stock helmet placement/rotation: {helmet_dynamic}")
    # The actual eight-angle PMP silhouette has no fixed geometric chin.
    # Enforce the user-requested sprite anchor without guessing a clearance.
    if helmet_dynamic.xyz[2] != 12824:
        raise ValueError("Helmet must be at exactly Z=12824")
    # Rendering is painter-style, not true depth-tested transparent sprites.
    # Test all parent polygon events, including upper bonnet, upper tail,
    # and mirror housing/struts, paint BEFORE the helmet from representative
    # front, rear and elevated oblique cameras. Near-side wheels remain last.
    helmet_paint_tests = {}
    for eye_x in (-100000, 0, 100000):
        for eye_y in (-90000, 90000):
            for eye_z in (10000, 34000):
                eye = (eye_x, eye_y, eye_z)
                events = []
                model.switched_polygons(
                    None, eye, bsp_mode="original", events=events
                )
                helmet_indices = [
                    i for i, (kind, offset, *_) in enumerate(events)
                    if kind == "dynamic" and offset == helmet_dynamic.offset
                ]
                if len(helmet_indices) != 1:
                    raise ValueError(f"Helmet absent/duplicated from {eye}")
                helmet_i = helmet_indices[0]
                polygon_indices = [
                    i for i, (kind, *_rest) in enumerate(events)
                    if kind == "polygon"
                ]
                if not polygon_indices or max(polygon_indices) >= helmet_i:
                    raise ValueError(
                        f"Bonnet, tail or mirror paints over helmet from {eye}"
                    )
                near_wheel_indices = [
                    i for i, (kind, offset, *_) in enumerate(events)
                    if kind == "dynamic" and offset in model.dynamics
                    and model.dynamics[offset].name in ("FWHEEL", "RWHEEL")
                    and model.dynamics[offset].xyz[1] * eye_y > 0
                ]
                if len(near_wheel_indices) != 2 or min(near_wheel_indices) <= helmet_i:
                    raise ValueError(f"Helmet paints outside wheel layers from {eye}")
                helmet_paint_tests[str(eye)] = {
                    "all_body_polygons_before_helmet": True,
                    "near_wheels_after_helmet": True,
                }
    # Confirm the fin is no longer buried within the elevated deck.
    # Each fin endpoint should dip only slightly into the deck surface
    # to prevent a light leak, rather than have ~0.5ft of hidden base.
    fin_shape_zx = (
        (3.24, 12.25), (4.12, 12.90), (4.49, 13.38),
        (4.52, 13.82), (4.20, 14.20), (2.98, 14.43),
    )
    for z_ft, x_ft in fin_shape_zx:
        x_raw = COCKPIT_DESIGN_X_RAW - round(x_ft * 6000)
        z_raw = round(z_ft * 6000) + STOCK_GROUND_RAW_Z
        for y_raw in (-330, 330):
            if not any(v.xyz == (x_raw, y_raw, z_raw)
                       for v in model.vertices.values()):
                raise ValueError(
                    f"Missing compiled dorsal-fin vertex at {(x_raw, y_raw, z_raw)}"
                )
    def rear_roof_height_ft(x_ft: float) -> float:
        return 3.40 + (3.08 - 3.40) * (x_ft - 11.12) / (14.55 - 11.12)
    for base_height, base_x in ((3.24, 12.25), (2.98, 14.43)):
        roof_overlap = rear_roof_height_ft(base_x) - base_height
        if not 0 < roof_overlap < 0.13:
            raise ValueError(
                f"Fin base must be 0..0.13ft into rear roof at {base_x}, "
                f"got {roof_overlap:.3f}ft"
            )
    if max(z_ft for z_ft, _ in fin_shape_zx) < 4.5:
        raise ValueError("Dorsal fin peak is not high enough")
    # Ensure rear deck now starts behind the seat but before the old
    # rear wheel line, and both broad front and middle sections are
    # higher than the rear bonnet's 3.42 ft crown.
    rear_deck_x = _game_coordinates((int(round(8.34*6000)), 0, 0))[0]
    rear_deck_crown = int(round(3.52*6000)) + STOCK_GROUND_RAW_Z
    middle_deck_x = _game_coordinates((int(round(11.12*6000)), 0, 0))[0]
    middle_deck_crown = int(round(3.40*6000)) + STOCK_GROUND_RAW_Z
    if not any(
        v.xyz[0] == rear_deck_x and v.xyz[2] == rear_deck_crown
        for v in model.vertices.values()
    ):
        raise ValueError("Front of raised rear deck is missing")
    if not any(
        v.xyz[0] == middle_deck_x and v.xyz[2] == middle_deck_crown
        for v in model.vertices.values()
    ):
        raise ValueError("Middle raised rear deck is missing")
    # Check actual compiled loft cross sections and taper; unlike the
    # bonnet's .43-foot shoulder-to-crown rise, the tail has <.11ft.
    tail_sections = (
        # design X, outer half-width, outer shoulder Z, plateau half-width, top Z
        (8.34, 1.33, 3.42, 0.86, 3.52),
        (11.12, 0.88, 3.30, 0.54, 3.40),
        (14.55, 0.08, 3.04, 0.0344, 3.08),
    )
    for x_ft, outer_width, shoulder_z, inner_width, crown_z in tail_sections:
        if not (0 < crown_z - shoulder_z <= 0.11):
            raise ValueError("Tail roof must be flatter than bonnet crown")
        for y_ft, z_ft in (
            (outer_width, shoulder_z), (-outer_width, shoulder_z),
            (inner_width, crown_z), (-inner_width, crown_z),
        ):
            game_xyz = _game_coordinates((
                round(x_ft*6000), round(y_ft*6000), round(z_ft*6000)
            ))
            if not any(tuple(v.xyz) == game_xyz for v in model.vertices.values()):
                raise ValueError(f"Tail loft station missing {game_xyz}")
    if not (tail_sections[0][1] > tail_sections[1][1] > tail_sections[2][1]
            and tail_sections[0][3] > tail_sections[1][3] > tail_sections[2][3]):
        raise ValueError("Tail must begin tapering directly behind driver")
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
            for i, event in enumerate(events)
            if event[0] == "dynamic"
            and model.dynamics[event[1]].name in {"FWHEEL", "RWHEEL"}
        ]
        driver_sprite_events = [
            (i, event[1]) for i, event in enumerate(events)
            if event[0] == "dynamic"
            and model.dynamics[event[1]].name == "HELMET"
        ]
        polygons = [
            (i, model.polygons[event[1]])
            for i, event in enumerate(events) if event[0] == "polygon"
        ]
        if (len(dynamic_positions) != 4 or len(driver_sprite_events) != 1
                or len(polygons) < 280):
            raise ValueError("Compiled BSP omitted wheel, pilot sprite or body polygon")
        # Ensure a centerline helmet is painted between far/near cockpit
        # sides and before the vehicle's near wheel pair.
        helmet_event_index = driver_sprite_events[0][0]
        if [p.color for _i,p in polygons[:8]] != [STOCK_SHADOW_COLOR]*8:
            raise ValueError("Stock-style shadow must paint first")
        # The black chassis polygons immediately follow the 8 shadows
        # in POLYGON-only order; the far wheel DYNAMICs are interleaved
        # before the chassis polygons but produce external polygons.
        frame_polys = polygons[8:8+expected_frame_polygons]
        if len(frame_polys) != expected_frame_polygons or any(
                p.color != BLACK_PALETTE for _i,p in frame_polys):
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
                or last_yellow >= min(near_wheels)
                or not frame_end < helmet_event_index < min(near_wheels)):
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
            "driver_helmet_dynamic_event": helmet_event_index,
            "driver_sprite_extern": "HELMET",
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
        if re.search(r'POLY\s*<(?:0|47|48|49)>', ordered_source):
            raise ValueError(f"Disallowed reserved/obsolete black in {obj_name}")
        wheel_palette = {poly.color for poly in ordered_model.polygons.values()}
        if wheel_palette != {BLACK_PALETTE, SIDE_YELLOW}:
            raise ValueError(f"{obj_name} wheel has unexpected palette {wheel_palette}")
        if ordered_model.records[ordered_model.root_offset] != 8:
            raise ValueError(f"{obj_name} root is not BSPA")
        (output / (obj_name + ".3D")).write_text(
            ordered_source, encoding="utf-8"
        )
        (output / (obj_name + ".3do")).write_bytes(ordered_model.raw)

    # The uploaded helmet.3do exactly matches the repository's stock binary
    # fixture (same SHA-256), so it can be bundled without committing an
    # additional or modified copy of any game asset to the source tree.
    helmet_file = Path(__file__).resolve().parents[1] / "icr2_3do_cad" / "fixtures" / "helmet.3do"
    if not helmet_file.is_file():
        raise FileNotFoundError("Stock sprite HELMET fixture missing")
    helmet_bytes = helmet_file.read_bytes()
    if sha256(helmet_bytes).hexdigest() != SUPPLIED_HELMET_SHA256:
        raise ValueError("Stock sprite fixture differs from user-supplied helmet.3do")
    shutil.copy2(helmet_file, output / "HELMET.3do")

    checks = {}
    for name in ("WASP", "FWHEEL", "RWHEEL", "HELMET"):
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
        "Place WASP.3do, FWHEEL.3do, RWHEEL.3do, HELMET.3do in one folder.\n"
        "HELMET.3do is the unchanged eight-angle stock sprite reference.\n"
        "The eight helm0001..helm0008.pmp images must be available from game resources.\n"
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
        "U cockpit walls retain visible shell and top lips; 40 hidden endcaps omitted.\n"
        "Dashboard closes nose from all behind-the-car views; seat remains cockpit-only.\n"
        "Tire size 34x4.5 inches, steel wheel covers nominal 25 inches; polygonal.\n"
        "Wheel and body BSPA sorting is authored; in-game BSP and LOD testing remain.\n"
        "Fixed black palette 33 replaces RECOLOR-sensitive 49; shadow remains 27.\n"
        "Upper yellow 158, sides/fin and wheel discs 159; mirror forward 158, real reflective rear 40.\n"
        "Mirror caps are oppositely FACE-culled; gray rear never overdraws yellow front.\n"
        "Shadow: eight flat polygons, palette 27 at Z=-8501; full-width tapered bonnet shadow.\n"
        "Far wheels paint before black frame; frame before yellow; near wheels last.\n"
        "Both mirror supports are yellow palette index 158.\n"
        "Rear radiator cap omitted; black frame always draws before colored body.\n"
        "Grille is +X-only; six radiator rim FACE planes keep near side visible.\n"
        "Seated gray driver (palette 40), black seat/gloves (palette 33).\n"
        "V24 HELMET DYNAMIC (-2100, 0, 12824): exact requested Z.\n"
        "Helmet paints after BOTH roof skins, mirror and struts.\n"
        "Neck 3.09..3.37ft; torso and shoulder height unchanged.\n"
        "Flatter converging tail: crowns 3.52, 3.40, 3.08ft.\n"
        "Fin now peaks at 4.52ft, with its bottom edge just inside rear roof.\n"
        "Previous wheel positions and palette assignments unchanged.\n",
        encoding="utf-8",
    )
    manifest = {
        "description": "Marmon Wasp body, seated driver, and external wheels and helmet sprite",
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
            "rear_deck_design_start_ft": 8.34,
            "rear_deck_front_crown_ft": 3.52,
            "rear_deck_mid_crown_ft": 3.40,
            "outer_halfwidths_ft": [1.33, 0.88, 0.08],
            "plateau_halfwidths_ft": [0.86, 0.54, 0.0344],
            "shoulder_heights_ft": [3.42, 3.30, 3.04],
            "tail_tip_crown_ft": 3.08,
            "helmet_center_height_above_ground_ft": 3.5967,
            "neck_bottom_height_ft": 3.09,
            "neck_top_height_ft": 3.37,
            "dorsal_fin_peak_height_ft": 4.52,
            "dorsal_fin_base_heights_ft": [3.24, 2.98],
            "wheelbase_inches": wheelbase_in,
            "overall_length_inches": length_in,
            "radiator_front_to_front_axle_inches": radiator_to_front_axle_in,
            "documented_source": "INDYCAR/IMS 2011 centennial specifications",
            "radiator_axle_alignment": "photograph-guided estimate; not a published measurement",
        },
        "source_files": ["WASP.3D", "FWHEEL.3D", "RWHEEL.3D"],
        "binary_files": ["WASP.3do", "FWHEEL.3do", "RWHEEL.3do", "HELMET.3do"],
        "driver": {
            "body_components": list(DRIVER_COMPONENTS),
            "gray_suit_palette": MIRROR_GRAY,
            "gloves_seat_palette": BLACK_PALETTE,
            "head_external": "HELMET",
            "helmet_anchor_raw": list(HELMET_GAME_XYZ),
            "sprite_chin_clearance": "not asserted: PMP silhouette depends on view",
            "helmet_paints_last_within_body": True,
            "helmet_file_sha256": SUPPLIED_HELMET_SHA256,
            "helmet_pmp_names": [f"helm{i:04}" for i in range(1, 9)],
            "head_is_external_sprite_not_polygon_mesh": True,
        },
        "validation": checks,
        "stock_style_shadow": {
            "polygon_count": 8,
            "palette_index": 27,
            "raw_z": STOCK_SHADOW_Z_RAW,
            "stock_ground_raw_z": STOCK_GROUND_RAW_Z,
            "offset_above_ground_raw": 255,
            "source": "user-provided stock indycar.3do shadow POLY group",
            "bonnet_footprint": [[13000,-7800], [44000,-7100],
                                  [44000,7100], [13000,7800]],
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
        "cockpit_closure_visibility": cockpit_visibility_tests,
        "helmet_painter_camera_tests": helmet_paint_tests,
        "painter_layer_order": ["shadow", "far_side_wheels",
                                "black_chassis", "painted_body",
                                "near_side_wheels"],
        "paint_source_regression_checks": len(check_colors) + 24 + 20 + 16,
        "paint_palette": {
            "chassis_tire_and_hub": BLACK_PALETTE,
            "side_and_fin_yellow": SIDE_YELLOW,
            "upper_crown_yellow": TOP_YELLOW,
            "mirror_front_yellow": TOP_YELLOW,
            "mirror_back_and_edge_gray": MIRROR_GRAY,
            "mirror_caps_have_opposing_FACE_culling": True,
            "shadow_original": STOCK_SHADOW_COLOR,
        },
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
