"""Compile a standalone subset of Papyrus N3 VERSION 3.0 into an ICR2 3DO.

This is *not* a reverse conversion of an existing binary file. It resolves
symbolic references and nested expressions, constructs the binary record tree
and resource table, and validates the result with the normal CAD Model parser.

Unsupported constructs fail explicitly; never silently drop records or pointers.
The original text is retained separately because a 3DO has no label/comment data.
"""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
import math
import re
import struct

from three_do import Model, FormatError, INT32_LO, INT32_HI, INT64_LO, INT64_HI
from text_3d import Document, Statement, parse_document

NUM = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
VEC = re.compile(r"^\[\s*<\s*("+NUM+r")\s*,\s*("+NUM+r")\s*,\s*("+NUM+
                 r")\s*>\s*(?:,\s*T\s*=\s*<\s*("+NUM+r")\s*,\s*("+NUM+
                 r")\s*>)?\s*(?:,\s*[cC]\s*=\s*<\s*("+NUM+r")\s*>)?\s*\]$",re.S)
IDENT = re.compile(r"^[A-Za-z_][A-Za-z_0-9-]*$")
COLOR = re.compile(r"^(?:<\s*("+NUM+r")\s*>|([A-Za-z_][A-Za-z_0-9-]*)\.c|("+NUM+r"))$",re.I)
PLANE5 = re.compile(r"^\(\s*([-+]?\d+)\s*,\s*([-+]?\d+)\s*,\s*([-+]?\d+)\s*,\s*([-+]?\d+)\s*,\s*([-+]?\d+)\s*\)$")
DOUBLE_QUOTE = re.compile(r'^"([^"]+)"$')
XYZ_TOKEN = re.compile(r"\[\s*<\s*("+NUM+r")\s*,\s*("+NUM+r")\s*,\s*("+NUM+r")\s*>", re.S)
SCALE_HINT = re.compile(r"(?m)^\s*%\s*ICR2_COORD_SCALE\s*:\s*([^\r\n]+?)\s*$")
DEFAULT_FRACTIONAL_SCALE = Decimal(6000)  # legacy 3d23do /s=6000: feet -> Papyrus units


def _source_coordinate_scale(source, statements):
    """Preserve integer Papyrus coordinates; scale fractional XYZ inputs.

    A source comment % ICR2_COORD_SCALE: N explicitly overrides the default.
    No inferred unit can be guaranteed for every hand-authored N3 file.
    """
    hints=SCALE_HINT.findall(source)
    if len(hints)>1:
        raise FormatError("Only one % ICR2_COORD_SCALE: N declaration is allowed")
    if hints:
        try:
            scale=Decimal(hints[0].strip())
        except InvalidOperation as exc:
            raise FormatError("Invalid ICR2_COORD_SCALE: expected a positive number") from exc
        if not scale.is_finite() or not (Decimal(0)<scale<=Decimal(1000000)):
            raise FormatError("ICR2_COORD_SCALE must be positive and at most 1000000")
        return scale
    for statement in statements:
        for match in XYZ_TOKEN.finditer(statement.command):
            if any(Decimal(v)!=Decimal(v).to_integral_value() for v in match.groups()):
                return DEFAULT_FRACTIONAL_SCALE
    return Decimal(1)



def _i32(value, what):
    x=int(round(float(value)))
    if not INT32_LO <= x <= INT32_HI:
        raise FormatError(f"{what} is outside signed 32-bit range: {value}")
    return x


def _u16(value,what):
    x=int(round(float(value)))
    if not 0<=x<=65535:
        raise FormatError(f"{what} is outside unsigned 16-bit range: {value}")
    return x


def _split(value: str) -> list[str]:
    """Separate top-level commas, retaining nested expressions and quoted MIPs."""
    res=[]
    at=0
    stack=[]
    quote=False
    matching={')':'(',']':'[','}':'{','>':'<'}
    for i,ch in enumerate(value):
        if ch=='"':
            quote=not quote
        elif not quote:
            if ch in "([{<":
                stack.append(ch)
            elif ch in ")]}>":
                # Track N3 uses SWITCH DISTANCE (anchor) > {branches}.
                # This '>' is an operator, not the closing angle of <x,y,z>.
                if ch==">" and (not stack or stack[-1]!="<"):
                    continue
                if not stack or stack.pop()!=matching[ch]:
                    raise FormatError("Unbalanced parentheses/brackets in N3 expression")
            elif ch==',' and not stack:
                res.append(value[at:i].strip());at=i+1
    if quote or stack:
        raise FormatError("Unterminated N3 expression")
    res.append(value[at:].strip())
    return res


