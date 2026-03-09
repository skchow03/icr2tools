#!/usr/bin/env python3
"""
ICR2 Building Generator (UI + .3D writer)

PyQt5 application that generates Papyrus/ICR2 .3D building objects.

Supported roof types
- none (no roof)
- flat
- parapet (inset roof cap)
- gable (simple pitched roof)
- pyramid (4-sided pitched roof)
- dome (for circular buildings)
"""

from __future__ import annotations

import configparser
import math
import sys
from pathlib import Path


INI_PATH = Path(__file__).with_suffix(".ini")
TEMPLATE_SECTION_PREFIX = "template:"

TEMPLATE_FIELDS = (
    "building_shape",
    "rect_center_origin",
    "width",
    "depth",
    "height",
    "diameter",
    "num_sides",
    "roof_type",
    "parapet_inset",
    "parapet_height",
    "gable_rise",
    "pyramid_rise",
    "dome_layers",
    "dome_roundness",
    "sunny_pcx",
    "roof_color_bright",
    "roof_color_dark",
    "side_color_bright",
    "side_color_dark",
    "tree_trunk_width",
    "tree_leaf_base_height",
    "tree_num_sides",
    "tree_profile",
    "tree_trunk_color",
    "tree_leaves_color",
    "tree_trunk_color_bright",
    "tree_trunk_color_dark",
    "tree_leaves_color_bright",
    "tree_leaves_color_dark",
    "bridge_length",
    "bridge_width",
    "bridge_clearance",
    "bridge_height",
    "bridge_half",
    "grandstand_length",
    "grandstand_width",
    "grandstand_height",
    "grandstand_angle",
    "grandstand_front_height",
)


# ------------------------------------------------------------
# Geometry generation
# ------------------------------------------------------------

def generate_base(width, depth, height):
    verts = {}

    verts["a0"] = (0, depth, 0)
    verts["b0"] = (0, 0, 0)
    verts["c0"] = (width, 0, 0)
    verts["d0"] = (width, depth, 0)

    verts["a1"] = (0, depth, height)
    verts["b1"] = (0, 0, height)
    verts["c1"] = (width, 0, height)
    verts["d1"] = (width, depth, height)

    faces = [
        ("ls1", ["a1", "a0", "b0", "b1"]),
        ("fr1", ["b1", "b0", "c0", "c1"]),
        ("rs1", ["c1", "c0", "d0", "d1"]),
        ("bk1", ["d1", "d0", "a0", "a1"]),
    ]

    return verts, faces


def add_flat_roof(faces):
    faces += [
        ("topB", ["a1", "b1", "c1"]),
        ("topD", ["a1", "c1", "d1"]),
    ]


def add_parapet_roof(verts, faces, width, depth, height, inset, roof_height):
    verts["a2"] = (inset, depth - inset, height + roof_height)
    verts["b2"] = (inset, inset, height + roof_height)
    verts["c2"] = (width - inset, inset, height + roof_height)
    verts["d2"] = (width - inset, depth - inset, height + roof_height)

    faces += [
        ("ls2", ["a2", "a1", "b1", "b2"]),
        ("fr2", ["b2", "b1", "c1", "c2"]),
        ("rs2", ["c2", "c1", "d1", "d2"]),
        ("bk2", ["d2", "d1", "a1", "a2"]),
        ("roofB", ["a2", "b2", "c2"]),
        ("roofD", ["a2", "c2", "d2"]),
    ]


