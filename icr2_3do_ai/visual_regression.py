"""Deterministic CPU previews of *compiled* Papyrus N3 scenes.

Uses the CAD binary parser, its view-dependent BSP/DYNAMIC traversal, existing
MIP rasterizer and PMP sprite decoder. Orthographic, back-to-front diagnostic
renders are NOT guaranteed to match ICR2's rasterizer or sprite perspective.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import sqrt
from pathlib import Path
import json
import shutil
import tempfile

import numpy as np
from PIL import Image, ImageChops, ImageDraw

# Inspector bootstraps the repo's established non-UI CAD Python modules.
from . import inspector as _inspector
from scene import build_scene, load_car_or_model
from sprites import prepare_scene_sprites
from textures import find_model_sunny_palette, find_texture, load_palette
from texture_preview import load_mip, rasterize_polygon, TextureError
from n3_compile import compile_n3_text

CAMERAS = {
    "front": (1, 0, 0.14),
    "rear": (-1, 0, 0.14),
    "left": (0, -1, 0.14),
    "right": (0, 1, 0.14),
    "top": (0, 0, 1),
    "front-left": (1, -1, 0.45),
    "front-right": (1, 1, 0.45),
    "rear-left": (-1, -1, 0.45),
    "rear-right": (-1, 1, 0.45),
}
DEFAULT_CAMERAS = ("front", "rear", "left", "right", "top",
                   "front-left", "rear-right")
BACKDROP = (246, 248, 251)
MAX_DIMENSION = 1600
MAX_POLYGONS = 60000


def _unit(vec):
    mag = sqrt(sum(v*v for v in vec))
    if mag < 1e-9:
        raise ValueError("Zero-length camera vector")
    return tuple(v/mag for v in vec)


def _cross(a, b):
    return (a[1]*b[2]-a[2]*b[1],
            a[2]*b[0]-a[0]*b[2],
            a[0]*b[1]-a[1]*b[0])


def _dot(a, b):
    return sum(a[i]*b[i] for i in range(3))


@dataclass(frozen=True)
class CameraFrame:
    eye_dir: tuple[float, float, float]
    right: tuple[float, float, float]
    up: tuple[float, float, float]
    origin: tuple[float, float, float]
    scale: float
    width: int
    height: int

    def project(self, point):
        rel = tuple(point[j] - self.origin[j] for j in range(3))
        return (self.width/2 + self.scale*_dot(rel, self.right),
                self.height/2 - self.scale*_dot(rel, self.up))


def _frame(name, scenes, width, height, margin=35):
    if name not in CAMERAS:
        raise ValueError(f"Unknown camera {name!r}. Options: {', '.join(CAMERAS)}")
    eye_dir = _unit(CAMERAS[name])
    up_hint = (0, 1, 0) if name == "top" else (0, 0, 1)
    right = _unit(_cross(up_hint, eye_dir))
    up = _unit(_cross(eye_dir, right))
    points = [p for s in scenes for p in s["points"]]
    if not points:
        raise ValueError("No geometry or resolvable PMP sprites to preview")
    lows = [min(p[i] for p in points) for i in range(3)]
    highs = [max(p[i] for p in points) for i in range(3)]
    center = tuple((lo+hi)/2 for lo, hi in zip(lows, highs))
    # Use the combined AABB, not the first model's bounds: before/after
    # always have identical framing even when a component is moved.
    corners = [(x, y, z) for x in (lows[0], highs[0])
               for y in (lows[1], highs[1])
               for z in (lows[2], highs[2])]
    proj = [( _dot(tuple(p[i]-center[i] for i in range(3)), right),
              _dot(tuple(p[i]-center[i] for i in range(3)), up))
            for p in corners]
    xspan = max(p[0] for p in proj)-min(p[0] for p in proj)
    yspan = max(p[1] for p in proj)-min(p[1] for p in proj)
    scale = min((width-2*margin)/max(xspan,1),
                (height-2*margin)/max(yspan,1))
    return CameraFrame(eye_dir, right, up, center, scale, width, height)


def _asset_palette(path, override):
    from textures import load_palette
    if override is not None:
        selected = Path(override)
        if not selected.is_file():
            raise FileNotFoundError(selected)
    else:
        selected = (find_model_sunny_palette(path) or
                    Path(__file__).resolve().parents[1] /
                    "icr2_3do_cad" / "gamepal.pcx")
    return load_palette(selected), str(selected.resolve())


def _load_scene(path, *, objects_folder=None, texture_folder=None,
                appearance=None, palette_file=None):
    from car_appearance import read_car_appearance
    from three_do import Model
    path = Path(path)
    if path.suffix.casefold() not in (".3d", ".3do") or not path.is_file():
        raise ValueError("Preview input must be an existing .3D or .3do")
    if path.suffix.casefold() == ".3d":
        model, _ = compile_n3_text(
            path.read_text(encoding="utf-8-sig"), path, associate_planes=False)
        app = read_car_appearance(Path(appearance)) if appearance else None
        scene = build_scene(model, objects_folder=objects_folder, appearance=app)
    elif appearance:
        model = Model(path, associate_planes=False)
        model, scene, _ = load_car_or_model(
            path, existing_model=model, objects_folder=objects_folder,
            appearance_override=read_car_appearance(Path(appearance)))
    else:
        model, scene, _ = load_car_or_model(path, objects_folder=objects_folder)
    palette, palette_path = _asset_palette(path, palette_file)
    sprites = prepare_scene_sprites(
        scene, objects_folder=objects_folder, texture_folder=texture_folder)
    points = [
        tuple(float(v) for v in vertex.xyz)
        for vertex in scene.geometry.vertices.values()
    ]
    points.extend(sprites.bounds_points)
    if not points:
        raise ValueError("Cannot preview an empty model")
    if sum(len(inst.model.polygons) for inst in scene.instances) > MAX_POLYGONS:
        raise ValueError(f"Preview exceeds {MAX_POLYGONS} polygons")
    return {"path": path, "model": model, "scene": scene,
            "palette": palette, "palette_path": palette_path,
            "sprites": sprites, "points": points,
            "texture_folder": texture_folder}


def _events(scene, frame, *, bsp_mode="original"):
    """Reproduce CAD's existing per-instance BSP order incl. child insertion."""
    events_out, stats = [], {"polygons": 0, "sprite_events": 0,
                             "tested_planes": 0, "culled_nodes": 0}
    diameter = max((max(p[i] for p in scene.geometry.vertices.values()
                        for p in [p.xyz]) -
                    min(p[i] for p in scene.geometry.vertices.values()
                        for p in [p.xyz]))
                   for i in range(3)) if scene.geometry.vertices else 1
    eye = tuple(frame.origin[i] + frame.eye_dir[i]*max(1000, diameter*10)
                for i in range(3))
    def walk(instance_id, ancestors):
        if instance_id in ancestors:
            raise ValueError("Recursive 3DO child graph")
        inst = scene.instances[instance_id]
        local_eye = inst.transform.inverse_point(eye)
        matrix = inst.transform.matrix
        local_direction = tuple(
            sum(matrix[j][i]*frame.eye_dir[j] for j in range(3))
            for i in range(3))
        events = []
        _, node_stats, _ = inst.model.switched_polygons(
            "auto", local_eye, bsp_mode, events=events,
            view_direction=local_direction)
        stats["tested_planes"] += node_stats["tested_planes"]
        stats["culled_nodes"] += node_stats["culled_nodes"]
        for event in events:
            kind, off = event[:2]
            if kind == "polygon":
                if (instance_id, off) in scene.polygon_lookup:
                    events_out.append(("polygon", instance_id, off))
                    stats["polygons"] += 1
            elif kind == "pmp":
                events_out.append(("sprite", instance_id, off))
                stats["sprite_events"] += 1
            elif kind in ("dynamic", "external"):
                child = scene.links.get((instance_id, kind, off))
                if child is not None:
                    walk(child, ancestors | {instance_id})
    walk(0, set())
    return events_out, stats