# N3 permits prefix-style nested operators without an extra pair of braces.
# E.g. BSPA (plane), BSPA (plane), a, b, c, d, e is one BSPA node,
# whose first child is another BSPA node, not five sibling list objects.
_N3_PLANE_CHILDREN={"FACE":1,"FACE2":2,"BSPF":3,"BSPA":3,"BSP2":4,"BSPN":2}
_N3_PLANE_HEAD=re.compile(r"^(FACE2?|BSPF|BSPA|BSP2|BSPN)\s+(.+)$",re.I|re.S)
_N3_MATERIAL_ATTR=re.compile(r"^(?:GROUP|MIP)\s*=",re.I)


def _consume_prefix_node(fields,at):
    """Read exactly one logical N3 node from comma-separated prefix tokens."""
    if at>=len(fields):
        raise FormatError("Incomplete nested N3 expression: missing object pointer")
    first=fields[at].strip()
    if not first:
        raise FormatError("Empty object in N3 hierarchy")
    pos=at+1
    head=_N3_PLANE_HEAD.match(first)
    if head:
        parts=[first]
        for _ in range(_N3_PLANE_CHILDREN[head.group(1).upper()]):
            child,pos=_consume_prefix_node(fields,pos)
            parts.append(child)
        return ", ".join(parts),pos
    if re.match(r"^MATERIAL\b",first,re.I):
        parts=[first]
        while pos<len(fields) and _N3_MATERIAL_ATTR.match(fields[pos].strip()):
            parts.append(fields[pos].strip())
            pos+=1
        child,pos=_consume_prefix_node(fields,pos)
        parts.append(child)
        return ", ".join(parts),pos
    if re.match(r"^SUPEROBJ\b",first,re.I):
        child,pos=_consume_prefix_node(fields,pos)
        return first+", "+child,pos
    if re.match(r"^(?:SRB|PMP2)\b",first,re.I):
        if pos+2>len(fields):
            raise FormatError("Incomplete SRB/PMP2 placement")
        return ", ".join(fields[at:pos+2]),pos+2
    if re.match(r"^DYNAMIC\b",first,re.I):
        # A DYNAMIC command has 8 scalar/comma-separated arguments in track N3.
        # Within a LIST it is a prefix operand, not eight sibling objects.
        if pos+7>len(fields):
            raise FormatError("Incomplete DYNAMIC placement")
        return ", ".join(fields[at:pos+7]),pos+7
    return first,pos


def _group_prefix_nodes(fields):
    """Recombine LIST children and FACE/BSP operands in prefix grammar order."""
    grouped=[]
    at=0
    while at<len(fields):
        node,at=_consume_prefix_node(fields,at)
        grouped.append(node)
    return grouped


def _brace(value, opener="{", closer="}"):
    value=value.strip()
    if not value.startswith(opener) or not value.endswith(closer):
        raise FormatError(f"Expected {opener}...{closer} in N3 expression")
    interior=value[len(opener):len(value)-len(closer)]
    # N3 track files use LIST { } for an empty object list, distinct
    # from NIL. _split("") produces [""], which the prefix parser
    # incorrectly treats as an invalid (blank) child.
    if not interior.strip():
        return []
    return _split(interior)


def _flavor(kind):
    return struct.pack("<I",0x80000000 | kind)


def _equation(points):
    p,q,r=points
    u=[q[i]-p[i] for i in range(3)]
    v=[r[i]-p[i] for i in range(3)]
    a,b,c=u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]
    norm=math.gcd(math.gcd(abs(a),abs(b)),abs(c))
    if norm==0:
        raise FormatError("FACE/BSP plane has collinear vertices")
    a,b,c=a//norm,b//norm,c//norm
    while any(not INT32_LO<=x<=INT32_HI for x in (a,b,c)) or not INT64_LO<=-(a*p[0]+b*p[1]+c*p[2])<=INT64_HI:
        a,b,c=tuple(int(x/2) for x in (a,b,c))
        if (a,b,c)==(0,0,0):
            raise FormatError("Cannot represent N3 plane in ICR2 signed coefficients")
    return (a,b,c,-(a*p[0]+b*p[1]+c*p[2]))


