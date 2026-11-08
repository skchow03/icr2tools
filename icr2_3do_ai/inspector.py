"""Structured, read-only 3DO/N3 scene inspection for coding agents.

This module reuses the actual 3DO CAD parser, car appearance resolver, model
references and material rules; it does NOT implement a second 3DO decoder.
All outputs are derived reports and never modify source game assets.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import json
import struct
import sys

# CAD's existing modules use sibling-level imports. This small bootstrap lets
# "python -m icr2_3do_ai" run from the repository root without installing Qt.
_CAD = Path(__file__).resolve().parents[1] / "icr2_3do_cad"
if str(_CAD) not in sys.path:
    sys.path.insert(0, str(_CAD))

from car import recolor_table
from car_appearance import read_car_appearance
from n3_compile import compile_n3_text
from scene import build_scene, load_car_or_model
from textures import find_texture
from three_do import NAMES, FormatError

from .geometry import analyze_geometry


SCHEMA_VERSION = "1.0"


def _mip_metadata(path):
    """Read texture dimensions without decompressing potentially huge atlases.

    This is a header inspection only, not proof the entire MIP is decodable.
    The CAD texture loader performs full validation when actually rendering.
    """
    data = Path(path).read_bytes()
    if len(data) < 36:
        raise ValueError("MIP header truncated")
    declared, _, width, height, levels, _ = struct.unpack_from("<6i", data)
    if declared not in (len(data), len(data) - 4):
        raise ValueError("MIP declared size differs from actual file length")
    if not (1 <= width <= 4096 and 1 <= height <= 4096
            and 1 <= levels <= 16 and len(data) >= 24 + 12 * levels):
        raise ValueError("Invalid MIP dimensions or level table")
    return {
        "path": str(path), "width": width, "height": height,
        "mip_levels": levels, "header_validated_only": True,
    }


def _model_nodes(model):
    nodes = []
    for offset in sorted(model.records):
        kind = model.records[offset]
        node = {
            "offset": offset, "type": NAMES.get(kind, f"UNKNOWN_{kind}"),
            "child_pointers": list(model.children.get(offset, ())),
        }
        if offset in model.planes:
            node["plane_equation_raw"] = list(model.planes[offset].equation)
        if offset in model.materials:
            node["material_mip"], _ = model.materials[offset]
        if offset in model.switches:
            switch = model.switches[offset]
            node["switch_anchor_vertex_offset"] = switch.anchor
            node["switch_branches"] = [
                {"minimum_distance": threshold, "child_pointer": ptr}
                for threshold, ptr in switch.branches
            ]
        if offset in model.dynamics:
            placement = model.dynamics[offset]
            node["dynamic"] = {
                "external_name": placement.name,
                "external_table_index_1_based": placement.file_index,
                "translation_raw": list(placement.xyz),
                "angles_papyrus_signed": list(placement.angles),
            }
        if offset in model.pmp_sprites:
            sprite = model.pmp_sprites[offset]
            node["pmp"] = {
                "name": sprite.name, "anchor_vertex_offset": sprite.vertex_ref,
                "size": sprite.size,
            }
        if offset in model.polygons:
            poly = model.polygons[offset]
            node["polygon"] = {
                "kind": "POLY[T]" if poly.kind == 2 else "POLY",
                "color": poly.color, "group": poly.group,
                "vertex_offsets": list(poly.refs),
                "local_mip": model.polygon_materials.get(offset),
            }
        nodes.append(node)
    return nodes


def _scene_graph(scene):
    parent_links = {}
    for (parent_id, kind, pointer), child_id in scene.links.items():
        parent_links[child_id] = {
            "instance_id": parent_id, "link_kind": kind,
            "source_record_or_external_pointer": pointer,
        }
    models, model_ids = [], {}
    instances = []
    for instance_id, instance in enumerate(scene.instances):
        key = str(instance.model.path.resolve())
        if key not in model_ids:
            m = instance.model
            model_ids[key] = f"model{len(models)}"
            models.append({
                "id": model_ids[key], "path": str(m.path),
                "root_offset": m.root_offset,
                "body_start_in_file": m.body_start,
                "body_length": len(m.body),
                "mip_names": list(m.mip_names),
                "pmp_names": list(m.pmp_names),
                "external_3do_names": list(m.external_names),
                "polygon_count": len(m.polygons),
                "vertex_count": len(m.vertices),
                "sprite_count": len(m.pmp_sprites),
                "warnings": list(m.warnings),
                "recolor_mapping": {str(k): v
                                    for k, v in sorted(recolor_table(m).items())},
                "nodes": _model_nodes(m),
            })
        instances.append({
            "id": instance_id,
            "model_id": model_ids[key],
            "source_file": str(instance.model.path),
            "parent_link": parent_links.get(instance_id),
            "depth": instance.depth,
            "transform": {
                "matrix": [list(row) for row in instance.transform.matrix],
                "translation_raw": list(instance.transform.translation),
            },
            "polygon_count": len(instance.model.polygons),
            "sprite_count": len(instance.model.pmp_sprites),
            "paintable_body": instance.car_body,
            "inherited_material": instance.texture_override,
            "material_source": (str(instance.texture_source)
                                if instance.texture_source else None),
            "polygon_recolor_layers": [
                {str(k): v for k, v in sorted(layer.items())}
                for layer in instance.recolor_layers
            ],
            "sprite_recolor_layers": [
                {str(k): v for k, v in sorted(layer.items())}
                for layer in instance.sprite_recolor_layers
            ],
        })
    return {
        "models": models, "instances": instances,
        "link_count": len(scene.links),
        "limits": "Scene uses CAD's default max depth 4 and 2000 instances.",
    }


def _materials(geometry, *, texture_folder=None):
    grouped = defaultdict(list)
    for p in geometry["polygons"]:
        if p["kind"] == "POLY[T]" and p["material"]:
            grouped[(p["material"].casefold(), p["material_source"] or p["source_file"])].append(p)
    report, diagnostic = [], []
    for (name, origin), polygons in sorted(grouped.items()):
        texture_path = find_texture(
            name, Path(origin), texture_folder=texture_folder)
        item = {
            "name": name, "lookup_origin": origin,
            "polygon_count": len(polygons),
            "polygon_ids": [p["id"] for p in polygons],
            "file": None, "dimensions": None,
        }
        dims = None
        if texture_path is None:
            diagnostic.append({
                "severity": "warning", "code": "MISSING_MIP_FILE",
                "record": name, "source_file": origin,
                "message": "Named MIP could not be found in the selected asset directories",
            })
        else:
            try:
                dims = _mip_metadata(texture_path)
                item["file"] = str(texture_path)
                item["dimensions"] = dims
            except (OSError, ValueError) as err:
                diagnostic.append({
                    "severity": "warning", "code": "INVALID_MIP_HEADER",
                    "record": name, "source_file": origin,
                    "message": str(err),
                })
        if dims:
            w, h = dims["width"], dims["height"]
            outside = []
            for face in polygons:
                bound = face["uv_bounds"]
                if bound and (bound["min"][0] < 0 or bound["min"][1] < 0
                              or bound["max"][0] >= w or bound["max"][1] >= h):
                    outside.append(face["id"])
            item["out_of_bounds_uv_polygon_ids"] = outside
            if outside:
                diagnostic.append({
                    "severity": "info", "code": "UV_OUTSIDE_MIP",
                    "record": name, "source_file": origin,
                    "related_polygons": outside,
                    "message": "UVs extend beyond the base MIP dimensions; "
                               "this can be intentional for wrapping/repeat",
                })
        report.append(item)
    return {
        "materials": report,
        "named_material_count": len(report),
        "named_textured_polygon_count": sum(len(x["polygon_ids"]) for x in report),
        "unassigned_textured_polygon_ids": [
            p["id"] for p in geometry["polygons"]
            if p["kind"] == "POLY[T]" and not p["material"]
        ],
        "note": "Inherited MATERIAL comes from CAD scene resolution. "
                "MIP dimensions are header-only; per-texel RECOLOR is not applied "
                "to MIP pixels. Named material files may be absent.",
    }, diagnostic


def analyze_model(path, *, objects_folder=None, texture_folder=None,
                  appearance_path=None):
    """Return reports in memory. Supports binary .3do and N3 .3D source."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.suffix.casefold() == ".3do":
        if appearance_path:
            # Apply the driver appearance to this actual opened geometry,
            # without substituting another carshape from the wrapper.
            from three_do import Model
            original = Model(path, associate_planes=False)
            app = read_car_appearance(Path(appearance_path))
            model, scene, app = load_car_or_model(
                path, existing_model=original,
                objects_folder=objects_folder, appearance_override=app)
        else:
            model, scene, app = load_car_or_model(
                path, objects_folder=objects_folder)
    elif path.suffix.casefold() == ".3d":
        text = path.read_text(encoding="utf-8-sig")
        model, _ = compile_n3_text(text, path, associate_planes=False)
        app = read_car_appearance(Path(appearance_path)) if appearance_path else None
        scene = build_scene(model, objects_folder=objects_folder, appearance=app)
    else:
        raise ValueError("Expected binary .3do or editable N3 .3D")
    geometry, geo_diag = analyze_geometry(scene)
    graph = _scene_graph(scene)
    materials, mip_diag = _materials(geometry, texture_folder=texture_folder)
    diagnostics = list(geo_diag) + list(mip_diag)
    for warning in scene.warnings:
        diagnostics.append({
            "severity": "warning", "code": "SCENE_REFERENCE_WARNING",
            "record": None, "message": warning,
        })
    # The scene loader already includes Model warnings for the root only
    # indirectly; report all unique model parse warnings explicitly.
    for m in graph["models"]:
        for warning in m["warnings"]:
            diagnostics.append({
                "severity": "warning", "code": "MODEL_PARSE_WARNING",
                "record": m["id"], "source_file": m["path"],
                "message": warning,
            })
    sev = Counter(x["severity"] for x in diagnostics)
    kinds = Counter(p["kind"] for p in geometry["polygons"])
    summary = {
        "schema_version": SCHEMA_VERSION,
        "input_file": str(path.resolve()),
        "resolved_geometry_file": str(model.path.resolve()),
        "appearance_wrapper": str(app.path) if app else None,
        "units": geometry["units"],
        "bounds": geometry["bounds"],
        "counts": {
            "unique_models": len(graph["models"]),
            "instances": len(graph["instances"]),
            "polygons": len(geometry["polygons"]),
            "textured_polygons": kinds.get("POLY[T]", 0),
            "components": len(geometry["components"]),
            "named_materials": materials["named_material_count"],
            "diagnostic_warnings": sev.get("warning", 0),
            "diagnostic_errors": sev.get("error", 0),
        },
        "caveats": [
            "Component detection uses shared source-vertex edges, not proximity.",
            "Face normals are geometric winding estimates, not proven BSP-facing rules.",
            "BSP and RES records are exported without assuming any camera-visible set.",
            "Missing external 3DOs and MIPs leave partial analysis.",
        ],
    }
    return {
        "summary": summary, "geometry": geometry,
        "scene_graph": graph, "materials": materials,
        "diagnostics": {"entries": diagnostics, "counts_by_severity": dict(sev)},
        "_model": model,
    }


