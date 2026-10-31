"""Conservative Papyrus/N3 .3D text interchange for the 3DO CAD editor.

Uses N3 VERSION 3.0 syntax and the same offset-based naming convention as
skchow03/3do23d.  % ICR2_OFFSET annotations are optional for conventional _123
names, but essential for arbitrary renamed labels.  The *text* is the home for
names and comments; a binary .3DO has nowhere to store either.

Import is deliberately an in-place patch of an existing, loaded binary 3DO.
It accepts edits to vertex coordinates/UVs, polygon colors and groups,
stored FACE/BSP coefficients, and DYNAMIC transforms.  It rejects any change
to the command/pointer topology, missing records, and unsupported syntax.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import struct

from three_do import FormatError, Model, INT32_LO, INT32_HI, INT64_LO, INT64_HI, i32, i64

ID_LINE = re.compile(r"^\s*%\s*ICR2_OFFSET\s*:\s*(\d+)\s*$", re.I)
IDENT = re.compile(r"^[A-Za-z_][A-Za-z_0-9]*$")
AUTO_ID = re.compile(r"^_(\d+)$")
NUM = r"[-+]?\d+"
VERTEX_RE = re.compile(r"^\[\s*<\s*(" + NUM + r")\s*,\s*(" + NUM +
                       r")\s*,\s*(" + NUM +
                       r")\s*>\s*(?:,\s*T\s*=\s*<\s*(" + NUM +
                       r")\s*,\s*(" + NUM + r")\s*>)?\s*\]$", re.I | re.S)
POLY_RE = re.compile(r"^POLY(\s+\[T\])?\s*<\s*(" + NUM +
                     r")\s*>\s*\{\s*([^{}]*?)\s*\}$", re.I | re.S)
RAW_PLANE = re.compile(r"^\s*\(\s*(" + NUM + r")\s*,\s*(" + NUM +
                       r")\s*,\s*(" + NUM + r")\s*,\s*(" + NUM +
                       r")\s*,\s*(" + NUM + r")\s*\)\s*,\s*(.*)$", re.S)
DYNAMIC_RE = re.compile(r"^DYNAMIC\s+(" + NUM + r")\s*,\s*(" + NUM +
                        r")\s*,\s*(" + NUM + r")\s*,\s*(" + NUM +
                        r")\s*,\s*(" + NUM + r")\s*,\s*(" + NUM +
                        r")\s*,\s*1\s*,\s*EXTERN\s+\"([^\"]+)\"\s*$", re.I | re.S)


@dataclass
class Statement:
    offset: int
    label: str
    command: str
    before: str
    trailing: str


@dataclass
class Document:
    statements: list[Statement]
    prologue: str
    epilogue: str
    original_text: str


def _ref(off: int, model: Model) -> str:
    if off == 0:
        return "NIL"
    if off < 0:
        index = -off
        if 1 <= index <= len(model.external_names):
            return 'EXTERN "' + model.external_names[index - 1] + '"'
        raise FormatError(f"Unknown external 3DO index {off}")
    return f"_{off}"


def _join_refs(refs, model):
    return ", ".join(_ref(r, model) for r in refs)


def _angle(raw):
    return round(raw * 1800 / 2147483648)


def _angle_back(tenths):
    val = round(tenths * 2147483648 / 1800)
    if not INT32_LO <= val <= INT32_HI:
        raise FormatError("DYNAMIC rotation overflows signed Papyrus angle")
    return val


def _plane(model, off, tag):
    a, b, c = (i32(model.body, off + j) for j in (4, 8, 12))
    lo, hi = struct.unpack_from("<ii", model.body, off + 16)
    children = [i32(model.body, off + j) for j in {
        5: (24,), 6: (24, 28), 7: (24, 28, 32),
        8: (24, 28, 32), 9: (24, 28, 32, 36),
        10: (24, 28),
    }[tag]]
    if tag in (7, 8):
        children = [children[0], children[2], children[1]]
    if tag == 9:
        children = [children[0], children[3], children[2], children[1]]
    return f"({a}, {b}, {c}, {lo}, {hi}), {_join_refs(children, model)}"


def _command(model: Model, off: int) -> str:
    if off in model.vertices:
        v = model.vertices[off]
        x, y, z = v.xyz
        tail = f", T=<{v.uv[0]}, {v.uv[1]}>" if v.textured else ""
        return f"[<{x}, {y}, {z}>{tail}]"
    kind = model.records.get(off)
    b = model.body
    if kind is None:
        raise FormatError(f"Unrecognized body record @{off}")
    if kind == 0:
        return "NIL"
    if kind in (1, 2):
        p = model.polygons[off]
        surface="LINE" if len(p.unique_refs)<=2 else ("POLY [T]" if kind==2 else "POLY")
        return f"{surface} <{p.color}> " + "{"+_join_refs(p.refs, model)+"}"
    if 5 <= kind <= 10:
        return {5: "FACE", 6: "FACE2", 7: "BSPF", 8: "BSPA",
                9: "BSP2", 10: "BSPN"}[kind] + " " + _plane(model, off, kind)
    if kind == 11:
        count = i32(b,off+4)
        return "LIST {" + _join_refs((i32(b,off+8+j*4) for j in range(count)),model) + "}"
    if kind == 13:
        sw = model.switches[off]
        return ("SWITCH DISTANCE ("+_ref(sw.anchor,model)+") > {" +
                ", ".join(f"({threshold} ? {_ref(ptr,model)})" for threshold,ptr in sw.branches)+"}")
    if kind == 15:
        d = model.dynamics[off]
        xyz = ", ".join(str(x) for x in d.xyz)
        angles = ", ".join(str(_angle(x)) for x in d.angles)
        return f'DYNAMIC {xyz}, {angles}, 1, EXTERN "{d.name}"'
    if kind == 16:
        prior = i32(b,off+4)
        count = i32(b,off+8)
        refs = [i32(b,off+12+j*4) for j in range(count)]
        return f"SUPEROBJ {_ref(prior,model)}, " + "{"+_join_refs(refs,model)+"}"
    if kind == 4:
        number = i32(b,off+4)
        if not 0<=number<len(model.mip_names):
            raise FormatError(f"MATERIAL @{off}: missing MIP name")
        group = 3
        descendants = [p for p in model.children.get(off,[]) if p in model.polygons and model.polygons[p].kind==2]
        if descendants:
            group=model.polygons[descendants[0]].group
        return f'MATERIAL MIP="{model.mip_names[number]}", GROUP={group}, {_ref(i32(b,off+12),model)}'
    if kind in (3,18):
        number = i32(b,off+12)
        if not 0<=number<len(model.pmp_names):
            raise FormatError(f"Sprite @{off}: unknown PMP index")
        op = "SRB" if kind==3 else "PMP2"
        return f'{op} {_ref(i32(b,off+4),model)}, {i32(b,off+8)}, "{model.pmp_names[number]}"'
    if kind == 12:
        return "DYNO {"+", ".join(str(i32(b,off+j)) for j in (4,8,12,16))+"}"
    if kind == 14:
        count=i32(b,off+4)
        pairs=[f"{i32(b,off+8+8*j)}: {i32(b,off+12+8*j)}" for j in range(count)]
        return "RECOLOR ("+", ".join(pairs)+")"
    if kind == 17:
        return "DATA {"+", ".join(str(i32(b,off+j)) for j in (4,8,12,16))+"}"
    raise FormatError(f"Cannot export {kind} record at @{off} to compatible N3 text")


def _all_offsets(model):
    return sorted(set(model.vertices) | set(model.records))


def _export_default(model):
    lines=["3D VERSION 3.0;", "% Exported by ICR2 3DO CAD.  Keep this .3D as the annotated source.",
           "% Original binary 3DO is required when importing edited text.",
           f"% ICR2_ROOT: {model.root_offset}", ""]
    for off in _all_offsets(model):
        lines.append(f"% ICR2_OFFSET: {off}")
        lines.append(f"_{off}: {_command(model, off)};")
    return "\n".join(lines)+"\n"


def _without_comment(line):
    # N3 uses % as the comment introducer, including indented full-line comments.
    # Preserve the comment verbatim in each statement's trailing field.
    inside=False
    for i,ch in enumerate(line):
        if ch=='"':
            inside=not inside
        elif ch=='%' and not inside:
            return line[:i],line[i:]
    return line,""


def parse_document(text: str) -> Document:
    """Parse N3 commands while preserving comments and all original label names."""
    if not re.search(r"(?im)^\s*3D\s+VERSION\s+3\.0\s*;",text):
        raise FormatError("Expected a Papyrus N3 '3D VERSION 3.0;' text file")
    rows=text.splitlines(keepends=True)
    statements=[]
    pending=""
    command_rows=[]
    anchored=None
    prefix=""
    started=False
    prologue=""
    labels=set()
    for lineno,row in enumerate(rows,1):
        raw,comment=_without_comment(row.rstrip("\r\n"))
        if not command_rows:
            tag=ID_LINE.fullmatch(row.strip())
            if tag:
                anchored=int(tag.group(1))
                prefix+=row
                continue
            if not raw.strip() and not command_rows:
                prefix+=row
                continue
            if raw.lstrip().startswith('%') or (not raw.strip() and comment):
                prefix+=row
                continue
            if re.match(r"^\s*3D\s+VERSION\s+3\.0\s*;\s*$",raw,re.I):
                prefix+=row
                continue
        command_rows.append((raw,comment,row))
        if ";" not in raw:
            continue
        combined="\n".join(r[0] for r in command_rows)
        if combined.count(";")!=1 or not combined.rstrip().endswith(";"):
            raise FormatError(f"Only one N3 command per statement is supported (near line {lineno})")
        m=re.match(r"^\s*([A-Za-z_][A-Za-z_0-9]*)\s*:\s*(.*?)\s*;\s*$",combined,re.S)
        if not m:
            raise FormatError(f"Could not parse N3 declaration near line {lineno}")
        label=m.group(1)
        if label in labels:
            raise FormatError(f"Duplicate .3D label {label!r}")
        labels.add(label)
        off=anchored
        if off is None:
            match=AUTO_ID.fullmatch(label)
            if match:
                off=int(match.group(1))
        if off is None:
            raise FormatError(f"Label {label!r} lacks '% ICR2_OFFSET: N' annotation; "
                              "load an annotated CAD export or use original _offset labels")
        trailing=command_rows[-1][1]+("\n" if command_rows[-1][2].endswith("\n") else "")
        statements.append(Statement(off,label,m.group(2).strip(),prefix,trailing))
        prefix=""
        anchored=None
        command_rows=[]
        started=True
    if command_rows:
        raise FormatError("Unterminated .3D statement")
    if not statements:
        raise FormatError("No N3 records found")
    seen=set()
    for entry in statements:
        if entry.offset in seen:
            raise FormatError(f"Duplicate 3DO record offset {entry.offset}")
        seen.add(entry.offset)
    return Document(statements,prologue,prefix,text)


def _split_csv(value):
    """Split commas while respecting parenthesized plane tuples and EXTERN quotes."""
    items=[];at=0;depth=0;quoted=False
    for i,ch in enumerate(value):
        if ch=='"':quoted=not quoted
        elif not quoted:
            if ch in "({[<":depth+=1
            elif ch in ")}]>":depth-=1
            elif ch=="," and depth==0:
                items.append(value[at:i].strip());at=i+1
    items.append(value[at:].strip())
    return items


def _normalize(text,label_offsets):
    """Replace named pointers with offset identities, ignoring layout only."""
    def swap(m):
        label=m.group(0)
        return f"@{label_offsets[label]}" if label in label_offsets else label
    text=re.sub(r'"[^"]*"|[A-Za-z_][A-Za-z_0-9]*',
                lambda m:m.group(0) if m.group(0).startswith('"') else swap(m),text)
    return re.sub(r"\s+","",text)


def _apply_edits(model, doc):
    expected=set(_all_offsets(model))
    actual={stmt.offset for stmt in doc.statements}
    if expected!=actual:
        missing=sorted(expected-actual)[:8];added=sorted(actual-expected)[:8]
        raise FormatError(f"Cannot change 3DO record count/topology: missing offsets {missing}; new offsets {added}. "
                          "Use CAD geometry tools for additions and splitting.")
    labels={s.label:s.offset for s in doc.statements}
    for s in doc.statements:
        if not IDENT.fullmatch(s.label):
            raise FormatError(f"Invalid N3 label {s.label!r}")
    raw=bytearray(model.raw)
    for s in doc.statements:
        off=s.offset
        kind=model.records.get(off)
        current=_command(model,off)
        command=s.command
        if off in model.vertices:
            m=VERTEX_RE.fullmatch(command)
            if not m:
                raise FormatError(f"Vertex {s.label}: invalid coordinate or UV syntax")
            values=[int(x) for x in m.groups() if x is not None]
            vertex=model.vertices[off]
            if (len(values)==5)!=vertex.textured:
                raise FormatError(f"Vertex {s.label}: textured/nontextured type cannot change")
            if any(not INT32_LO<=v<=INT32_HI for v in values[:3]):
                raise FormatError(f"Vertex {s.label}: coordinate outside signed 32-bit range")
            struct.pack_into("<3i",raw,model.body_start+off+4,*values[:3])
            if vertex.textured:
                if any(not 0<=v<=65535 for v in values[3:]):
                    raise FormatError(f"Vertex {s.label}: UV outside unsigned 16-bit range")
                struct.pack_into("<HH",raw,model.body_start+off+16,*values[3:])
            continue
        if kind in (1,2):
            m=POLY_RE.fullmatch(command)
            line_form=False
            if m is None:
                line_form=True
                m=re.fullmatch(r"LINE\s*<\s*("+NUM+r")\s*>\s*\{\s*([^{}]*?)\s*\}",command,re.I|re.S)
            if not m or (not line_form and bool(m.group(1))!=(kind==2)) or (
                    line_form and len(model.polygons[off].unique_refs)>2):
                raise FormatError(f"Polygon {s.label}: polygon type/format cannot change")
            refs=[x.strip() for x in _split_csv(m.group(2 if line_form else 3))]
            original=model.polygons[off]
            if refs != [] and any(r not in labels and r!='NIL' for r in refs):
                raise FormatError(f"Polygon {s.label}: undefined vertex pointer")
            resolved=[labels[r] if r in labels else 0 for r in refs]
            if resolved!=list(original.refs):
                raise FormatError(f"Polygon {s.label}: vertex topology changes are not supported by text import")
            color=int(m.group(1 if line_form else 2))
            if not INT32_LO<=color<=INT32_HI:
                raise FormatError(f"Polygon {s.label}: color outside 32-bit range")
            struct.pack_into("<i",raw,model.body_start+off+(8 if kind==2 else 4),color)
            continue
        if kind in (5,6,7,8,9,10):
            name={5:"FACE",6:"FACE2",7:"BSPF",8:"BSPA",9:"BSP2",10:"BSPN"}[kind]
            if not command.upper().startswith(name+" "):
                raise FormatError(f"Plane {s.label}: cannot change FACE/BSP command flavor")
            plane=RAW_PLANE.fullmatch(command[len(name):].strip())
            baseline=RAW_PLANE.fullmatch(current[len(name):].strip())
            if not plane or not baseline:
                raise FormatError(f"Plane {s.label}: expected five raw signed coefficients")
            if _normalize(plane.group(6),labels)!=_normalize(baseline.group(6),
                                    {f"_{x}":x for x in expected}):
                raise FormatError(f"Plane {s.label}: BSP child pointers may not change")
            coefficients=list(map(int,plane.groups()[:5]))
            if any(not INT32_LO<=v<=INT32_HI for v in coefficients):
                raise FormatError(f"Plane {s.label}: coefficient outside signed 32-bit range")
            struct.pack_into("<5i",raw,model.body_start+off+4,*coefficients)
            continue
        if kind==15:
            m=DYNAMIC_RE.fullmatch(command)
            baseline=DYNAMIC_RE.fullmatch(current)
            if not m:
                raise FormatError(f"Dynamic {s.label}: invalid DYNAMIC syntax")
            if m.group(7).casefold()!=baseline.group(7).casefold():
                raise FormatError(f"Dynamic {s.label}: changing EXTERN file is not supported")
            xyz=tuple(map(int,m.groups()[:3]))
            if any(not INT32_LO<=v<=INT32_HI for v in xyz):
                raise FormatError(f"Dynamic {s.label}: coordinate overflow")
            angles=tuple(int(x) for x in m.groups()[3:6])
            original=model.dynamics[off].angles
            angles_raw=tuple(old if _angle(old)==new else _angle_back(new)
                             for old,new in zip(original,angles))
            struct.pack_into("<6i",raw,model.body_start+off+4,*xyz,*angles_raw)
            continue
        normal_old=_normalize(current,{f"_{x}":x for x in expected})
        normal_new=_normalize(command,labels)
        if normal_old!=normal_new:
            raise FormatError(f"{s.label} @{off}: changes to {kind} records/pointers are not yet supported. "
                              "You may freely rename labels and edit comments.")
    checked=Model(model.path,raw_data=bytes(raw))
    if set(checked.records)!=set(model.records) or set(checked.vertices)!=set(model.vertices):
        raise FormatError("Imported .3D changed reachable 3DO record structure")
    return checked


def import_text(model: Model, text: str) -> tuple[Model,Document]:
    """Apply annotated N3 text edits to an existing binary 3DO without rebuilding it."""
    doc=parse_document(text)
    return _apply_edits(model,doc),doc


def export_text(model: Model, template: Document | None = None) -> str:
    """Emit real N3 declarations, retaining comments and names from an imported text document."""
    checked=Model(model.path,raw_data=model.build_modified_bytes()[0])
    if template is None:
        return _export_default(checked)
    if {s.offset for s in template.statements}!=set(_all_offsets(checked)):
        # Geometry changes made in CAD can append nodes. Never reuse an obsolete
        # name map where a newly created offset might accidentally be misidentified.
        return _export_default(checked)
    labels={s.offset:s.label for s in template.statements}
    ret=[]
    if not re.search(r"(?im)^\s*3D\s+VERSION\s+3\.0\s*;",template.statements[0].before):
        ret=["3D VERSION 3.0;", "% ICR2_ROOT: "+str(checked.root_offset)]
    for s in template.statements:
        fresh=_command(checked,s.offset)
        fresh=re.sub(r'"[^"]*"|(?<![A-Za-z_0-9])_(\d+)\b',
                     lambda m:m.group(0) if m.group(0).startswith('"')
                         else labels.get(int(m.group(1)),m.group(0)),fresh)
        # Preserve the entire declaration (including its whitespace) if semantics
        # are already identical, otherwise update just the declaration content.
        refmap={x.label:x.offset for x in template.statements}
        if _normalize(fresh,refmap)==_normalize(s.command,refmap):
            declaration=s.command
        else:
            declaration=fresh
        ret.append(s.before.rstrip("\r\n") if s.before.strip() else "")
        ret.append(f"{s.label}: {declaration};"+s.trailing.rstrip("\r\n"))
    if template.epilogue:
        ret.append(template.epilogue.rstrip("\r\n"))
    return "\n".join(line for line in ret if line is not None)+"\n"