class Compiler:
    def __init__(self, text: str, path):
        self.source=text
        self.path=path
        # Arbitrary labels need no offset annotation in a standalone .3D file.
        self.document=parse_document(text,require_offsets=False)
        self.coordinate_scale=_source_coordinate_scale(text,self.document.statements)
        self.decls={entry.label:entry for entry in self.document.statements}
        self.body=bytearray(b"\x00\x00\x00\x00")  # legal null/NIL child pointer
        self.offsets={}
        self.building=set()
        self.mips=[]
        self.pmps=[]
        self.externals=[]
        self._anonymous=0
        self.geometry=0
        self.vertex_uv={}  # Track whether every textured pointer carries UV data.
        self.data_lengths={}  # Track N3 DATA payloads may exceed four words.

    def _file(self,name,table):
        if len(name.encode('ascii','strict'))>8:
            raise FormatError(f"External resource name {name!r} exceeds 8 DOS characters")
        if name not in table:
            table.append(name)
        return table.index(name)

    def _allocate(self,data):
        if len(self.body) + len(data) >= INT32_HI:
            raise FormatError("Compiled 3DO exceeds 2 GiB")
        off=len(self.body)
        self.body.extend(data)
        return off

    def _record(self,kind,*values):
        return self._allocate(_flavor(kind)+struct.pack("<"+"i"*len(values),*values))

    def _coordinate(self,value):
        try:
            numeric=int((Decimal(value)*self.coordinate_scale).to_integral_value(
                rounding=ROUND_HALF_EVEN))
        except (InvalidOperation,OverflowError) as exc:
            raise FormatError(f"Invalid scaled XYZ coordinate {value!r}") from exc
        if not INT32_LO<=numeric<=INT32_HI:
            raise FormatError(f"XYZ coordinate {value} × {self.coordinate_scale} "
                              "exceeds signed 32-bit 3DO range")
        return numeric

    def _vector(self,value):
        match=VEC.fullmatch(value.strip())
        if not match:
            raise FormatError("Expected a coordinate [<X,Y,Z>] expression")
        x,y,z=(self._coordinate(v) for v in match.groups()[:3])
        uv=None
        if match.group(4) is not None:
            uv=(_u16(match.group(4),"Texture U"),_u16(match.group(5),"Texture V"))
        color=_i32(match.group(6),"Vertex color") if match.group(6) else None
        return (x,y,z),uv,color

    def _vertex(self,expression):
        coords,uv,_=self._vector(expression)
        data=b"\x00"*4+struct.pack("<3i",*coords)
        if uv is not None:
            data+=struct.pack("<HH",*uv)
        off=self._allocate(data)
        self.vertex_uv[off]=uv is not None
        return off

    def _coordinates(self,expr):
        expr=expr.strip()
        if expr in self.decls:
            entry=self.decls[expr].command
            if not entry.lstrip().startswith("[<"):
                raise FormatError(f"{expr} does not name a vertex")
            return self._vector(entry)[0]
        if expr.startswith("["):
            return self._vector(expr)[0]
        raise FormatError(f"Unknown plane vertex {expr!r}")

    def _color(self,token):
        token=token.strip()
        match=COLOR.fullmatch(token)
        if not match:
            raise FormatError(f"Unsupported polygon color expression: {token}")
        if match.group(2):
            label=match.group(2)
            if label not in self.decls:
                raise FormatError(f"Color vertex {label} is undefined")
            color=self._vector(self.decls[label].command)[2]
            if color is None:
                raise FormatError(f"Vertex {label} has no c=<color> value")
            return color
        return _i32(match.group(1) or match.group(3),"Polygon color")

    def _angle(self,n):
        value=int(round(float(n)*2147483648/1800))
        return _i32(value,"DYNAMIC rotation")

    def _node(self,expression):
        expression=expression.strip()
        if expression in self.decls:
            return self._named(expression)
        if IDENT.fullmatch(expression):
            return self._named(expression)
        if expression.lower()=='nil':
            return 0
        if expression.upper()=="NIL":return 0
        if expression.upper().startswith('EXTERN '):
            matched=re.fullmatch(r'EXTERN\s+"([^"]+)"',expression,re.I)
            if not matched:raise FormatError(f"Malformed external reference {expression!r}")
            return -(self._file(matched.group(1),self.externals)+1)
        self._anonymous+=1
        off=self._expression(expression)
        return off

    def _named(self,label):
        if label in self.offsets:
            return self.offsets[label]
        if label.lower()=='nil' and label not in self.decls:
            return 0
        if label not in self.decls:
            raise FormatError(f"Unresolved N3 pointer: {label}")
        if label in self.building:
            raise FormatError(f"Circular N3 reference involving {label}")
        self.building.add(label)
        try:
            code=self.decls[label].command
            if code.strip().upper()=="NIL":
                off=0
            else:
                try:
                    off=self._expression(code)
                except FormatError as exc:
                    if re.search(r"\bline\s+\d+\b",str(exc),re.I):
                        raise
                    match=re.search(r"(?m)^\s*"+re.escape(label)+r"\s*:",self.source)
                    line=self.source.count("\n",0,match.start())+1 if match else 1
                    raise FormatError(f"Label {label!r} (line {line}): {exc}") from exc
            self.offsets[label]=off
            return off
        finally:
            self.building.remove(label)

    def _plane(self,token):
        token=token.strip()
        if not token.startswith("(") or not token.endswith(")"):
            raise FormatError("Expected FACE/BSP plane in parentheses")
        raw=PLANE5.fullmatch(token)
        if raw:
            values=[_i32(v,"Plane coefficient") for v in raw.groups()]
            return (values[0],values[1],values[2],struct.unpack("<q",struct.pack("<ii",values[3],values[4]))[0])
        items=_brace(token,"(",")")
        if len(items)!=3:
            raise FormatError("FACE/BSP requires 3 plane vertices or 5 raw coefficients")
        return _equation([self._coordinates(x) for x in items])

    def _expression(self,code):
        code=code.strip()
        if code.upper()=="NIL":return 0
        if code.startswith("["):
            return self._vertex(code)
        poly=re.match(r"^(POLY(?:\s+\[T\])?|LINE)\s+(.+?)\s*(\{.*\})$",code,re.I|re.S)
        if poly:
            textured="[T]" in poly.group(1).upper()
            color=self._color(poly.group(2))
            refs=[self._node(x) for x in _brace(poly.group(3))]
            if len(refs)<2:
                raise FormatError("N3 polygon requires at least two vertices")
            for ref in refs:
                if ref<=0 or ref not in self.vertex_uv:
                    raise FormatError("A polygon must reference local vertex declarations")
            # Papyrus polygon references are commonly closed by repeating vertex 0.
            if refs[-1]!=refs[0]:
                refs.append(refs[0])
            if len(refs)>250000:
                raise FormatError("Too many polygon vertices")
            self.geometry+=1
            if textured:
                for ref in refs:
                    if not self.vertex_uv[ref]:
                        raise FormatError("Textured polygon references a vertex without T=<U,V>")
                return self._record(2,0,color,len(refs)-1,*refs)
            return self._record(1,color,len(refs)-1,*refs)
        list_match=re.match(r"^LIST\s*(\{.*\})$",code,re.I|re.S)
        if list_match:
            refs=[self._node(x) for x in _group_prefix_nodes(_brace(list_match.group(1)))]
            return self._record(11,len(refs),*refs)
        face=re.match(r"^(FACE2?|BSPF|BSPA|BSP2|BSPN)\s+(.+)$",code,re.I|re.S)
        if face:
            kind={"FACE":5,"FACE2":6,"BSPF":7,"BSPA":8,"BSP2":9,"BSPN":10}[face.group(1).upper()]
            fields=_split(face.group(2))
            count={5:1,6:2,7:3,8:3,9:4,10:2}[kind]
            if len(fields)<count+1:
                raise FormatError(f"{face.group(1)} requires a plane and {count} object pointers")
            a,b,c,d=self._plane(fields[0])
            children=_group_prefix_nodes(fields[1:])
            if len(children)!=count:
                raise FormatError(f"{face.group(1)} requires {count} object pointers; "
                                  f"found {len(children)}")
            refs=[self._node(x) for x in children]
            # The text N3 operand orders differ from the binary ICR2 slots.
            if kind in (7,8):refs=[refs[0],refs[2],refs[1]]
            elif kind==9:refs=[refs[0],refs[3],refs[2],refs[1]]
            return self._allocate(_flavor(kind)+struct.pack("<3iq",a,b,c,d)+struct.pack("<"+"i"*len(refs),*refs))
        material=re.match(r"^MATERIAL\s+(.+)$",code,re.I|re.S)
        if material:
            fields=_split(material.group(1))
            mip=None;group=3;child=None
            for f in fields:
                name=re.fullmatch(r'MIP\s*=\s*"([^"]+)"',f,re.I)
                g=re.fullmatch(r'GROUP\s*=\s*([-+]?\d+)',f,re.I)
                if name:mip=name.group(1)
                elif g:group=_i32(g.group(1),"MATERIAL GROUP")
                else:
                    if child is not None:raise FormatError("MATERIAL has more than one child")
                    child=f
            if child is None:
                raise FormatError("MATERIAL requires a child object")
            # Track N3 legitimately uses MATERIAL GROUP=30, LIST {...}
            # without a MIP. In the 3DO flavor, -1 denotes no texture.
            mid=self._file(mip,self.mips) if mip is not None else -1
            return self._record(4,mid,group if mip is None else 0,self._node(child))
        sprite=re.match(r"^(SRB|PMP2)\s+(.+)$",code,re.I|re.S)
        if sprite:
            fields=_split(sprite.group(2))
            if len(fields)!=3:
                raise FormatError("SRB/PMP2 requires vertex, size, PMP filename")
            name=DOUBLE_QUOTE.fullmatch(fields[2])
            if not name:
                raise FormatError("SRB/PMP2 filename must be quoted")
            idx=self._file(name.group(1),self.pmps)
            return self._record(3 if sprite.group(1).upper()=="SRB" else 18,
                                self._node(fields[0]),_i32(fields[1],"Sprite size"),idx)
        dynamic=re.match(r'^DYNAMIC\s+(.+)$',code,re.I|re.S)
        if dynamic:
            fields=_split(dynamic.group(1))
            if len(fields) not in (5,8):
                raise FormatError("DYNAMIC requires XYZ, one or three rotations, EXTERN name")
            if len(fields)==5:
                x,y,z,angle,external=fields
                angles=[angle,"0","0"]
                # Fourth supplied number is an orientation, not the '1' animation flag.
            else:
                x,y,z,a,b,c,flag,external=fields
                if flag.strip()!="1":
                    raise FormatError("DYNAMIC only supports animation flag 1")
                angles=[a,b,c]
            ext=re.fullmatch(r'EXTERN\s+"([^"]+)"',external,re.I)
            if not ext:raise FormatError("DYNAMIC requires an EXTERN name")
            idx=self._file(ext.group(1),self.externals)
            return self._record(15,*[self._coordinate(n) for n in (x,y,z)],
                                *[self._angle(n) for n in angles],-(idx+1))
        superobj=re.match(r"^SUPEROBJ\s+(.+)$",code,re.I|re.S)
        if superobj:
            fields=_split(superobj.group(1))
            if len(fields)!=2:raise FormatError("SUPEROBJ expects previous object and a list")
            refs=[self._node(x) for x in _brace(fields[1])]
            return self._record(16,self._node(fields[0]),len(refs),*refs)
        switch=re.fullmatch(r"SWITCH\s+DISTANCE\s*\((.*?)\)\s*>\s*\{(.*)\}",code,re.I|re.S)
        if switch:
            anchor=self._node(switch.group(1))
            branches=[]
            for element in _split(switch.group(2)):
                term=re.fullmatch(r"\(\s*([-+]?\d+)\s*\?\s*(.*?)\s*\)",element,re.S)
                if not term:raise FormatError("Malformed SWITCH DISTANCE branch")
                branches.append((_i32(term.group(1),"SWITCH threshold"),self._node(term.group(2))))
            if not 1<=len(branches)<=4 or branches[-1][0]!=0:
                raise FormatError("SWITCH DISTANCE requires 1–4 branches ending in zero")
            payload=[anchor]
            for threshold,ptr in branches:payload.extend((threshold,ptr))
            return self._record(13,*payload)
        dyno=re.match(r"^DYNO\s+(\{.*\})$",code,re.I|re.S)
        if dyno:
            numbers=_brace(dyno.group(1))
            if len(numbers)!=4:raise FormatError("DYNO requires four integers")
            return self._record(12,*[_i32(x,"DYNO parameter") for x in numbers])
        data=re.match(r"^DATA\s+(\{.*\})$",code,re.I|re.S)
        if data:
            numbers=_brace(data.group(1))
            if not numbers or any(not x for x in numbers):
                raise FormatError("DATA requires one or more integer values")
            if len(numbers)>250000:
                raise FormatError("DATA exceeds safe maximum of 250,000 integers")
            off=self._record(17,*[_i32(x,"DATA parameter") for x in numbers])
            self.data_lengths[off]=len(numbers)
            return off
        recolor=re.match(r"^RECOLOR\s*\((.*)\)$",code,re.I|re.S)
        if recolor:
            fields=_split(recolor.group(1))
            values=[]
            for x in fields:
                m=re.fullmatch(r"([-+]?\d+)\s*:\s*([-+]?\d+)",x)
                if not m:raise FormatError("Malformed RECOLOR mapping")
                values.extend((_i32(m.group(1),"RECOLOR index"),_i32(m.group(2),"RECOLOR color")))
            return self._record(14,len(fields),*values)
        raise FormatError("Unsupported N3 construct: "+code[:125])

    def compile(self):
        if not self.decls:
            raise FormatError("No N3 declarations found")
        # 'root' is standard for hand-authored N3; offset-tagged CAD exports
        # carry an explicit root marker. Otherwise the final non-data command.
        root_name=next((name for name in self.decls if name.lower()=="root"),None)
        if root_name is None:
            m=re.search(r"(?m)^\s*%\s*ICR2_ROOT:\s*(\d+)\s*$",self.source)
            if m:
                root_name=next((s.label for s in self.document.statements
                                if s.offset==int(m.group(1))),None)
        if root_name is None:
            possible=[s.label for s in self.document.statements
                      if not s.command.startswith("[") and s.command.upper()!="NIL"]
            if not possible:raise FormatError("No root render node present in N3 text")
            root_name=possible[-1]
        root=self._named(root_name)
        if root<=0:raise FormatError("N3 root resolves to NIL or an external pointer")
        # Emit other standalone declarations so their annotations survive;
        # they can be unreferenced from root but must still be well-formed.
        for label in self.decls:
            self._named(label)
        if not self.geometry and not self.externals:
            raise FormatError("N3 text has no local geometry or external placements")
        names=self.mips+self.pmps+self.externals
        header=struct.pack("<5i",len(self.body),root,len(self.mips),len(self.pmps),len(self.externals))
        try:
            name_table=b"".join(n.encode("ascii").ljust(8,b"\x00") for n in names)
        except UnicodeError as err:
            raise FormatError("Papyrus 3DO resource names must be ASCII") from err
        raw=header+name_table+bytes(self.body)
        checked=Model(self.path,raw_data=raw)
        checked.n3_coordinate_scale=self.coordinate_scale
        checked.n3_data_lengths=self.data_lengths
        # Rewrite annotations for the new compiled offsets. A label can
        # legitimately denote NIL at 0; that has no separately editable record.
        remapped=Document(
            [replace(s,offset=self.offsets[s.label]) for s in self.document.statements],
            self.document.prologue,self.document.epilogue,self.document.original_text)
        return checked,remapped


def compile_n3_text(source: str, path):
    """Return (validated Model, name/comment Document) from only N3 .3D text."""
    try:
        return Compiler(source,path).compile()
    except (OverflowError,ValueError,struct.error) as exc:
        if isinstance(exc,FormatError):raise
        raise FormatError(f"Cannot compile N3 text: {exc}") from exc