def _write_json(path, data):
    with Path(path).open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def write_package(path, output, *, objects_folder=None, texture_folder=None,
                  appearance_path=None, with_views=False, with_source=False,
                  overwrite=False):
    """Write an atomic-enough *new* analysis package, never game assets.

    Existing report files are rejected unless the caller explicitly opts in.
    Existing source input paths cannot be used as the output directory.
    """
    path, output = Path(path), Path(output)
    if output.resolve() == path.resolve() or path.resolve() in output.resolve().parents:
        raise ValueError("Output cannot be the source file or a directory inside it")
    targets = ["summary.json", "geometry.json", "scene_graph.json",
               "materials.json", "diagnostics.json"]
    if with_source:
        targets.append("source.3D")
    if with_views:
        targets.extend(("views/side.png", "views/top.png", "views/front.png"))
    if not overwrite and any((output / target).exists() for target in targets):
        raise FileExistsError("Report files already exist; specify --overwrite")
    report = analyze_model(
        path, objects_folder=objects_folder, texture_folder=texture_folder,
        appearance_path=appearance_path)
    if with_source:
        from text_3d import export_compilable_text
        if path.suffix.casefold() == ".3d":
            source = path.read_text(encoding="utf-8-sig")
        else:
            source = export_compilable_text(report["_model"])
    output.mkdir(parents=True, exist_ok=True)
    if with_source:
        (output / "source.3D").write_text(source, encoding="utf-8")
    if with_views:
        from .views import render_views
        render_views(report["geometry"], output / "views")
    for key in ("summary", "geometry", "scene_graph", "materials", "diagnostics"):
        _write_json(output / f"{key}.json", report[key])
    return report["summary"]