def _render_camera(data, frame, *, bsp_mode="original", textures=True,
                   edge_lines=False):
    scene = data["scene"]
    sprites = data["sprites"]
    palette = data["palette"]
    img = Image.new("RGB", (frame.width, frame.height), BACKDROP)
    draw = ImageDraw.Draw(img)
    events, stats = _events(scene, frame, bsp_mode=bsp_mode)
    warnings = list(scene.warnings) + list(sprites.warnings)
    palette_rgba = np.concatenate(
        (palette, np.full((256,1), 255, dtype=np.uint8)), axis=1)
    mip_cache = {}
    missing_textures = set()
    drawn_sprites = 0
    drawn_textures = 0
    for kind, instance_id, offset in events:
        if kind == "sprite":
            sprite = sprites.placements.get((instance_id, offset))
            if sprite is None:
                continue
            indices = sprites.images[sprite.image_key]
            color = palette_rgba[indices[:,:,0]].copy()
            color[:,:,3] = indices[:,:,1]
            sprite_image = Image.fromarray(color, "RGBA")
            pixel_size = sprite.normalized_pixel_size*frame.scale
            width = max(1, round(indices.shape[1]*pixel_size))
            height = max(1, round(indices.shape[0]*pixel_size))
            if width > 3*frame.width or height > 3*frame.height:
                warnings.append(f"Sprite at {instance_id}:{offset} exceeds canvas safety budget")
                continue
            box = sprite.bounds
            cx, cy = frame.project(sprite.xyz)
            x = round(cx + (box[0] - 128)*pixel_size)
            y = round(cy + (box[1] - 127)*pixel_size)
            if width > 0 and height > 0:
                sprite_image = sprite_image.resize(
                    (width,height), Image.Resampling.NEAREST)
                img.paste(sprite_image, (x,y), sprite_image)
                drawn_sprites += 1
            continue
        inst = scene.instances[instance_id]
        poly = inst.model.polygons[offset]
        face = [inst.model.vertices[r] for r in poly.unique_refs]
        world = [inst.transform.apply(v.xyz) for v in face]
        projected = [frame.project(p) for p in world]
        if len(projected) < 3:
            continue
        flat_id = scene.polygon_lookup[(instance_id,offset)]
        color_index = scene.geometry.polygons[flat_id].color
        material = scene.geometry.polygon_materials.get(flat_id)
        textured = False
        if textures and poly.kind == 2 and material and all(v.uv for v in face):
            source = scene.geometry.polygon_sources.get(flat_id, inst.model.path)
            key = (str(source), material.casefold())
            if key not in mip_cache:
                location = find_texture(
                    material, Path(source), texture_folder=data["texture_folder"])
                if location is None:
                    mip_cache[key] = None
                    missing_textures.add(material)
                else:
                    try:
                        mip_cache[key] = load_mip(location)[0]
                    except (OSError, TextureError, ValueError) as exc:
                        missing_textures.add(f"{material}: {exc}")
                        mip_cache[key] = None
            texture = mip_cache[key]
            if texture is not None:
                tex_vertices = [(p[0],p[1],1.0,float(v.uv[0]),float(v.uv[1]))
                                for p,v in zip(projected,face)]
                rendered = rasterize_polygon(
                    texture, palette, tex_vertices,
                    (frame.width,frame.height), perspective=False)
                if rendered is not None:
                    tile,x,y = rendered
                    img.paste(tile, (x,y), tile)
                    drawn_textures += 1
                    textured = True
        if not textured:
            color = tuple(int(c) for c in palette[color_index])
            draw.polygon(projected, fill=color)
        if edge_lines:
            draw.line(projected+[projected[0]], fill=(51, 61, 73), width=1)
    warnings.extend("Missing/unreadable MIP: "+n for n in sorted(missing_textures))
    stats.update({"rendered_sprites": drawn_sprites,
                  "textured_polygons": drawn_textures,
                  "missing_textures": sorted(missing_textures)})
    return img, stats, sorted(set(warnings))


