"""Construct valid Papyrus N3 FACE/BSP plane operands from binary planes.

Adapted from the integer Diophantine construction in skchow03/3do23d
(plane.py:get_points_on_plane), with signed-32-bit coordinate validation.

Prefer actual polygon vertex references when they define the SAME oriented
plane; otherwise synthesize three exact on-plane integer coordinates.
Never emit the internal five-number binary coefficient form as N3 source.
"""
from __future__ import annotations

from itertools import combinations
from math import gcd

from three_do import FormatError, INT32_LO, INT32_HI


def _cross(a,b):
    return (a[1]*b[2]-a[2]*b[1],
            a[2]*b[0]-a[0]*b[2],
            a[0]*b[1]-a[1]*b[0])


def _dot(a,b):
    return sum(x*y for x,y in zip(a,b))


def _egcd(a,b):
    old_r,r=abs(a),abs(b)
    old_s,s=1,0
    old_t,t=0,1
    while r:
        q=old_r//r
        old_r,r=r,old_r-q*r
        old_s,s=s,old_s-q*s
        old_t,t=t,old_t-q*t
    return old_r, old_s if a>=0 else -old_s, old_t if b>=0 else -old_t


def _primitive(v):
    g=gcd(gcd(abs(v[0]),abs(v[1])),abs(v[2]))
    return tuple(x//g for x in v) if g else v


def oriented_plane_matches(equation,points):
    """Exact same oriented geometric plane, allowing coefficient scaling."""
    a,b,c,d=equation
    p,q,r=points
    u=tuple(q[i]-p[i] for i in range(3))
    v=tuple(r[i]-p[i] for i in range(3))
    normal=_cross(u,v)
    if normal==(0,0,0) or (a,b,c)==(0,0,0):
        return False
    if _dot(normal,(a,b,c))<=0:
        return False
    # All points lie on the original plane, and normals are parallel.
    return (_cross(normal,(a,b,c))==(0,0,0)
            and all(a*x+b*y+c*z+d==0 for x,y,z in points))


def _plane_key(equation):
    a,b,c,d=equation
    g=gcd(gcd(gcd(abs(a),abs(b)),abs(c)),abs(d))
    return (a//g,b//g,c//g,d//g) if g else equation


def _vertex_triplet(model,equation):
    """Cache the oriented polygon-plane index once per model."""
    lookup=getattr(model,"_n3_plane_triplet_index",None)
    if lookup is None:
        lookup={}
        vertices=model.vertices
        for poly in model.polygons.values():
            refs=list(dict.fromkeys(poly.unique_refs))
            if len(refs)<3:continue
            if len(refs)>18:
                refs=refs[:9]+refs[-9:]
            for x,y,z in combinations(refs,3):
                if x not in vertices or y not in vertices or z not in vertices:
                    continue
                p,q,r=(vertices[t].xyz for t in (x,y,z))
                u=tuple(q[i]-p[i] for i in range(3))
                v=tuple(r[i]-p[i] for i in range(3))
                a,b,c=_cross(u,v)
                if (a,b,c)==(0,0,0):continue
                d=-_dot((a,b,c),p)
                lookup.setdefault(_plane_key((a,b,c,d)),(x,y,z))
                lookup.setdefault(_plane_key((-a,-b,-c,-d)),(x,z,y))
        model._n3_plane_triplet_index=lookup
    return lookup.get(_plane_key(equation))


def _base_point(equation):
    a,b,c,d=equation
    if (a,b,c)==(0,0,0):
        raise FormatError("Cannot export FACE/BSP plane with a zero normal")
    g=gcd(gcd(abs(a),abs(b)),abs(c))
    if d%g:
        raise FormatError(
            f"No exact integer-coordinate N3 plane exists for {equation}: "
            f"gcd(A,B,C)={g} does not divide -D. "
            "Choose/edit a valid three-point BSP plane explicitly.")
    # Prefer a compact solution with one coordinate fixed to zero.
    choices=[]
    abc=(a,b,c)
    target=-d
    for i,j in ((0,1),(0,2),(1,2)):
        gg,xx,yy=_egcd(abc[i],abc[j])
        if not gg or target%gg:continue
        scale=target//gg
        x,y=xx*scale,yy*scale
        dx=abc[j]//gg
        dy=-abc[i]//gg
        values=set((0,))
        if dx:
            k=round(-x/dx)
            values.update((k-1,k,k+1))
        if dy:
            k=round(-y/dy)
            values.update((k-1,k,k+1))
        for k in values:
            v=[0,0,0]
            v[i],v[j]=x+k*dx,y+k*dy
            if all(INT32_LO<=q<=INT32_HI for q in v):
                choices.append(tuple(v))
    if choices:
        return min(choices,key=lambda p:(max(map(abs,p)),sum(map(abs,p))))
    # General 3-variable Bezout construction, from 3do23d/plane.py.
    gg,xa,ya=_egcd(a,b)
    whole,pair,zc=_egcd(gg,c)
    scale=-d//whole
    p=(xa*pair*scale,ya*pair*scale,zc*scale)
    if all(INT32_LO<=v<=INT32_HI for v in p):
        return p
    raise FormatError(
        f"No bounded integer point found for FACE/BSP equation {equation}; "
        "cannot safely export as three signed-32-bit N3 coordinates.")


def get_points_on_plane(equation):
    """Return three noncollinear, in-range integer points on an oriented plane.

    No approximate fallback: if exact N3 geometry is impossible, report why.
    """
    a,b,c,d=equation
    p=_base_point(equation)
    n=(a,b,c)
    directions=[]
    for axis in ((1,0,0),(0,1,0),(0,0,1)):
        tangent=_primitive(_cross(n,axis))
        if tangent!=(0,0,0) and tangent not in directions:
            directions.append(tangent)
    candidates=[]
    for i,u in enumerate(directions):
        for v in directions[i+1:]:
            if _cross(u,v)==(0,0,0):continue
            for su in (1,-1):
                for sv in (1,-1):
                    q=tuple(p[k]+su*u[k] for k in range(3))
                    r=tuple(p[k]+sv*v[k] for k in range(3))
                    if not all(INT32_LO<=x<=INT32_HI for point in (q,r) for x in point):
                        continue
                    if oriented_plane_matches(equation,(p,q,r)):
                        candidates.append((p,q,r))
    if candidates:
        return min(candidates,key=lambda pts:max(abs(c) for point in pts for c in point))
    raise FormatError(
        f"Could not find three in-range integer points for FACE/BSP {equation}. "
        "Edit this plane in N3 manually; raw binary coefficients are not valid N3 source.")


def plane_expression(model,offset):
    """Return '(label1, label2, label3)' or inline '[<X,Y,Z>]' N3 syntax."""
    plane=model.planes[offset]
    equation=plane.equation
    refs=_vertex_triplet(model,equation)
    if refs:
        return "("+", ".join(f"_{ref}" for ref in refs)+")"
    points=get_points_on_plane(equation)
    return "("+", ".join("[<{}, {}, {}>]".format(*p) for p in points)+")"
