"""Read-only GPU scene graph for Papyrus DYNAMIC and external 3DO children.

Discover the complete referenced hierarchy once on the worker, and flatten all
instance-transformed geometry into ONE VBO/texture atlas. At draw time expand
the original per-model BSP/RES event stream at each DYNAMIC insertion site;
only the ordered element indices change. No nested asset is ever modified.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from dynamic_scene import ExternalResolver, Transform, placement_transform
from gpu_viewer.car import recolor_table, recolor_index
from gpu_viewer.track_lod import detect_track_section_lods, selected_track_section_lists
from car_appearance import read_car_appearance, locate_base_geometry, AppearanceError
from three_do import Model


@dataclass
class Instance:
    model: Model
    transform: Transform
    depth: int
    ancestry: frozenset
    texture_override: str | None = None
    texture_source: Path | None = None
    recolor_layers: tuple[dict[int, int], ...] = ()


@dataclass
class GPUScene:
    root: Model
    instances: list[Instance]
    links: dict[tuple[int, str, int], int]
    polygon_lookup: dict[tuple[int, int], int]
    geometry: SimpleNamespace
    warnings: tuple[str, ...]
    recolor_pairs: int = 0
    appearance: object | None = None
    track_section_lods: dict | None = None

    @property
    def loaded_instances(self):
        return len(self.instances) - 1


def build_scene(root, *, objects_folder=None, object_overrides=None,
                appearance=None, max_depth=4, max_instances=2000):
    """Resolve instances including inactive LOD/BSP branches (no GL calls).

    Reusing a child 3DO file is cheap: the parsed Model is cached, while each
    DYNAMIC placement receives a distinct transformed instance of its faces.
    """
    resolver = ExternalResolver(objects_folder)
    overrides = {str(name).casefold(): Path(path)
                 for name, path in (object_overrides or {}).items()}
    cache = {}
    root_key = Path(root.path).resolve()
    # The CPU editor treats a standalone driver file as *appearance* over
    # separately opened base geometry, not as a renderable model itself.
    root_recolor = appearance.mapping if appearance is not None else recolor_table(root)
    instances = [Instance(root, Transform(), 0, frozenset((root_key,)),
                          recolor_layers=((root_recolor,) if root_recolor else ()))]
    links = {}
    warnings = []
    for parent_id, instance in enumerate(instances):
        events = []
        instance.model.switched_polygons(None, (0, 0, 0), 'off', events=events)
        for event in events:
            kind, ref = event[:2]
            if kind not in ('dynamic', 'external'):
                continue
            if kind == 'dynamic':
                placement = instance.model.dynamics[ref]
                name = placement.name
                transform = instance.transform.compose(placement_transform(placement))
                texture_override = instance.texture_override
                texture_source = instance.texture_source
            else:
                if not 1 <= -ref <= len(instance.model.external_names):
                    warnings.append(f'Invalid external pointer {ref} in {instance.model.path.name}')
                    continue
                name = instance.model.external_names[-ref - 1]
                transform = instance.transform
                texture_override = event[2] or instance.texture_override
                texture_source = (instance.model.path if event[2]
                                  else instance.texture_source)

            if (parent_id, kind, ref) in links:
                # Original traversal deduplicates each record. Negative child
                # pointers can be reused by distinct MATERIAL wrappers; the
                # source traversal currently cannot distinguish those sites.
                continue
            location = overrides.get(name.casefold())
            if location is not None and not location.is_file():
                warnings.append(f'{name}: override file missing: {location.name}')
                continue
            if location is None:
                location = resolver.find(name, instance.model.path)
            if location is None:
                warnings.append(f'{instance.model.path.name}: missing {name}.3do')
                continue
            key = location.resolve()
            if key in instance.ancestry:
                warnings.append(f'{location.name}: recursive 3DO reference')
                continue
            if instance.depth >= max_depth:
                warnings.append(f'{location.name}: max nesting depth {max_depth} reached')
                continue
            if len(instances) >= max_instances:
                warnings.append(f'Maximum {max_instances} external instances reached')
                continue
            try:
                if key not in cache:
                    cache[key] = Model(location, associate_planes=False)
                child = cache[key]
            except (OSError, ValueError) as exc:
                warnings.append(f'{location.name}: {exc}')
                continue
            child_id = len(instances)
            links[parent_id, kind, ref] = child_id
            local_recolor = recolor_table(child)
            # A driver's RECOLOR belongs to the base car, not its external
            # wheels or helmet. Match the CPU editor's effective_color().
            inherited = (() if appearance is not None and parent_id == 0
                         else instance.recolor_layers)
            layers = inherited + ((local_recolor,) if local_recolor else ())
            instances.append(Instance(
                child, transform, instance.depth+1,
                instance.ancestry | frozenset((key,)), texture_override,
                texture_source, layers))

    vertices = {}
    polygons = {}
    polygon_materials = {}
    polygon_sources = {}
    polygon_lookup = {}
    body_polygons = set()
    next_vertex = 1
    next_polygon = 1
    for instance_id, instance in enumerate(instances):
        remap = {}
        for old, vertex in instance.model.vertices.items():
            remap[old] = next_vertex
            vertices[next_vertex] = SimpleNamespace(
                xyz=instance.transform.apply(vertex.xyz), uv=vertex.uv)
            next_vertex += 1
        for old, polygon in instance.model.polygons.items():
            refs = tuple(remap[r] for r in polygon.unique_refs if r in remap)
            if len(refs) != len(polygon.unique_refs):
                continue
            polygons[next_polygon] = SimpleNamespace(
                unique_refs=refs, kind=polygon.kind,
                color=recolor_index(polygon.color, instance.recolor_layers))
            if instance_id == 0 and polygon.kind == 2:
                body_polygons.add(next_polygon)
            local_material = instance.model.polygon_materials.get(old)
            # The wrapper MIP has priority for BODY only. External wheel
            # materials are independent and must not inherit its paint.
            if instance_id == 0 and appearance is not None and appearance.texture_name:
                name = appearance.texture_name
            else:
                name = local_material or instance.texture_override
            if name:
                polygon_materials[next_polygon] = name
                if instance_id == 0 and appearance is not None and appearance.texture_name:
                    polygon_sources[next_polygon] = appearance.path
                else:
                    polygon_sources[next_polygon] = (
                        instance.model.path if local_material
                        else (instance.texture_source or instance.model.path))
            polygon_lookup[instance_id, old] = next_polygon
            next_polygon += 1
    geometry = SimpleNamespace(
        vertices=vertices, polygons=polygons,
        polygon_materials=polygon_materials,
        polygon_sources=polygon_sources,
        body_polygons=frozenset(body_polygons))
    return GPUScene(root, instances, links, polygon_lookup,
                    geometry, tuple(dict.fromkeys(warnings)),
                    len(root_recolor), appearance,
                    track_section_lods=detect_track_section_lods(root))


def ordered_scene_indices(scene, mesh, camera, distance=0.0, *,
                          view_direction=None, with_sprites=False,
                          track_detail=None, bsp_mode='original'):
    """Expand BSP/DYNAMIC painter order with optional PMP insertion markers.

    Default three-value result remains compatible with existing callers.
    With sprite events return a fourth item: (EBO element position,
    (instance_id, sprite record offset)) for each active PMP/PMP2, preserving
    its location between polygons rather than drawing sprites on top.
    """
    overrides = (selected_track_section_lists(
        scene.track_section_lods, track_detail, model=scene.root)
        if track_detail is not None and scene.track_section_lods else None)
    spans = []
    sprite_events = []
    element_count = 0
    root_visible = set()
    stats = dict(mesh_polygons=0, triangles=0, tested_planes=0,
                 culled_nodes=0, lod_selections=0, excluded_branches=0,
                 pmp_sprites=0, instances_visited=0)
    def walk(instance_id):
        nonlocal element_count
        instance = scene.instances[instance_id]
        local_eye = instance.transform.inverse_point(camera)
        local_direction = None
        if view_direction is not None:
            matrix = instance.transform.matrix
            local_direction = tuple(
                sum(matrix[j][i] * view_direction[j] for j in range(3))
                for i in range(3))
        events = []
        _, summary, lods = instance.model.switched_polygons(
            distance, local_eye, bsp_mode, events=events,
            view_direction=local_direction,
            list_overrides=overrides if instance_id == 0 else None)
        stats['instances_visited'] += 1
        stats['tested_planes'] += summary['tested_planes']
        stats['culled_nodes'] += summary['culled_nodes']
        stats['excluded_branches'] += summary['excluded_branches']
        stats['lod_selections'] += len(lods)
        for event in events:
            kind, old = event[:2]
            if kind == 'polygon':
                poly = scene.polygon_lookup.get((instance_id, old))
                if poly is None:
                    continue
                if instance_id == 0:
                    root_visible.add(old)
                span = mesh.polygon_ranges.get(poly)
                if span is None:
                    continue
                spans.append(span)
                element_count += span[1]
                stats['mesh_polygons'] += 1
            elif kind == 'pmp':
                resources = getattr(scene, "sprite_resources", None)
                if (resources is not None and
                        (instance_id, old) in resources.placements):
                    sprite_events.append((element_count, (instance_id, old)))
                    stats['pmp_sprites'] += 1
            elif kind in ('dynamic', 'external'):
                child = scene.links.get((instance_id, kind, old))
                if child is not None:
                    walk(child)
    walk(0)
    indices = np.empty(sum(count for _, count in spans), dtype=np.uint32)
    cursor = 0
    for start, count in spans:
        indices[cursor:cursor+count] = np.arange(start, start+count,
                                                 dtype=np.uint32)
        cursor += count
    stats['triangles'] = cursor // 3
    result = (indices, frozenset(root_visible), stats)
    return (*result, tuple(sprite_events)) if with_sprites else result


def load_car_or_model(path, *, existing_model=None, objects_folder=None,
                      object_overrides=None, fixtures_folder=None):
    """Mirror CPU editor's read_car_appearance + locate_base_geometry flow.

    Individual car wrappers point their MATERIAL to a RECOLOR at offset 0;
    they DO NOT have a traversable child pointer to the shared geometry.
    Return (model, scene, appearance) while keeping source files immutable.
    If the base shape is unavailable, preserve the wrapper and a clear
    warning so the UI can offer 'Assign carshape 3DO…'.
    """
    path = Path(path)
    if path.suffix.casefold() != '.3do':
        raise ValueError('Expected a 3DO model')
    try:
        appearance = read_car_appearance(path)
    except AppearanceError:
        appearance = None
    if appearance is None:
        if existing_model is not None and existing_model.path.resolve() == path.resolve():
            model = existing_model
        else:
            model = Model(path, associate_planes=False)
        return model, build_scene(model, objects_folder=objects_folder,
                                  object_overrides=object_overrides), None

    overrides = {str(k).casefold(): Path(v) for k,v in (object_overrides or {}).items()}
    wanted = appearance.geometry_name
    chosen = overrides.get(wanted.casefold())
    warnings = []
    if chosen is not None and not chosen.is_file():
        warnings.append(f'Assigned carshape is missing: {chosen}')
        chosen = None
    if chosen is None:
        extra = [d for d in (objects_folder, fixtures_folder) if d is not None]
        chosen = locate_base_geometry(appearance, extra_dirs=extra)
        if chosen is None and wanted:
            chosen = ExternalResolver(objects_folder).find(wanted, appearance.path)
    if chosen is not None:
        if existing_model is not None and existing_model.path.resolve() == chosen.resolve():
            model = existing_model
        else:
            model = Model(chosen, associate_planes=False)
        scene = build_scene(model, objects_folder=objects_folder,
                            object_overrides=object_overrides,
                            appearance=appearance)
    else:
        model = Model(path, associate_planes=False)
        scene = build_scene(model, objects_folder=objects_folder,
                            object_overrides=object_overrides)
        scene.appearance = appearance
        scene.recolor_pairs = len(appearance.mapping)
        warnings.append(
            f'Carshape {wanted}.3do not found; choose Assign carshape 3DO')
    if warnings:
        scene.warnings = tuple(dict.fromkeys((*scene.warnings, *warnings)))
    return model, scene, appearance