def _validate_settings(cameras, width, height):
    if not cameras or len(cameras) != len(set(cameras)):
        raise ValueError("Camera names must be nonempty and unique")
    bad = set(cameras)-set(CAMERAS)
    if bad:
        raise ValueError("Invalid camera(s): "+", ".join(sorted(bad)))
    for value in (width,height):
        if not isinstance(value,int) or not 64<=value<=MAX_DIMENSION:
            raise ValueError(f"Dimensions must be integers in 64..{MAX_DIMENSION}")


def _json(path, obj):
    Path(path).write_text(
        json.dumps(obj, indent=2, sort_keys=True, allow_nan=False)+"\n",
        encoding="utf-8")


def _prepare_output(output, sources):
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    for source in sources:
        if source.resolve() == output.resolve() or source.resolve() in output.resolve().parents:
            raise ValueError("Output may not be a source or ancestor of the source")
    output.parent.mkdir(parents=True, exist_ok=True)
    return output, Path(tempfile.mkdtemp(prefix=".3do-preview-", dir=output.parent))


def _publish(temp, output):
    if output.exists():
        raise FileExistsError(f"Output created concurrently: {output}")
    temp.rename(output)


def render_previews(path, output, *, cameras=DEFAULT_CAMERAS, width=700,
                    height=500, objects_folder=None, texture_folder=None,
                    palette_file=None, appearance=None, bsp_mode="original",
                    textures=True, edge_lines=False, strict_assets=False):
    """Render fixed orthographic diagnostic views; never touch game assets."""
    cameras = tuple(cameras)
    _validate_settings(cameras,width,height)
    data = _load_scene(
        path, objects_folder=objects_folder, texture_folder=texture_folder,
        palette_file=palette_file, appearance=appearance)
    output,temp = _prepare_output(Path(output), [Path(path)])
    try:
        files, reports = {}, {}
        warnings = set()
        for camera in cameras:
            frame = _frame(camera,[data],width,height)
            image,stats,issues = _render_camera(
                data, frame, bsp_mode=bsp_mode,
                textures=textures, edge_lines=edge_lines)
            dest = temp/(camera+".png")
            image.save(dest)
            files[camera] = {"file":dest.name,
                             "sha256":sha256(dest.read_bytes()).hexdigest()}
            reports[camera] = stats
            warnings.update(issues)
        if strict_assets and warnings:
            raise ValueError("Incomplete visual assets: " + "; ".join(sorted(warnings)))
        report = {"schema":"icr2.visual-preview.v1",
                  "input":str(Path(path).resolve()),
                  "input_sha256":sha256(Path(path).read_bytes()).hexdigest(),
                  "cameras":list(cameras), "size":[width,height],
                  "orthographic":True, "bsp_mode":bsp_mode,
                  "source_palette":data["palette_path"],
                  "views":files, "statistics":reports,
                  "warnings":sorted(warnings),
                  "caveats":[
                      "Diagnostic painter renderer; not exact Papyrus rasterization.",
                      "Orthographic PMP billboards use CAD's source-canvas anchor and size.",
                      "No depth buffer: FACE/BSP/LIST traverse in compiled draw order.",
                      "Absent texture or PMP assets may make previews incomplete.",
                  ]}
        _json(temp/"preview.json",report)
        _publish(temp,output)
        return report
    finally:
        if temp.exists():
            shutil.rmtree(temp)


