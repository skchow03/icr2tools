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
from three_do import Model


@dataclass
class Instance:
    model: Model
    transform: Transform
    depth: int
    ancestry: frozenset
    texture_override: str | None = None


@dataclass
class GPUScene:
    root: Model
    instances: list[Instance]
    links: dict[tuple[int, str, int], int]
    polygon_lookup: dict[tuple[int, int], int]
    geometry: SimpleNamespace
    warnings: tuple[str, ...]

    @property
    def loaded_instances(self):
        return len(self.instances) - 1


def build_scene(root, *, objects_folder=None, max_depth=4, max_instances=2000):
    """Resolve instances including inactive LOD/BSP branches (no GL calls).

    Reusing a child 3DO file is cheap: the parsed Model is cached, while each
    DYNAMIC placement receives a distinct transformed instance of its faces.
    """
    resolver = ExternalResolver(objects_folder)
    cache = {}
    root_key = Path(root.path).resolve()
    instances = [Instance(root, Transform(), 0, frozenset((root_key,)))]
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
            else:
                if not 1 <= -ref <= len(instance.model.external_names):
                    warnings.append(f'Invalid external pointer {ref} in {instance.model.path.name}')
                    continue
                name = instance.model.external_names[-ref - 1]
                transform = instance.transform
                texture_override = event[2] or instance.texture_override

            if (parent_id, kind, ref) in links:
                # Original traversal deduplicates each record. Negative child
                # pointers can be reused by distinct MATERIAL wrappers; the
                # source traversal currently cannot distinguish those sites.
                continue
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
            instances.append(Instance(
                child, transform, instance.depth+1,
                instance.ancestry | frozenset((key,)), texture_override))

    vertices = {}
    polygons = {}
    polygon_materials = {}
    polygon_sources = {}
    polygon_lookup = {}
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
                unique_refs=refs, kind=polygon.kind, color=polygon.color)
            name = instance.model.polygon_materials.get(old) or instance.texture_override
            if name:
                polygon_materials[next_polygon] = name
                polygon_sources[next_polygon] = instance.model.path
            polygon_lookup[instance_id, old] = next_polygon
            next_polygon += 1
    geometry = SimpleNamespace(
        vertices=vertices, polygons=polygons,
        polygon_materials=polygon_materials,
        polygon_sources=polygon_sources)
    return GPUScene(root, instances, links, polygon_lookup,
                    geometry, tuple(dict.fromkeys(warnings)))


def ordered_scene_indices(scene, mesh, camera, distance=0.0, *,
                          view_direction=None):
    """Expand nested painter events, evaluating child BSP in local coordinates.

    Returns indices, root-only visible polygon offsets (for the inspector),
    and aggregate traversal statistics.
    """
    spans = []
    root_visible = set()
    stats = dict(mesh_polygons=0, triangles=0, tested_planes=0,
                 culled_nodes=0, lod_selections=0, excluded_branches=0,
                 instances_visited=0)
    def walk(instance_id):
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
            distance, local_eye, 'original', events=events,
            view_direction=local_direction)
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
                span = mesh.polygon_ranges.get(poly)
                if span is None:
                    continue
                spans.append(span)
                stats['mesh_polygons'] += 1
                if instance_id == 0:
                    root_visible.add(old)
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
    return indices, frozenset(root_visible), stats