def add_gable_roof(verts, faces, width, depth, height, rise):
    verts["r0"] = (width // 2, 0, height + rise)
    verts["r1"] = (width // 2, depth, height + rise)

    faces += [
        ("roofL", ["a1", "b1", "r0", "r1"]),
        ("roofR", ["c1", "d1", "r1", "r0"]),
        ("gableF", ["b1", "c1", "r0"]),
        ("gableB", ["d1", "a1", "r1"]),
    ]


def add_pyramid_roof(verts, faces, width, depth, height, rise):
    verts["p0"] = (width // 2, depth // 2, height + rise)

    faces += [
        ("pyrF", ["b1", "c1", "p0"]),
        ("pyrR", ["c1", "d1", "p0"]),
        ("pyrB", ["d1", "a1", "p0"]),
        ("pyrL", ["a1", "b1", "p0"]),
    ]


def generate_circular_base(diameter, sides, height):
    verts = {}
    faces = []
    radius = diameter / 2.0

    def _round_point(value):
        return round(value, 2)

    for i in range(sides):
        angle = (2.0 * math.pi * i) / sides
        x = radius * math.cos(angle)
        y = radius * math.sin(angle)
        verts[f"cb{i}"] = (_round_point(x), _round_point(y), 0)
        verts[f"ct{i}"] = (_round_point(x), _round_point(y), height)

    for i in range(sides):
        nxt = (i + 1) % sides
        theta = (2.0 * math.pi * (i + 0.5)) / sides
        side_prefix = "sideB" if (math.cos(theta) - math.sin(theta)) >= 0 else "sideD"
        faces.append((f"{side_prefix}{i}", [f"ct{i}", f"cb{i}", f"cb{nxt}", f"ct{nxt}"]))

    return verts, faces


def add_circular_flat_roof(verts, faces, sides, diameter, height):
    verts["ctp"] = (0, 0, height)
    for i in range(sides):
        nxt = (i + 1) % sides
        theta = (2.0 * math.pi * (i + 0.5)) / sides
        roof_prefix = "roofB" if (math.cos(theta) - math.sin(theta)) >= 0 else "roofD"
        faces.append((f"{roof_prefix}{i}", [f"ct{i}", f"ct{nxt}", "ctp"]))


def add_circular_dome_roof(verts, faces, diameter, sides, height, dome_layers, dome_roundness):
    radius = diameter / 2.0

    def _round_point(value):
        return round(value, 2)

    roundness = max(0.0, min(100.0, float(dome_roundness))) / 100.0
    dome_height = radius * roundness
    prev_ring = [f"ct{i}" for i in range(sides)]

    for layer in range(1, dome_layers + 1):
        t = layer / (dome_layers + 1)
        # Use a quarter-circle profile so dome sides curve upward like a capitol dome,
        # instead of tapering linearly into a cone.
        profile_angle = (math.pi / 2.0) * t
        # Keep the profile curved all the way to the top, while lowering total
        # dome height for flatter stadium-like roofs.
        ring_radius = radius * math.cos(profile_angle)
        ring_z = height + (dome_height * math.sin(profile_angle))
        ring_names = []
        for i in range(sides):
            angle = (2.0 * math.pi * i) / sides
            x = ring_radius * math.cos(angle)
            y = ring_radius * math.sin(angle)
            name = f"dr{layer}_{i}"
            verts[name] = (_round_point(x), _round_point(y), _round_point(ring_z))
            ring_names.append(name)

        for i in range(sides):
            nxt = (i + 1) % sides
            theta = (2.0 * math.pi * (i + 0.5)) / sides
            roof_prefix = "roofB" if (math.cos(theta) - math.sin(theta)) >= 0 else "roofD"
            faces.append((f"{roof_prefix}L{layer}_{i}", [prev_ring[i], prev_ring[nxt], ring_names[nxt], ring_names[i]]))

        prev_ring = ring_names

    top_z = _round_point(height + dome_height)
    verts["dome_top"] = (0, 0, top_z)
    for i in range(sides):
        nxt = (i + 1) % sides
        theta = (2.0 * math.pi * (i + 0.5)) / sides
        roof_prefix = "roofB" if (math.cos(theta) - math.sin(theta)) >= 0 else "roofD"
        faces.append((f"{roof_prefix}Top{i}", [prev_ring[i], prev_ring[nxt], "dome_top"]))


def generate_tree(width, height, trunk_width, leaf_base_height, tree_num_sides=10, tree_profile="pointy"):
    width = max(1, int(width))
    height = max(1, int(height))
    trunk_width = max(1, min(int(trunk_width), width))
    leaf_base_height = max(1, min(int(leaf_base_height), height - 1))

    sides = max(3, int(tree_num_sides))
    trunk_radius = trunk_width / 2.0
    leaf_radius = width / 2.0

    verts = {}
    faces = []

    def _rounded(value, decimals):
        if decimals <= 0:
            return int(round(value))
        return round(value, decimals)

    def _build_ring(radius, sides, z, name_prefix):
        best_names = []
        # Try coarse integer coordinates first (for compact output), then add
        # decimal precision when needed so tiny trunks don't collapse into
        # degenerate faces with fewer than 3 unique points.
        for decimals in (0, 1, 2, 3):
            trial_names = []
            trial_coords = []
            for i in range(sides):
                angle = (2.0 * math.pi * i) / sides
                x = _rounded(radius * math.cos(angle), decimals)
                y = _rounded(radius * math.sin(angle), decimals)
                name = f"{name_prefix}{i}"
                trial_names.append(name)
                trial_coords.append((x, y, z))

            has_adjacent_duplicates = any(
                trial_coords[i][:2] == trial_coords[(i + 1) % sides][:2]
                for i in range(sides)
            )
            if not has_adjacent_duplicates and len(set(trial_coords)) >= 3:
                best_names = trial_names
                for name, coord in zip(trial_names, trial_coords):
                    verts[name] = coord
                return best_names

            best_names = trial_names
            for name, coord in zip(trial_names, trial_coords):
                verts[name] = coord

        return best_names

    trunk_bottom_ring = _build_ring(trunk_radius, sides, 0, "tb")
    trunk_top_ring = _build_ring(trunk_radius, sides, leaf_base_height, "tt")

    for i in range(sides):
        nxt = (i + 1) % sides
        theta = (2.0 * math.pi * (i + 0.5)) / sides
        trunk_prefix = "trunkB" if (math.cos(theta) - math.sin(theta)) >= 0 else "trunkD"
        faces.append((f"{trunk_prefix}{i}", [trunk_top_ring[i], trunk_bottom_ring[i], trunk_bottom_ring[nxt], trunk_top_ring[nxt]]))

    leaf_bottom_z = leaf_base_height
    leaf_top_z = height
    profile = str(tree_profile or "pointy").strip().lower()

    if profile == "round":
        verts["leaf_bottom_center"] = (0, 0, leaf_bottom_z)
        verts["leaf_top_center"] = (0, 0, leaf_top_z)
        canopy_rings = []
        ring_count = 4
        for ring_index in range(1, ring_count + 1):
            t = ring_index / (ring_count + 1)
            ring_radius = leaf_radius * math.sin(math.pi * t)
            ring_z = int(round(leaf_bottom_z + ((leaf_top_z - leaf_bottom_z) * t)))
            ring_names = []
            for i in range(sides):
                angle = (2.0 * math.pi * i) / sides
                x = int(round(ring_radius * math.cos(angle)))
                y = int(round(ring_radius * math.sin(angle)))
                name = f"lr{ring_index}_{i}"
                verts[name] = (x, y, ring_z)
                ring_names.append(name)
            canopy_rings.append(ring_names)

        for i in range(sides):
            nxt = (i + 1) % sides
            theta = (2.0 * math.pi * (i + 0.5)) / sides
            leaf_prefix = "leafB" if (math.cos(theta) - math.sin(theta)) >= 0 else "leafD"
            # Keep the underside winding oriented outward (downward normal)
            # so these faces remain visible from outside the tree canopy.
            faces.append((f"{leaf_prefix}B{i}", ["leaf_bottom_center", canopy_rings[0][nxt], canopy_rings[0][i]]))
            for ring_index in range(len(canopy_rings) - 1):
                lower = canopy_rings[ring_index]
                upper = canopy_rings[ring_index + 1]
                faces.append((f"{leaf_prefix}S{ring_index}_{i}", [lower[i], lower[nxt], upper[nxt], upper[i]]))
            top_ring = canopy_rings[-1]
            faces.append((f"{leaf_prefix}T{i}", [top_ring[i], top_ring[nxt], "leaf_top_center"]))
    elif profile == "palm":
        crown_z = leaf_base_height
        crown_radius = trunk_radius * 0.75
        frond_count = max(5, min(10, sides))
        inner_leaf_faces = []
        outer_leaf_faces = []

        verts["leaf_crown_center"] = (0, 0, crown_z)

        for i in range(frond_count):
            angle = (2.0 * math.pi * i) / frond_count
            radial_x = math.cos(angle)
            radial_y = math.sin(angle)
            tangent_x = -radial_y
            tangent_y = radial_x

            base_x = crown_radius * radial_x
            base_y = crown_radius * radial_y

            mid_radius = leaf_radius * 0.62
            tip_radius = leaf_radius * 0.96
            blade_half_width = leaf_radius * 0.16
            canopy_height = height - leaf_base_height

            if i % 2 == 0:
                # Arching fronds first rise above the trunk top and then dip.
                mid_z = int(round(crown_z + (canopy_height * 0.22)))
                tip_z = int(round(crown_z - (canopy_height * 0.14)))
            else:
                # Drooping fronds hang downward from the crown.
                mid_z = int(round(crown_z - (canopy_height * 0.12)))
                tip_z = int(round(crown_z - (canopy_height * 0.34)))

            base_name = f"pfb{i}"
            left_name = f"pfl{i}"
            right_name = f"pfr{i}"
            tip_name = f"pft{i}"
            verts[base_name] = (int(round(base_x)), int(round(base_y)), crown_z)
            verts[left_name] = (
                int(round((mid_radius * radial_x) + (blade_half_width * tangent_x))),
                int(round((mid_radius * radial_y) + (blade_half_width * tangent_y))),
                mid_z,
            )
            verts[right_name] = (
                int(round((mid_radius * radial_x) - (blade_half_width * tangent_x))),
                int(round((mid_radius * radial_y) - (blade_half_width * tangent_y))),
                mid_z,
            )
            verts[tip_name] = (int(round(tip_radius * radial_x)), int(round(tip_radius * radial_y)), tip_z)

            theta = (2.0 * math.pi * (i + 0.5)) / frond_count
            leaf_prefix = "leafB" if (math.cos(theta) - math.sin(theta)) >= 0 else "leafD"
            stem_outer = ["leaf_crown_center", right_name, base_name, left_name]
            blade_outer = [left_name, right_name, tip_name]
            inner_leaf_faces.append((f"{leaf_prefix}PalmStemInner{i}", list(reversed(stem_outer))))
            inner_leaf_faces.append((f"{leaf_prefix}PalmBladeInner{i}", list(reversed(blade_outer))))
            outer_leaf_faces.append((f"{leaf_prefix}PalmStemOuter{i}", stem_outer))
            outer_leaf_faces.append((f"{leaf_prefix}PalmBladeOuter{i}", blade_outer))

        faces.extend(inner_leaf_faces)
        faces.extend(outer_leaf_faces)
    else:
        leaf_mid_z = int(round(leaf_base_height + ((height - leaf_base_height) * 0.72)))
        leaf_mid_radius = leaf_radius * 0.58
        leaf_bottom_center_z = int(round(leaf_base_height + ((height - leaf_base_height) * 0.12)))
        verts["leaf_bottom_center"] = (0, 0, leaf_bottom_center_z)
        verts["leaf_top_center"] = (0, 0, leaf_top_z)

        leaf_bottom_ring = []
        leaf_mid_ring = []
        for i in range(sides):
            angle = (2.0 * math.pi * i) / sides
            x0 = leaf_radius * math.cos(angle)
            y0 = leaf_radius * math.sin(angle)
            x1 = leaf_mid_radius * math.cos(angle)
            y1 = leaf_mid_radius * math.sin(angle)
            b_name = f"lb{i}"
            m_name = f"lm{i}"
            verts[b_name] = (int(round(x0)), int(round(y0)), leaf_bottom_z)
            verts[m_name] = (int(round(x1)), int(round(y1)), leaf_mid_z)
            leaf_bottom_ring.append(b_name)
            leaf_mid_ring.append(m_name)

        for i in range(sides):
            nxt = (i + 1) % sides
            theta = (2.0 * math.pi * (i + 0.5)) / sides
            leaf_prefix = "leafB" if (math.cos(theta) - math.sin(theta)) >= 0 else "leafD"
            faces.append((f"{leaf_prefix}S{i}", [leaf_bottom_ring[i], leaf_bottom_ring[nxt], leaf_mid_ring[nxt], leaf_mid_ring[i]]))
            faces.append((f"{leaf_prefix}T{i}", [leaf_mid_ring[i], leaf_mid_ring[nxt], "leaf_top_center"]))
            # Keep the underside winding oriented outward (downward normal)
            # so these faces remain visible from outside the tree canopy.
            faces.append((f"{leaf_prefix}B{i}", ["leaf_bottom_center", leaf_bottom_ring[nxt], leaf_bottom_ring[i]]))

    return verts, faces


def generate_bridge(length, width, clearance, bridge_height, bridge_half=False):
    length = max(1, int(length))
    width = max(1, int(width))
    clearance = max(1, int(clearance))
    bridge_height = max(1, int(bridge_height))

    y0 = -(width / 2.0)
    y1 = width / 2.0

    z0 = 0
    z1 = clearance
    z2 = clearance + bridge_height
    z3 = bridge_height

    if bridge_half:
        half_length = max(1, int(round(length / 2.0)))
        # Keep the chopped side on the world vertical axis so mirrored/swiveled
        # halves can meet cleanly without extra translation.
        x2 = 0
        x1 = -half_length
        x0 = -(half_length + clearance)
        profile = [
            (x0, z0),
            (x1, z1),
            (x2, z1),
            (x2, z2),
            (x1, z2),
            (x0, z3),
        ]
    else:
        total_span = length + (2 * clearance)
        x0 = -(total_span / 2.0)
        x1 = x0 + clearance
        x2 = x1 + length
        x3 = x2 + clearance
        profile = [
            (x0, z0),
            (x1, z1),
            (x2, z1),
            (x3, z0),
            (x3, z3),
            (x2, z2),
            (x1, z2),
            (x0, z3),
        ]

    verts = {}
    for index, (x, z) in enumerate(profile):
        verts[f"f{index}"] = (x, y0, z)
        verts[f"b{index}"] = (x, y1, z)

    if bridge_half:
        faces = [
            ("lsLeft", ["b0", "b1", "b4", "b5"]),
            ("lsCenter", ["b1", "b2", "b3", "b4"]),
            ("rsLeft", ["f5", "f4", "f1", "f0"]),
            ("rsCenter", ["f4", "f3", "f2", "f1"]),
            ("fr1", ["f0", "f5", "b5", "b0"]),
            ("topRampL", ["f5", "f4", "b4", "b5"]),
            ("topBridge", ["f4", "f3", "b3", "b4"]),
            ("botRampL", ["f0", "f1", "b1", "b0"]),
            ("botBridge", ["f1", "f2", "b2", "b1"]),
        ]
    else:
        faces = [
            ("lsLeft", ["b0", "b1", "b6", "b7"]),
            ("lsCenter", ["b1", "b2", "b5", "b6"]),
            ("lsRight", ["b2", "b3", "b4", "b5"]),
            ("rsLeft", ["f7", "f6", "f1", "f0"]),
            ("rsCenter", ["f6", "f5", "f2", "f1"]),
            ("rsRight", ["f5", "f4", "f3", "f2"]),
            ("fr1", ["f0", "f7", "b7", "b0"]),
            ("bk1", ["f4", "f3", "b3", "b4"]),
            ("topRampL", ["f7", "f6", "b6", "b7"]),
            ("topBridge", ["f6", "f5", "b5", "b6"]),
            ("topRampR", ["f5", "f4", "b4", "b5"]),
            ("botRampL", ["f0", "f1", "b1", "b0"]),
            ("botBridge", ["f1", "f2", "b2", "b1"]),
            ("botRampR", ["f2", "f3", "b3", "b2"]),
        ]

    return verts, faces


def calculate_grandstand_height(width, angle_degrees, front_height=0):
    width = max(1.0, float(width))
    angle = max(0.0, min(89.9, float(angle_degrees)))
    front = max(0, int(front_height))
    rise = math.tan(math.radians(angle)) * width
    return max(front, int(round(front + rise)))


def calculate_grandstand_angle(width, height, front_height=0):
    width = max(1.0, float(width))
    back_height = max(0.0, float(height))
    front = max(0.0, float(front_height))
    rise = max(0.0, back_height - front)
    return max(0.0, min(89.9, math.degrees(math.atan(rise / width))))


def generate_grandstand(length, width, height, front_height=0):
    length = max(1, int(length))
    width = max(1, int(width))
    front_height = max(0, int(front_height))
    height = max(front_height, int(height))

    verts = {
        "gs_tf_l": (0, 0, front_height),
        "gs_tf_r": (length, 0, front_height),
        "gs_tb_l": (0, width, height),
        "gs_tb_r": (length, width, height),
        "gs_bf_l": (0, 0, 0),
        "gs_bf_r": (length, 0, 0),
        "gs_bb_l": (0, width, 0),
        "gs_bb_r": (length, width, 0),
    }

    faces = [
        ("seatB", ["gs_tf_l", "gs_tf_r", "gs_tb_r", "gs_tb_l"]),
        ("seatD", ["gs_bf_l", "gs_bb_l", "gs_bb_r", "gs_bf_r"]),
        ("seatBack", ["gs_tb_l", "gs_tb_r", "gs_bb_r", "gs_bb_l"]),
        ("seatLs", ["gs_tf_l", "gs_tb_l", "gs_bb_l", "gs_bf_l"]),
        ("seatRs", ["gs_tf_r", "gs_bf_r", "gs_bb_r", "gs_tb_r"]),
    ]

    if front_height > 0:
        faces.append(("seatFront", ["gs_tf_l", "gs_bf_l", "gs_bf_r", "gs_tf_r"]))

    return verts, faces


def generate_building(
    width,
    depth,
    height,
    roof_type,
    inset,
    roof_height,
    gable_rise,
    pyramid_rise,
    building_shape="rectangular",
    diameter=320,
    num_sides=12,
    dome_layers=4,
    dome_roundness=100,
    rect_center_origin=False,
    tree_trunk_width=30,
    tree_leaf_base_height=100,
    tree_num_sides=12,
    tree_profile="pointy",
    bridge_length=320,
    bridge_width=80,
    bridge_clearance=100,
    bridge_height=20,
    bridge_half=False,
    grandstand_length=320,
    grandstand_width=120,
    grandstand_height=100,
    grandstand_front_height=0,
):
    if building_shape == "tree":
        return generate_tree(width, height, tree_trunk_width, tree_leaf_base_height, tree_num_sides, tree_profile)

    if building_shape == "circular":
        verts, faces = generate_circular_base(diameter, num_sides, height)
        if roof_type == "flat":
            add_circular_flat_roof(verts, faces, num_sides, diameter, height)
        elif roof_type == "dome":
            if int(dome_roundness) <= 0:
                add_circular_flat_roof(verts, faces, num_sides, diameter, height)
            else:
                add_circular_dome_roof(verts, faces, diameter, num_sides, height, dome_layers, dome_roundness)
        return verts, faces

    if building_shape == "bridge":
        return generate_bridge(bridge_length, bridge_width, bridge_clearance, bridge_height, bridge_half=bridge_half)

    if building_shape == "grandstand":
        return generate_grandstand(grandstand_length, grandstand_width, grandstand_height, grandstand_front_height)

    verts, faces = generate_base(width, depth, height)

    if roof_type == "flat":
        add_flat_roof(faces)
    elif roof_type == "parapet":
        add_parapet_roof(verts, faces, width, depth, height, inset, roof_height)
    elif roof_type == "gable":
        add_gable_roof(verts, faces, width, depth, height, gable_rise)
    elif roof_type == "pyramid":
        add_pyramid_roof(verts, faces, width, depth, height, pyramid_rise)

    if rect_center_origin:
        x_offset = -(width // 2)
        y_offset = -(depth // 2)
        for name, (x, y, z) in list(verts.items()):
            verts[name] = (x + x_offset, y + y_offset, z)

    return verts, faces


# ------------------------------------------------------------
# .3D writer
# ------------------------------------------------------------

def write_3d(path, verts, faces, parameters):
    roof_bright = int(parameters.get("roof_color_bright", 0))
    roof_dark = int(parameters.get("roof_color_dark", roof_bright))
    side_bright = int(parameters.get("side_color_bright", 0))
    side_dark = int(parameters.get("side_color_dark", side_bright))
    roof_type = str(parameters.get("roof_type", ""))
    building_shape = str(parameters.get("building_shape", "rectangular"))
    tree_trunk_color = int(parameters.get("tree_trunk_color", side_dark))
    tree_leaves_color = int(parameters.get("tree_leaves_color", side_bright))
    tree_trunk_color_bright = int(parameters.get("tree_trunk_color_bright", tree_trunk_color))
    tree_trunk_color_dark = int(parameters.get("tree_trunk_color_dark", tree_trunk_color_bright))
    tree_leaves_color_bright = int(parameters.get("tree_leaves_color_bright", tree_leaves_color))
    tree_leaves_color_dark = int(parameters.get("tree_leaves_color_dark", tree_leaves_color_bright))

    if roof_type == "flat":
        roof_dark = roof_bright

    def color_for_face(name):
        if building_shape == "tree":
            if name.startswith("trunkB"):
                return tree_trunk_color_bright
            if name.startswith("trunkD"):
                return tree_trunk_color_dark
            if name.startswith("leafB"):
                return tree_leaves_color_bright
            if name.startswith("leafD"):
                return tree_leaves_color_dark

        roof_bright_faces = {"topB", "roofB", "roofL", "pyrF", "pyrL"}
        roof_dark_faces = {"topD", "roofD", "roofR", "pyrR", "pyrB"}
        side_bright_faces = {"ls1", "fr1", "ls2", "fr2", "gableF"}
        side_dark_faces = {"rs1", "bk1", "rs2", "bk2", "gableB"}

        if roof_type == "parapet":
            parapet_side_bright_faces = {"ls2", "fr2"}
            parapet_side_dark_faces = {"rs2", "bk2"}
            parapet_top_faces = {"roofB", "roofD"}

            if name in parapet_side_bright_faces:
                return roof_bright
            if name in parapet_side_dark_faces:
                return roof_dark
            if name in parapet_top_faces:
                return roof_bright

        if name in roof_bright_faces or name.startswith("roofB"):
            return roof_bright
        if name.startswith("seatB"):
            return roof_bright
        if name.startswith("seatD"):
            return roof_dark
        if name.startswith("scaffoldB"):
            return side_bright
        if name.startswith("scaffoldD"):
            return side_dark
        if name.startswith("top"):
            return roof_bright
        if name in roof_dark_faces or name.startswith("roofD"):
            return roof_dark
        if name.startswith("bot"):
            return roof_dark
        if name in side_bright_faces or name.startswith("sideB") or name.startswith("ls"):
            return side_bright
        if name in side_dark_faces or name.startswith("sideD") or name.startswith("rs"):
            return side_dark
        return side_bright

    lines = []
    lines.append("3D VERSION 3.0;")
    lines.append("% Generated by ICR2 Building Generator")
    for key, value in parameters.items():
        lines.append(f"% {key}: {value}")
    lines.append("")
    lines.append("nil: NIL;")

    for name in verts:
        x, y, z = verts[name]
        lines.append(f"{name}: [<{x}, {y}, {z}>];")

    lines.append("")

    for name, vs in faces:
        v = ", ".join(vs)
        lines.append(f"{name}: POLY <{color_for_face(name)}> {{{v}}};")

    lines.append("")

    prev = "nil"

    for i, (name, vs) in enumerate(faces):
        v1, v2, v3 = vs[:3]
        node = f"o{i}"
        lines.append(f"{node}: BSPF ({v1}, {v2}, {v3}), nil, {name}, {prev};")
        prev = node

    v1, v2, v3 = faces[-1][1][:3]
    lines.append(f"root: BSPF ({v1}, {v2}, {v3}), nil, {faces[-1][0]}, {prev};")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ------------------------------------------------------------
# UI helpers
# ------------------------------------------------------------

def load_settings():
    config = configparser.ConfigParser()
    config.read(INI_PATH)
    return config


def save_settings(config: configparser.ConfigParser):
    with open(INI_PATH, "w", encoding="utf-8") as ini_file:
        config.write(ini_file)


def set_sunny_path(config: configparser.ConfigParser, sunny_pcx_path: str):
    if not config.has_section("paths"):
        config.add_section("paths")
    config["paths"]["sunny_pcx"] = sunny_pcx_path


def set_last_3d_dir(config: configparser.ConfigParser, directory: str):
    if not config.has_section("paths"):
        config.add_section("paths")
    config["paths"]["last_3d_dir"] = directory


def list_template_names(config: configparser.ConfigParser):
    return sorted(
        section[len(TEMPLATE_SECTION_PREFIX):]
        for section in config.sections()
        if section.startswith(TEMPLATE_SECTION_PREFIX)
    )


def get_template_values(config: configparser.ConfigParser, name: str):
    section = f"{TEMPLATE_SECTION_PREFIX}{name}"
    if not config.has_section(section):
        return None
    return {field: config.get(section, field, fallback="") for field in TEMPLATE_FIELDS}


def save_template(config: configparser.ConfigParser, name: str, values):
    section = f"{TEMPLATE_SECTION_PREFIX}{name}"
    if not config.has_section(section):
        config.add_section(section)
    for field in TEMPLATE_FIELDS:
        config[section][field] = str(values.get(field, ""))


def remove_template(config: configparser.ConfigParser, name: str):
    config.remove_section(f"{TEMPLATE_SECTION_PREFIX}{name}")


def int_or_default(raw_value, default):
    if raw_value is None:
        return default
    if isinstance(raw_value, str) and not raw_value.strip():
        return default
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return default


def float_or_default(raw_value, default):
    if raw_value is None:
        return default
    if isinstance(raw_value, str) and not raw_value.strip():
        return default
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return default


def load_sunny_palette(path: str | Path):
    data = Path(path).read_bytes()
    if len(data) < 769 or data[-769] != 0x0C:
        raise ValueError("Invalid or missing 256-color PCX palette marker")
    raw = data[-768:]
    return [(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, 768, 3)]


def _ui_imports():
    from PyQt5 import QtCore, QtGui, QtWidgets

    return QtCore, QtGui, QtWidgets


def build_window():
    QtCore, QtGui, QtWidgets = _ui_imports()

    class PaletteMatrixDialog(QtWidgets.QDialog):
        def __init__(self, parent, palette, selected_index: int):
            super().__init__(parent)
            self.setWindowTitle("Pick Palette Color")
            self.selected_index = int(max(0, min(255, selected_index)))

            layout = QtWidgets.QVBoxLayout(self)
            info = QtWidgets.QLabel("Select a palette index (0-255):")
            layout.addWidget(info)

            grid = QtWidgets.QGridLayout()
            grid.setSpacing(2)
            self._tiles = {}

            for index, (r, g, b) in enumerate(palette[:256]):
                tile = QtWidgets.QPushButton(f"{index}")
                tile.setFixedSize(34, 24)
                tile.setToolTip(f"Index {index}: rgb({r}, {g}, {b})")
                tile.setStyleSheet(
                    "QPushButton {"
                    f"background-color: rgb({r}, {g}, {b});"
                    "color: #000;"
                    "border: 1px solid #444;"
                    "font-size: 10px;"
                    "padding: 0px;"
                    "}"
                )
                tile.clicked.connect(lambda _checked=False, idx=index: self._choose(idx))
                grid.addWidget(tile, index // 16, index % 16)
                self._tiles[index] = tile

            layout.addLayout(grid)
            self._apply_selection_outline()

        def _apply_selection_outline(self):
            for index, tile in self._tiles.items():
                if index == self.selected_index:
                    tile.setStyleSheet(tile.styleSheet() + "QPushButton { border: 2px solid #fff; }")

        def _choose(self, index: int):
            self.selected_index = int(index)
            self.accept()

    class PaletteIndexPicker(QtWidgets.QWidget):
        def __init__(self, parent, palette, initial_index: int):
            super().__init__(parent)
            self._palette = list(palette)
            self._index = int(max(0, min(255, initial_index)))

            layout = QtWidgets.QHBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)

            self._preview = QtWidgets.QLabel()
            self._preview.setFixedWidth(90)
            self._button = QtWidgets.QPushButton("Pick...")
            self._button.clicked.connect(self._open_picker)

            layout.addWidget(self._preview)
            layout.addWidget(self._button)
            self._refresh_preview()

        def _refresh_preview(self):
            r, g, b = self._palette[self._index]
            self._preview.setText(f"{self._index:>3} ({r},{g},{b})")
            self._preview.setStyleSheet(
                "QLabel {"
                f"background-color: rgb({r}, {g}, {b});"
                "border: 1px solid #222;"
                "padding: 2px;"
                "}"
            )

        def _open_picker(self):
            dialog = PaletteMatrixDialog(self, self._palette, self._index)
            if dialog.exec_() != QtWidgets.QDialog.Accepted:
                return
            self._index = dialog.selected_index
            self._refresh_preview()

        def set_palette(self, palette):
            self._palette = list(palette)
            self._refresh_preview()

        def set_color_index(self, index: int):
            self._index = int(max(0, min(255, index)))
            self._refresh_preview()

        def color_index(self):
            return self._index

    class MainWindow(QtWidgets.QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("ICR2 Building Generator")
            self.palette = [(0, 0, 0)] * 256
            self.settings = load_settings()
            self._updating_grandstand_fields = False
            self._build_ui()

        def _build_ui(self):
            central = QtWidgets.QWidget(self)
            self.setCentralWidget(central)
            root_layout = QtWidgets.QHBoxLayout(central)

            self.template_list = QtWidgets.QListWidget()
            self.template_list.setMinimumWidth(220)
            self.save_template_btn = QtWidgets.QPushButton("Save Template")
            self.load_template_btn = QtWidgets.QPushButton("Load Selected")
            self.remove_template_btn = QtWidgets.QPushButton("Remove Selected")

            self.save_template_btn.clicked.connect(self.save_template_clicked)
            self.load_template_btn.clicked.connect(self.load_template_clicked)
            self.remove_template_btn.clicked.connect(self.remove_template_clicked)

            template_layout = QtWidgets.QVBoxLayout()
            template_layout.addWidget(QtWidgets.QLabel("Templates"))
            template_layout.addWidget(self.template_list, 1)
            template_layout.addWidget(self.save_template_btn)
            template_layout.addWidget(self.load_template_btn)
            template_layout.addWidget(self.remove_template_btn)

            form_widget = QtWidgets.QWidget()
            layout = QtWidgets.QGridLayout(form_widget)
            root_layout.addLayout(template_layout)
            root_layout.addWidget(form_widget, 1)

            self.width_spin = QtWidgets.QSpinBox()
            self.width_spin.setRange(1, 50000)
            self.width_spin.setValue(320)

            self.depth_spin = QtWidgets.QSpinBox()
            self.depth_spin.setRange(1, 50000)
            self.depth_spin.setValue(1042)

            self.height_spin = QtWidgets.QSpinBox()
            self.height_spin.setRange(1, 50000)
            self.height_spin.setValue(100)

            self.tree_trunk_width_spin = QtWidgets.QSpinBox()
            self.tree_trunk_width_spin.setRange(1, 50000)
            self.tree_trunk_width_spin.setValue(30)

            self.tree_leaf_base_height_spin = QtWidgets.QSpinBox()
            self.tree_leaf_base_height_spin.setRange(1, 50000)
            self.tree_leaf_base_height_spin.setValue(100)

            self.tree_sides_spin = QtWidgets.QSpinBox()
            self.tree_sides_spin.setRange(3, 256)
            self.tree_sides_spin.setValue(12)

            self.tree_profile_combo = QtWidgets.QComboBox()
            self.tree_profile_combo.addItems(["pointy", "round", "palm"])

            self.shape_combo = QtWidgets.QComboBox()
            self.shape_combo.addItems(["rectangular", "circular", "tree", "bridge", "grandstand"])
            self.shape_combo.currentTextChanged.connect(self.update_shape_field_visibility)

            self.roof_combo = QtWidgets.QComboBox()
            self.roof_combo.currentTextChanged.connect(self.update_roof_field_visibility)

            self.inset_spin = QtWidgets.QSpinBox()
            self.inset_spin.setRange(0, 50000)
            self.inset_spin.setValue(30)

            self.roof_height_spin = QtWidgets.QSpinBox()
            self.roof_height_spin.setRange(0, 50000)
            self.roof_height_spin.setValue(15)

            self.gable_spin = QtWidgets.QSpinBox()
            self.gable_spin.setRange(0, 50000)
            self.gable_spin.setValue(50)

            self.pyramid_spin = QtWidgets.QSpinBox()
            self.pyramid_spin.setRange(0, 50000)
            self.pyramid_spin.setValue(50)

            self.diameter_spin = QtWidgets.QSpinBox()
            self.diameter_spin.setRange(1, 50000)
            self.diameter_spin.setValue(320)

            self.sides_spin = QtWidgets.QSpinBox()
            self.sides_spin.setRange(3, 256)
            self.sides_spin.setValue(16)

            self.dome_layers_spin = QtWidgets.QSpinBox()
            self.dome_layers_spin.setRange(1, 256)
            self.dome_layers_spin.setValue(4)

            self.dome_roundness_spin = QtWidgets.QSpinBox()
            self.dome_roundness_spin.setRange(0, 100)
            self.dome_roundness_spin.setSuffix("%")
            self.dome_roundness_spin.setValue(100)

            self.rect_center_check = QtWidgets.QCheckBox("Center rectangular building at (0,0)")

            self.bridge_length_spin = QtWidgets.QSpinBox()
            self.bridge_length_spin.setRange(1, 50000)
            self.bridge_length_spin.setValue(320)

            self.bridge_width_spin = QtWidgets.QSpinBox()
            self.bridge_width_spin.setRange(1, 50000)
            self.bridge_width_spin.setValue(80)

            self.bridge_clearance_spin = QtWidgets.QSpinBox()
            self.bridge_clearance_spin.setRange(1, 50000)
            self.bridge_clearance_spin.setValue(100)

            self.bridge_height_spin = QtWidgets.QSpinBox()
            self.bridge_height_spin.setRange(1, 50000)
            self.bridge_height_spin.setValue(20)

            self.bridge_half_check = QtWidgets.QCheckBox("Generate half bridge")

            self.grandstand_length_spin = QtWidgets.QSpinBox()
            self.grandstand_length_spin.setRange(1, 50000)
            self.grandstand_length_spin.setValue(320)

            self.grandstand_width_spin = QtWidgets.QSpinBox()
            self.grandstand_width_spin.setRange(1, 50000)
            self.grandstand_width_spin.setValue(120)

            self.grandstand_height_spin = QtWidgets.QSpinBox()
            self.grandstand_height_spin.setRange(0, 50000)
            self.grandstand_height_spin.setValue(100)

            self.grandstand_angle_spin = QtWidgets.QDoubleSpinBox()
            self.grandstand_angle_spin.setRange(0.0, 89.9)
            self.grandstand_angle_spin.setDecimals(1)
            self.grandstand_angle_spin.setSuffix("°")
            self.grandstand_angle_spin.setSingleStep(0.5)
            self.grandstand_angle_spin.setValue(39.8)

            self.grandstand_front_height_spin = QtWidgets.QSpinBox()
            self.grandstand_front_height_spin.setRange(0, 50000)
            self.grandstand_front_height_spin.setValue(0)
            self.grandstand_angle_spin.valueChanged.connect(self.update_grandstand_height_from_angle)
            self.grandstand_height_spin.valueChanged.connect(self.update_grandstand_angle_from_height)
            self.grandstand_width_spin.valueChanged.connect(self.update_grandstand_angle_from_height)
            self.grandstand_front_height_spin.valueChanged.connect(self.update_grandstand_angle_from_height)

            self.roof_bright_picker = PaletteIndexPicker(self, self.palette, 200)
            self.roof_dark_picker = PaletteIndexPicker(self, self.palette, 201)
            self.side_bright_picker = PaletteIndexPicker(self, self.palette, 202)
            self.side_dark_picker = PaletteIndexPicker(self, self.palette, 203)
            self.tree_trunk_bright_picker = PaletteIndexPicker(self, self.palette, 96)
            self.tree_trunk_dark_picker = PaletteIndexPicker(self, self.palette, 97)
            self.tree_leaves_bright_picker = PaletteIndexPicker(self, self.palette, 120)
            self.tree_leaves_dark_picker = PaletteIndexPicker(self, self.palette, 121)
            self.color_pickers = [
                self.roof_bright_picker,
                self.roof_dark_picker,
                self.side_bright_picker,
                self.side_dark_picker,
                self.tree_trunk_bright_picker,
                self.tree_trunk_dark_picker,
                self.tree_leaves_bright_picker,
                self.tree_leaves_dark_picker,
            ]

            self.sunny_edit = QtWidgets.QLineEdit(self.settings.get("paths", "sunny_pcx", fallback=""))
            self.sunny_browse = QtWidgets.QPushButton("Browse...")
            self.sunny_browse.clicked.connect(self.load_sunny_pcx_clicked)

            self.generate_btn = QtWidgets.QPushButton("Generate .3D")
            self.generate_btn.clicked.connect(self.generate_clicked)

            self.form_rows = {}

            def add_form_row(row, field_name, label_text, widget):
                label = QtWidgets.QLabel(label_text)
                layout.addWidget(label, row, 0)
                layout.addWidget(widget, row, 1)
                self.form_rows[field_name] = (label, widget)

            row_specs = [
                ("building_shape", "Building Shape", self.shape_combo),
                ("rect_center_origin", "Rect Origin", self.rect_center_check),
                ("width", "Width", self.width_spin),
                ("depth", "Depth", self.depth_spin),
                ("diameter", "Diameter", self.diameter_spin),
                ("num_sides", "Number of Sides", self.sides_spin),
                ("height", "Height", self.height_spin),
                ("bridge_length", "Bridge Length", self.bridge_length_spin),
                ("bridge_width", "Bridge Width", self.bridge_width_spin),
                ("bridge_clearance", "Bridge Ground Clearance", self.bridge_clearance_spin),
                ("bridge_height", "Bridge Height", self.bridge_height_spin),
                ("bridge_half", "Bridge Half", self.bridge_half_check),
                ("grandstand_length", "Grandstand Length", self.grandstand_length_spin),
                ("grandstand_width", "Grandstand Width", self.grandstand_width_spin),
                ("grandstand_height", "Grandstand Height", self.grandstand_height_spin),
                ("grandstand_angle", "Grandstand Angle", self.grandstand_angle_spin),
                ("grandstand_front_height", "Grandstand Front Height", self.grandstand_front_height_spin),
                ("tree_trunk_width", "Tree Trunk Width", self.tree_trunk_width_spin),
                ("tree_leaf_base_height", "Tree Leaf Base Height", self.tree_leaf_base_height_spin),
                ("tree_num_sides", "Tree Circle Sides", self.tree_sides_spin),
                ("tree_profile", "Tree Profile", self.tree_profile_combo),
                ("roof_type", "Roof Type", self.roof_combo),
                ("parapet_inset", "Parapet Inset", self.inset_spin),
                ("parapet_height", "Parapet Height", self.roof_height_spin),
                ("gable_rise", "Gable Rise", self.gable_spin),
                ("pyramid_rise", "Pyramid Rise", self.pyramid_spin),
                ("dome_layers", "Dome Layers", self.dome_layers_spin),
                ("dome_roundness", "Dome Roundness", self.dome_roundness_spin),
                ("roof_color_bright", "Roof Color (Bright)", self.roof_bright_picker),
                ("roof_color_dark", "Roof Color (Dark)", self.roof_dark_picker),
                ("side_color_bright", "Side Color (Bright)", self.side_bright_picker),
                ("side_color_dark", "Side Color (Dark)", self.side_dark_picker),
                ("tree_trunk_color_bright", "Tree Trunk Color (Bright)", self.tree_trunk_bright_picker),
                ("tree_trunk_color_dark", "Tree Trunk Color (Dark)", self.tree_trunk_dark_picker),
                ("tree_leaves_color_bright", "Tree Leaves Color (Bright)", self.tree_leaves_bright_picker),
                ("tree_leaves_color_dark", "Tree Leaves Color (Dark)", self.tree_leaves_dark_picker),
            ]
            for row, (field_name, label, widget) in enumerate(row_specs):
                add_form_row(row, field_name, label, widget)

            sunny_row = len(row_specs)
            layout.addWidget(QtWidgets.QLabel("sunny.pcx"), sunny_row, 0)
            path_layout = QtWidgets.QHBoxLayout()
            path_layout.addWidget(self.sunny_edit)
            path_layout.addWidget(self.sunny_browse)
            layout.addLayout(path_layout, sunny_row, 1)
            layout.addWidget(self.generate_btn, sunny_row + 1, 0, 1, 2)

            file_menu = self.menuBar().addMenu("File")
            load_action = QtWidgets.QAction("Load sunny.pcx...", self)
            load_action.triggered.connect(self.load_sunny_pcx_clicked)
            file_menu.addAction(load_action)

            self.refresh_color_combos(defaults=(200, 201, 202, 203))
            if self.sunny_edit.text().strip():
                self.try_load_palette(self.sunny_edit.text().strip(), preserve_selection=True)
            self.refresh_templates()
            self.update_shape_field_visibility(self.shape_combo.currentText())
            self.update_grandstand_height_from_angle()

        def _set_row_visible(self, field_name, is_visible: bool):
            label, widget = self.form_rows[field_name]
            label.setVisible(is_visible)
            widget.setVisible(is_visible)

        def _set_roof_options_for_shape(self, shape: str):
            shape = str(shape)
            if shape == "rectangular":
                options = ["none", "flat", "parapet", "gable", "pyramid"]
            elif shape == "circular":
                options = ["none", "flat", "dome"]
            elif shape in {"bridge", "grandstand"}:
                options = ["none"]
            else:
                options = ["none"]
            current = self.roof_combo.currentText()
            self.roof_combo.blockSignals(True)
            self.roof_combo.clear()
            self.roof_combo.addItems(options)
            self.roof_combo.setCurrentText(current if current in options else options[0])
            self.roof_combo.blockSignals(False)

        def update_grandstand_height_from_angle(self, _value=None):
            if self.shape_combo.currentText() != "grandstand" or self._updating_grandstand_fields:
                return
            self._updating_grandstand_fields = True
            calculated_height = calculate_grandstand_height(
                self.grandstand_width_spin.value(),
                self.grandstand_angle_spin.value(),
                self.grandstand_front_height_spin.value(),
            )
            self.grandstand_height_spin.setValue(calculated_height)
            self._updating_grandstand_fields = False

        def update_grandstand_angle_from_height(self, _value=None):
            if self.shape_combo.currentText() != "grandstand" or self._updating_grandstand_fields:
                return
            self._updating_grandstand_fields = True
            calculated_angle = calculate_grandstand_angle(
                self.grandstand_width_spin.value(),
                self.grandstand_height_spin.value(),
                self.grandstand_front_height_spin.value(),
            )
            self.grandstand_angle_spin.setValue(calculated_angle)
            self._updating_grandstand_fields = False

        def update_shape_field_visibility(self, shape: str):
            shape = str(shape)
            is_rectangular = shape == "rectangular"
            is_tree = shape == "tree"
            is_bridge = shape == "bridge"
            is_grandstand = shape == "grandstand"
            uses_standard_height = shape in {"rectangular", "circular", "tree"}
            self._set_roof_options_for_shape(shape)
            self._set_row_visible("width", is_rectangular or is_tree)
            self._set_row_visible("depth", is_rectangular)
            self._set_row_visible("height", uses_standard_height)
            self._set_row_visible("rect_center_origin", is_rectangular)
            self._set_row_visible("diameter", shape == "circular")
            self._set_row_visible("num_sides", shape == "circular")
            self._set_row_visible("bridge_length", is_bridge)
            self._set_row_visible("bridge_width", is_bridge)
            self._set_row_visible("bridge_clearance", is_bridge)
            self._set_row_visible("bridge_height", is_bridge)
            self._set_row_visible("bridge_half", is_bridge)
            self._set_row_visible("grandstand_length", is_grandstand)
            self._set_row_visible("grandstand_width", is_grandstand)
            self._set_row_visible("grandstand_height", is_grandstand)
            self._set_row_visible("grandstand_angle", is_grandstand)
            self._set_row_visible("grandstand_front_height", is_grandstand)
            self._set_row_visible("tree_trunk_width", is_tree)
            self._set_row_visible("tree_leaf_base_height", is_tree)
            self._set_row_visible("tree_num_sides", is_tree)
            self._set_row_visible("tree_profile", is_tree)
            self.update_roof_field_visibility(self.roof_combo.currentText())

        def update_roof_field_visibility(self, roof_type: str):
            roof_type = str(roof_type)
            shape = self.shape_combo.currentText()
            is_rectangular = shape == "rectangular"
            is_tree = shape == "tree"
            is_bridge = shape == "bridge"
            is_grandstand = shape == "grandstand"
            show_building_colors = (not is_tree) and (not is_grandstand)
            self._set_row_visible("roof_color_bright", show_building_colors)
            self._set_row_visible("roof_color_dark", is_bridge or ((roof_type not in {"none", "flat"}) and show_building_colors))
            self._set_row_visible("side_color_bright", show_building_colors)
            self._set_row_visible("side_color_dark", show_building_colors)
            self._set_row_visible("tree_trunk_color_bright", is_tree)
            self._set_row_visible("tree_trunk_color_dark", is_tree)
            self._set_row_visible("tree_leaves_color_bright", is_tree)
            self._set_row_visible("tree_leaves_color_dark", is_tree)
            self._set_row_visible("roof_type", (not is_tree) and (not is_bridge) and (not is_grandstand))
            self._set_row_visible("parapet_inset", is_rectangular and roof_type == "parapet")
            self._set_row_visible("parapet_height", is_rectangular and roof_type == "parapet")
            self._set_row_visible("gable_rise", is_rectangular and roof_type == "gable")
            self._set_row_visible("pyramid_rise", is_rectangular and roof_type == "pyramid")
            is_dome = (not is_rectangular) and roof_type == "dome"
            self._set_row_visible("dome_layers", is_dome)
            self._set_row_visible("dome_roundness", is_dome)

        def collect_current_values(self):
            return {
                "building_shape": self.shape_combo.currentText(),
                "width": self.width_spin.value(),
                "depth": self.depth_spin.value(),
                "rect_center_origin": self.rect_center_check.isChecked(),
                "diameter": self.diameter_spin.value(),
                "num_sides": self.sides_spin.value(),
                "height": self.height_spin.value(),
                "bridge_length": self.bridge_length_spin.value(),
                "bridge_width": self.bridge_width_spin.value(),
                "bridge_clearance": self.bridge_clearance_spin.value(),
                "bridge_height": self.bridge_height_spin.value(),
                "bridge_half": self.bridge_half_check.isChecked(),
                "grandstand_length": self.grandstand_length_spin.value(),
                "grandstand_width": self.grandstand_width_spin.value(),
                "grandstand_height": self.grandstand_height_spin.value(),
                "grandstand_angle": self.grandstand_angle_spin.value(),
                "grandstand_front_height": self.grandstand_front_height_spin.value(),
                "tree_trunk_width": self.tree_trunk_width_spin.value(),
                "tree_leaf_base_height": self.tree_leaf_base_height_spin.value(),
                "tree_num_sides": self.tree_sides_spin.value(),
                "tree_profile": self.tree_profile_combo.currentText(),
                "roof_type": self.roof_combo.currentText(),
                "parapet_inset": self.inset_spin.value(),
                "parapet_height": self.roof_height_spin.value(),
                "gable_rise": self.gable_spin.value(),
                "pyramid_rise": self.pyramid_spin.value(),
                "dome_layers": self.dome_layers_spin.value(),
                "dome_roundness": self.dome_roundness_spin.value(),
                "sunny_pcx": self.sunny_edit.text().strip(),
                "roof_color_bright": self.roof_bright_picker.color_index(),
                "roof_color_dark": self.roof_dark_picker.color_index(),
                "side_color_bright": self.side_bright_picker.color_index(),
                "side_color_dark": self.side_dark_picker.color_index(),
                "tree_trunk_color_bright": self.tree_trunk_bright_picker.color_index(),
                "tree_trunk_color_dark": self.tree_trunk_dark_picker.color_index(),
                "tree_leaves_color_bright": self.tree_leaves_bright_picker.color_index(),
                "tree_leaves_color_dark": self.tree_leaves_dark_picker.color_index(),
            }

        def apply_values(self, values):
            self.shape_combo.setCurrentText(values.get("building_shape", self.shape_combo.currentText()))
            self.width_spin.setValue(int_or_default(values.get("width"), self.width_spin.value()))
            self.depth_spin.setValue(int_or_default(values.get("depth"), self.depth_spin.value()))
            self.rect_center_check.setChecked(str(values.get("rect_center_origin", "False")).lower() in {"1", "true", "yes", "on"})
            self.diameter_spin.setValue(int_or_default(values.get("diameter"), self.diameter_spin.value()))
            self.sides_spin.setValue(int_or_default(values.get("num_sides"), self.sides_spin.value()))
            self.height_spin.setValue(int_or_default(values.get("height"), self.height_spin.value()))
            self.bridge_length_spin.setValue(int_or_default(values.get("bridge_length"), self.bridge_length_spin.value()))
            self.bridge_width_spin.setValue(int_or_default(values.get("bridge_width"), self.bridge_width_spin.value()))
            self.bridge_clearance_spin.setValue(int_or_default(values.get("bridge_clearance"), self.bridge_clearance_spin.value()))
            self.bridge_height_spin.setValue(int_or_default(values.get("bridge_height"), self.bridge_height_spin.value()))
            self.bridge_half_check.setChecked(str(values.get("bridge_half", "False")).lower() in {"1", "true", "yes", "on"})
            self.grandstand_length_spin.setValue(int_or_default(values.get("grandstand_length"), self.grandstand_length_spin.value()))
            self.grandstand_width_spin.setValue(int_or_default(values.get("grandstand_width"), self.grandstand_width_spin.value()))
            self.grandstand_height_spin.setValue(int_or_default(values.get("grandstand_height"), self.grandstand_height_spin.value()))
            self.grandstand_angle_spin.setValue(float_or_default(values.get("grandstand_angle"), self.grandstand_angle_spin.value()))
            self.grandstand_front_height_spin.setValue(int_or_default(values.get("grandstand_front_height"), self.grandstand_front_height_spin.value()))
            self.tree_trunk_width_spin.setValue(int_or_default(values.get("tree_trunk_width"), self.tree_trunk_width_spin.value()))
            self.tree_leaf_base_height_spin.setValue(int_or_default(values.get("tree_leaf_base_height"), self.tree_leaf_base_height_spin.value()))
            self.tree_sides_spin.setValue(int_or_default(values.get("tree_num_sides"), self.tree_sides_spin.value()))
            self.tree_profile_combo.setCurrentText(str(values.get("tree_profile", self.tree_profile_combo.currentText()) or "pointy"))
            self.roof_combo.setCurrentText(values.get("roof_type", self.roof_combo.currentText()))
            self.inset_spin.setValue(int_or_default(values.get("parapet_inset"), self.inset_spin.value()))
            self.roof_height_spin.setValue(int_or_default(values.get("parapet_height"), self.roof_height_spin.value()))
            self.gable_spin.setValue(int_or_default(values.get("gable_rise"), self.gable_spin.value()))
            self.pyramid_spin.setValue(int_or_default(values.get("pyramid_rise"), self.pyramid_spin.value()))
            self.dome_layers_spin.setValue(int_or_default(values.get("dome_layers"), self.dome_layers_spin.value()))
            self.dome_roundness_spin.setValue(int_or_default(values.get("dome_roundness"), self.dome_roundness_spin.value()))
            self.sunny_edit.setText(values.get("sunny_pcx", self.sunny_edit.text().strip()))

            self.roof_bright_picker.set_color_index(int_or_default(values.get("roof_color_bright"), 0))
            self.roof_dark_picker.set_color_index(int_or_default(values.get("roof_color_dark"), 0))
            self.side_bright_picker.set_color_index(int_or_default(values.get("side_color_bright"), 0))
            self.side_dark_picker.set_color_index(int_or_default(values.get("side_color_dark"), 0))
            tree_trunk_bright = int_or_default(values.get("tree_trunk_color_bright", values.get("tree_trunk_color")), 0)
            tree_trunk_dark = int_or_default(values.get("tree_trunk_color_dark"), tree_trunk_bright)
            tree_leaves_bright = int_or_default(values.get("tree_leaves_color_bright", values.get("tree_leaves_color")), 0)
            tree_leaves_dark = int_or_default(values.get("tree_leaves_color_dark"), tree_leaves_bright)
            self.tree_trunk_bright_picker.set_color_index(tree_trunk_bright)
            self.tree_trunk_dark_picker.set_color_index(tree_trunk_dark)
            self.tree_leaves_bright_picker.set_color_index(tree_leaves_bright)
            self.tree_leaves_dark_picker.set_color_index(tree_leaves_dark)

            path = self.sunny_edit.text().strip()
            if path:
                self.try_load_palette(path, preserve_selection=True)

        def refresh_templates(self):
            current_name = self.template_list.currentItem().text() if self.template_list.currentItem() else ""
            names = list_template_names(self.settings)
            self.template_list.clear()
            self.template_list.addItems(names)
            if current_name in names:
                matches = self.template_list.findItems(current_name, QtCore.Qt.MatchExactly)
                if matches:
                    self.template_list.setCurrentItem(matches[0])

        def save_template_clicked(self):
            name, ok = QtWidgets.QInputDialog.getText(self, "Save Template", "Template name:")
            template_name = name.strip()
            if not ok or not template_name:
                return
            save_template(self.settings, template_name, self.collect_current_values())
            save_settings(self.settings)
            self.refresh_templates()

        def load_template_clicked(self):
            item = self.template_list.currentItem()
            if not item:
                return
            values = get_template_values(self.settings, item.text())
            if values is None:
                QtWidgets.QMessageBox.warning(self, "Template", "Template not found in settings file.")
                return
            self.apply_values(values)

        def remove_template_clicked(self):
            item = self.template_list.currentItem()
            if not item:
                return
            remove_template(self.settings, item.text())
            save_settings(self.settings)
            self.refresh_templates()

        def refresh_color_combos(self, defaults=None):
            defaults = defaults or (0, 1, 2, 3, 96, 97, 120, 121)
            for picker, selected in zip(self.color_pickers, defaults):
                picker.set_palette(self.palette)
                picker.set_color_index(int(selected))

        def load_sunny_pcx_clicked(self):
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self,
                "Select sunny.pcx",
                self.sunny_edit.text().strip(),
                "PCX files (*.pcx);;All files (*.*)",
            )
            if not path:
                return
            self.try_load_palette(path, preserve_selection=True)
            self.sunny_edit.setText(path)
            set_sunny_path(self.settings, path)
            save_settings(self.settings)

        def try_load_palette(self, path: str, preserve_selection: bool):
            selections = [picker.color_index() for picker in self.color_pickers]
            try:
                self.palette = load_sunny_palette(path)
                self.refresh_color_combos(defaults=selections if preserve_selection else None)
            except Exception as exc:
                QtWidgets.QMessageBox.warning(self, "Palette Load Error", str(exc))

        def generate_clicked(self):
            try:
                roof = self.roof_combo.currentText()
                path = self.sunny_edit.text().strip()
                if path:
                    self.try_load_palette(path, preserve_selection=True)
                    set_sunny_path(self.settings, path)
                    save_settings(self.settings)

                values = self.collect_current_values()
                verts, faces = generate_building(
                    values["width"],
                    values["depth"],
                    values["height"],
                    roof,
                    values["parapet_inset"],
                    values["parapet_height"],
                    values["gable_rise"],
                    values["pyramid_rise"],
                    values["building_shape"],
                    values["diameter"],
                    values["num_sides"],
                    values["dome_layers"],
                    values["dome_roundness"],
                    values["rect_center_origin"],
                    values["tree_trunk_width"],
                    values["tree_leaf_base_height"],
                    values["tree_num_sides"],
                    values["tree_profile"],
                    values["bridge_length"],
                    values["bridge_width"],
                    values["bridge_clearance"],
                    values["bridge_height"],
                    values["bridge_half"],
                    values["grandstand_length"],
                    values["grandstand_width"],
                    values["grandstand_height"],
                    values["grandstand_front_height"],
                )

                default_save_dir = self.settings.get("paths", "last_3d_dir", fallback="")
                out_path, _ = QtWidgets.QFileDialog.getSaveFileName(
                    self,
                    "Save .3D",
                    default_save_dir,
                    "3D files (*.3D)",
                )
                if not out_path:
                    return

                set_last_3d_dir(self.settings, str(Path(out_path).parent))
                save_settings(self.settings)

                params = dict(values)
                params["roof_type"] = roof

                write_3d(out_path, verts, faces, params)
                QtWidgets.QMessageBox.information(self, "Success", "Building generated successfully.")
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, "Error", str(exc))

    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    app.exec_()


if __name__ == "__main__":
    build_window()
