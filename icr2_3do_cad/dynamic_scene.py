"""Read-only external 3DO scene traversal for Papyrus DYNAMIC placements.

Editor changes only the parent model's DYNAMIC translation and rotation values.
External files are never written.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import math

from three_do import Model, FormatError

ANGLE_SCALE=math.pi/(1 << 31)  # signed 32-bit Papyrus angle: 2^31 == 180 deg

@dataclass(frozen=True)
class Transform:
    matrix: tuple[tuple[float,float,float], ...] = ((1.,0.,0.),(0.,1.,0.),(0.,0.,1.))
    translation: tuple[float,float,float] = (0.,0.,0.)

    def apply(self, vec):
        return tuple(self.translation[i]+sum(self.matrix[i][j]*vec[j] for j in range(3)) for i in range(3))

    def inverse_point(self, point):
        rel=[point[i]-self.translation[i] for i in range(3)]
        return tuple(sum(self.matrix[j][i]*rel[j] for j in range(3)) for i in range(3))

    def compose(self, other):
        """Local `other` transform inside this parent transform."""
        m=tuple(tuple(sum(self.matrix[i][k]*other.matrix[k][j] for k in range(3))
                        for j in range(3)) for i in range(3))
        return Transform(m,self.apply(other.translation))


def placement_transform(placement):
    """Rotation order matches DYNAMIC z, y, x encoding; applied Z then Y then X.

    On stock wheels only Z=0/180 is used; Y/X are available for edited objects.
    """
    z,y,x=[v*ANGLE_SCALE for v in placement.angles]
    cz,sz=math.cos(z),math.sin(z)
    cy,sy=math.cos(y),math.sin(y)
    cx,sx=math.cos(x),math.sin(x)
    # R = Rx * Ry * Rz: first Z, then Y, then X
    rz=((cz,-sz,0.),(sz,cz,0.),(0.,0.,1.))
    ry=((cy,0.,sy),(0.,1.,0.),(-sy,0.,cy))
    rx=((1.,0.,0.),(0.,cx,-sx),(0.,sx,cx))
    def mul(a,b):
        return tuple(tuple(sum(a[i][k]*b[k][j] for k in range(3)) for j in range(3)) for i in range(3))
    return Transform(mul(rx,mul(ry,rz)),tuple(float(v) for v in placement.xyz))


def degrees_to_papyrus(degrees):
    degrees=float(degrees)
    if not math.isfinite(degrees):
        raise ValueError('Rotation must be a finite number')
    # Valid int32 supports +180 by the equivalent -180 representation.
    value=int(round(((degrees+180)%360-180)*(1<<31)/180))
    return value


def papyrus_to_degrees(value):
    return value*180/(1<<31)


class ExternalResolver:
    def __init__(self, directory=None):
        self.directory=Path(directory) if directory else None
        self._cache={}
        self.missing=set()

    def choose_directory(self, directory):
        self.directory=Path(directory) if directory else None
        self._cache.clear()
        self.missing.clear()

    def find(self, name, parent_path, extra_dirs=(), extension='.3do'):
        name=Path(name).stem.casefold()+extension
        parent=Path(parent_path).parent
        dirs=[parent,self.directory,*extra_dirs,
              parent/'3do', parent/'obj',parent.parent/'obj',parent.parent/'cars',parent.parent]
        for directory in dirs:
            if directory is None:continue
            folder=Path(directory)
            if not folder.is_dir():continue
            key=(str(folder.resolve()),name)
            if key not in self._cache:
                # Exact lookup first; DOS filenames are case insensitive.
                match=folder/name
                if not match.is_file():
                    match=next((x for x in folder.iterdir()
                       if x.is_file() and x.name.casefold()==name),None)
                self._cache[key]=match
            if self._cache[key] is not None:
                return self._cache[key]
        self.missing.add(name)
        return None


@dataclass
class RenderSprite:
    source: Model
    offset: int
    transform: Transform
    placement: int | None = None


@dataclass
class RenderFace:
    source: Model
    offset: int
    transform: Transform
    placement: int | None = None   # top-level DYNAMIC offset (selection key)
    texture_override: str | None = None  # inherited external MATERIAL MIP


def gather_faces(parent, distance, camera, mode, resolver,
                 *, cache=None, max_depth=4, extra_dirs=()):
    """Yield polygons across parent and DYNAMIC children in painter's order.

    Both LIST and BSP traversal order are inherited at the placement site.
    Child BSP tests run in child-local coordinates. Any missing submodel is
    reported but does not abort rendering the rest of the parent.
    """
    faces=[]
    failures={}
    loaded=cache if cache is not None else {}
    def walk(model,transform,root_placement,depth,ancestry,texture_override=None):
        events=[]
        model.switched_polygons(distance,transform.inverse_point(camera),mode,events=events)
        for event in events:
            kind,ref=event[:2]
            if kind=='polygon':
                faces.append(RenderFace(model,ref,transform,root_placement,
                                        model.polygon_materials.get(ref,texture_override)))
                continue
            if kind=='pmp':
                faces.append(RenderSprite(model,ref,transform,root_placement))
                continue
            if kind=='dynamic':
                obj=model.dynamics[ref]
                name=obj.name
                nested_transform=transform.compose(placement_transform(obj))
                inherited_texture=texture_override
            elif kind=='external':
                # Negative object index in a MATERIAL/LIST/etc. child pointer.
                # This is a zero-transform external insertion, not DYNAMIC.
                if not (1 <= -ref <= len(model.external_names)):
                    failures[ref]=f'Invalid external pointer {ref}'
                    continue
                name=model.external_names[-ref-1]
                nested_transform=transform
                inherited_texture=event[2] or texture_override
            else:
                continue
            location=resolver.find(name,model.path,extra_dirs)
            if location is None:
                failures[ref]=f'{name}.3do not found'
                continue
            key=location.resolve()
            if key in ancestry:
                failures[ref]=f'Circular external 3DO reference to {location.name}'
                continue
            if depth>=max_depth:
                failures[ref]=f'Maximum DYNAMIC nesting depth {max_depth} reached'
                continue
            try:
                if key not in loaded:
                    loaded[key]=Model(location)
                child=loaded[key]
                walk(child,nested_transform,
                     ref if (kind=='dynamic' and root_placement is None) else root_placement,
                     depth+1,ancestry|{key},inherited_texture)
            except (OSError,ValueError,FormatError) as exc:
                failures[ref]=f'{location.name}: {exc}'
    walk(parent,Transform(),None,0,{parent.path.resolve()})
    return faces,failures
