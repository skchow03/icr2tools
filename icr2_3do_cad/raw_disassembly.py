"""Read-only Papyrus 3DO structure listing for inspection and BSP debugging."""
from three_do import NAMES, i32


def disassemble(model):
    """Return printable lines; offsets are relative to the 3DO body."""
    lines=[f'; FILE {model.path.name}',
           f'; HEADER root=@{model.root_offset} body_length={len(model.body)}',
           f'; MIPs: {model.mip_names}',
           f'; PMPs: {model.pmp_names}',
           f'; EXTERNAL 3DOs: {model.external_names}',
           '; Reachable commands plus referenced vertex records. Unreachable orphan bytes are not decoded.',
           '; READ ONLY — edit vertices, polygons, and transforms through their respective tabs.', '']
    offsets=sorted(set(model.records)|set(model.vertices))
    for off in offsets:
        if off in model.vertices:
            v=model.vertices[off]
            uv=f' UV=<{v.uv[0]},{v.uv[1]}>' if v.textured else ''
            lines.append(f'@{off:<7} VERTEX  <{v.xyz[0]}, {v.xyz[1]}, {v.xyz[2]}>{uv}')
            continue
        kind=model.records[off];name=NAMES[kind]
        ptrs=model.children.get(off,())
        if kind in (1,2):
            p=model.polygons[off]
            lines.append(f'@{off:<7} {name:<10} color={p.color} group={p.group} '
                         f'vertices=[{", ".join("@"+str(v) for v in p.refs)}]')
        elif kind in (5,6,7,8,9,10):
            plane=model.planes[off]
            a,b,c,d=plane.equation
            lines.append(f'@{off:<7} {name:<10} plane=({a},{b},{c},{d}) '
                         f'children=[{", ".join("@"+str(p) for p in ptrs)}]')
        elif kind==11:
            lines.append(f'@{off:<7} LIST       count={len(ptrs)} '
                         f'back→front=[{", ".join("@"+str(p) for p in ptrs)}]')
        elif kind==13:
            s=model.switches[off]
            lines.append(f'@{off:<7} RES        anchor=@{s.anchor} DISTANCE '
                         +', '.join(f'>={n}:@{p}' for n,p in s.branches))
        elif kind==15:
            o=model.dynamics[off]
            lines.append(f'@{off:<7} DYNAMIC    {o.name} XYZ={o.xyz} ZYX-angles={o.angles}')
        elif kind==4:
            mat=model.materials.get(off)
            lines.append(f'@{off:<7} MATERIAL   MIP={mat[0] if mat else "?"} '
                         f'child={"@"+str(ptrs[0]) if ptrs else "NIL"}')
        elif kind in (3,18):
            spr=model.pmp_sprites.get(off)
            lines.append(f'@{off:<7} {name:<10} '
                         + (f'{spr.name} vertex=@{spr.vertex_ref} size={spr.size}' if spr else 'Unknown sprite'))
        else:
            lines.append(f'@{off:<7} {name:<10} children=[{", ".join("@"+str(p) for p in ptrs)}]')
    return '\n'.join(lines)+'\n'