def compare_previews(before, after, output, *, cameras=DEFAULT_CAMERAS,
                     width=700, height=500, objects_folder=None,
                     texture_folder=None, palette_file=None, appearance=None,
                     bsp_mode="original", textures=True, tolerance=0,
                     max_diff_ratio=None, strict_assets=False):
    """Shared framing and pixel-by-pixel compare; return measured mismatch."""
    cameras = tuple(cameras)
    _validate_settings(cameras,width,height)
    if not isinstance(tolerance,int) or not 0<=tolerance<=255:
        raise ValueError("Tolerance must be integer 0..255")
    if max_diff_ratio is not None and not 0<=max_diff_ratio<=1:
        raise ValueError("max_diff_ratio must be in [0,1]")
    first = _load_scene(
        before, objects_folder=objects_folder, texture_folder=texture_folder,
        palette_file=palette_file, appearance=appearance)
    # Compare geometry/material output with one exact palette. A candidate
    # folder may carry a different local SUNNY.PCX; never let that silently
    # masquerade as a geometry/painter regression. An explicit --palette
    # overrides the shared baseline palette for both sides.
    second = _load_scene(
        after, objects_folder=objects_folder, texture_folder=texture_folder,
        palette_file=palette_file or first["palette_path"],
        appearance=appearance)
    output,temp = _prepare_output(Path(output), [Path(before),Path(after)])
    try:
        reports, warnings, greatest = {}, set(), 0.0
        for name in cameras:
            frame = _frame(name,[first,second],width,height)
            a,astats,awarn = _render_camera(
                first,frame,bsp_mode=bsp_mode,textures=textures)
            b,bstats,bwarn = _render_camera(
                second,frame,bsp_mode=bsp_mode,textures=textures)
            a.save(temp/(name+"-before.png"))
            b.save(temp/(name+"-after.png"))
            difference = np.asarray(ImageChops.difference(a,b),dtype=np.uint8)
            changed = np.any(difference > tolerance,axis=2)
            count = int(np.count_nonzero(changed))
            total = width*height
            ratio = count/total
            greatest = max(greatest,ratio)
            heat = np.zeros((height,width,3),dtype=np.uint8)
            heat[changed] = [255, 30, 80]
            heat_im = Image.fromarray(heat,"RGB")
            heat_im.save(temp/(name+"-diff.png"))
            combined = Image.new("RGB",(width*3,height), BACKDROP)
            for i,side in enumerate((a,b,heat_im)):
                combined.paste(side,(i*width,0))
            combined.save(temp/(name+"-comparison.png"))
            reports[name] = {
                "changed_pixels":count, "total_pixels":total,
                "changed_fraction":ratio,
                "mean_absolute_channel_delta":
                    float(np.mean(difference.astype(np.float32))),
                "before":name+"-before.png","after":name+"-after.png",
                "diff":name+"-diff.png",
                "side_by_side":name+"-comparison.png",
                "before_stats":astats,"after_stats":bstats,
            }
            warnings.update(awarn)
            warnings.update(bwarn)
        if strict_assets and warnings:
            raise ValueError("Incomplete visual assets: "+"; ".join(sorted(warnings)))
        report = {
            "schema":"icr2.visual-regression.v1",
            "before":str(Path(before).resolve()),
            "after":str(Path(after).resolve()),
            "before_sha256":sha256(Path(before).read_bytes()).hexdigest(),
            "after_sha256":sha256(Path(after).read_bytes()).hexdigest(),
            "cameras":list(cameras),"size":[width,height],
            "orthographic":True,"bsp_mode":bsp_mode,
            "source_palette":first["palette_path"],
            "tolerance":tolerance, "maximum_changed_fraction":greatest,
            "threshold":max_diff_ratio,
            "threshold_passed":max_diff_ratio is None or greatest <= max_diff_ratio,
            "views":reports,"warnings":sorted(warnings),
            "note":"Same camera, union bounding box, fixed palette and fixed resolution. "
                   "Pixel changes identify visual differences, not their cause; "
                   "in-game rendering is not reproduced.",
        }
        _json(temp/"comparison.json",report)
        _publish(temp,output)
        return report
    finally:
        if temp.exists():
            shutil.rmtree(temp)
