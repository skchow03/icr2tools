"""Contextual, read-only syntax help for the N3 features supported by ICR2 CAD.

Based on n3_compile.Compiler._expression and text_3d.parse_document.
This is documentation only: no completion, source mutation, or compilation.
The pure helpers are intentionally independent of Qt for regression testing.
"""
from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class N3CommandHelp:
    name: str
    syntax: str
    description: str
    detail: str

    def compact(self) -> str:
        return f"{self.name} — {self.description}\nSyntax: {self.syntax}"

    def tooltip(self) -> str:
        return f"{self.name}\n{self.description}\n\nSyntax: {self.syntax}\n\n{self.detail}"


# child0 / child1 are deliberately described as ordered scene children:
# camera-side traversal differs by FACE/BSP flavor; an unverified semantic
# such as "always front" or "always back" would be misleading.
COMMAND_HELP = {
    "VERSION": N3CommandHelp(
        "3D VERSION 3.0", "3D VERSION 3.0;",
        "Identifies the file as Papyrus N3 text.",
        "Required at the beginning of an editable .3D source. This is a header, not a named object."),
    "DECLARATION": N3CommandHelp(
        "Named statement", "label: COMMAND arguments;",
        "Defines a named N3 object that other statements can reference.",
        "Use a unique pointer name before the colon and a semicolon to end the command. F2 renames a selected pointer."),
    "VERTEX": N3CommandHelp(
        "Vertex", "name: [<X, Y, Z>];",
        "Defines a 3D point in Papyrus XYZ coordinates.",
        "Optional T=<U,V> gives texture coordinates; c=<index> supplies a vertex palette color. "
        "Examples: p: [<0,0,0>, T=<127,120>]; or p: [<1,2,3>, c=<44>]; "
        "Fractional XYZ can be scaled (default 6000); an ICR2_COORD_SCALE comment overrides the scale."),
    "POLY": N3CommandHelp(
        "POLY", "name: POLY <color> {v1, v2, v3, ...};",
        "Creates a solid, palette-indexed polygon from ordered vertex references.",
        "The color is a numeric palette index or a color-bearing vertex reference (p.c). "
        "Vertex order controls face orientation. The compiler closes an unclosed polygon automatically; "
        "all references must be local vertices."),
    "POLY_T": N3CommandHelp(
        "POLY [T]", "name: POLY [T] <color> {v1, v2, v3, ...};",
        "Creates a polygon whose vertices supply texture UV coordinates.",
        "Each referenced vertex needs T=<U,V>; a surrounding MATERIAL MIP selects the bitmap. "
        "Vertex winding still matters. The color is a palette-index operand."),
    "LINE": N3CommandHelp(
        "LINE", "name: LINE <color> {v1, v2};",
        "Creates line geometry using local vertex references.",
        "The parser accepts LINE using the polygon-record path. Supply at least two vertices "
        "and a color operand. A LINE is not a BSP partition."),
    "NIL": N3CommandHelp(
        "NIL", "name: NIL;",
        "Represents an empty or null scene-tree pointer.",
        "Use NIL in LIST/FACE/BSP hierarchy positions with no child. "
        "It is not a valid POLY vertex reference. Some files declare nil: NIL; as a named null."),
    "LIST": N3CommandHelp(
        "LIST", "name: LIST {child1, child2, ...};",
        "Groups child scene nodes so they can be referenced together.",
        "Children may be labels, NIL, or inline N3 commands. Empty LIST { } "
        "and a trailing comma are accepted by this compiler."),
    "FACE": N3CommandHelp(
        "FACE", "name: FACE (v1, v2, v3), child;",
        "Attaches one child object to a geometric plane.",
        "The ordered three non-collinear points define the plane and its normal. "
        "Points may be named vertices or inline [<X,Y,Z>]."),
    "FACE2": N3CommandHelp(
        "FACE2", "name: FACE2 (v1, v2, v3), child1, child2;",
        "Defines a plane-associated node with two child object slots.",
        "The three ordered plane points establish orientation. The two subsequent "
        "object references are hierarchy children, not additional plane vertices."),
    "BSPF": N3CommandHelp(
        "BSPF", "name: BSPF (v1, v2, v3), child1, child2, child3;",
        "Defines a plane-based BSP hierarchy node with three child slots.",
        "The three points in parentheses define the oriented partition plane; "
        "their winding determines the normal. Child pointers follow the plane tuple. "
        "Selecting the row displays ordered vertex markers and winding arrows in the viewport."),
    "BSPA": N3CommandHelp(
        "BSPA", "name: BSPA (v1, v2, v3), child1, child2, child3;",
        "Defines another three-child BSP plane node.",
        "Like BSPF, its plane uses three ordered points; the child pointers are "
        "interpreted according to the BSPA record flavor. The viewer can show 1→2→3 winding."),
    "BSP2": N3CommandHelp(
        "BSP2", "name: BSP2 (v1, v2, v3), child1, child2, child3, child4;",
        "Defines a BSP plane node with four child slots.",
        "The first three operands inside parentheses define the oriented partition plane; "
        "the four object pointers occur after the parentheses."),
    "BSPN": N3CommandHelp(
        "BSPN", "name: BSPN (v1, v2, v3), child1, child2;",
        "Defines a BSP plane node with two child slots.",
        "The normal is computed from the ordered three plane points. "
        "The two following pointers are scene children and may be NIL."),
    "MATERIAL": N3CommandHelp(
        "MATERIAL", 'name: MATERIAL MIP="texture", GROUP=4, child;',
        "Wraps a child scene node with material/texture attributes.",
        "MIP is an optional quoted 8-character DOS resource name; GROUP is a numeric "
        "material parameter. A MATERIAL can also omit MIP and use GROUP alone. "
        "The final operand must be one child object."),
    "SWITCH": N3CommandHelp(
        "SWITCH DISTANCE",
        "name: SWITCH DISTANCE (anchor) > {(distance ? child), (0 ? fallback)};",
        "Selects scene children by distance from a reference vertex.",
        "Provide 1–4 threshold/child pairs; the last threshold must be zero. "
        "The anchor must reference a vertex. This is the N3 RES/LOD mechanism."),
    "DYNAMIC": N3CommandHelp(
        "DYNAMIC", 'name: DYNAMIC X, Y, Z, A, B, C, 1, EXTERN "object";',
        "Places an external .3DO object with position and orientation.",
        'A compact form DYNAMIC X, Y, Z, A, EXTERN "object" is also supported. '
        "The longer form requires flag 1. XYZ is scaled like other N3 coordinates."),
    "EXTERN": N3CommandHelp(
        "EXTERN", 'EXTERN "objectname"',
        "References another named external 3DO object.",
        "Used as a scene child and as the last operand of DYNAMIC. "
        "Names must fit the eight-character DOS resource name table."),
    "SUPEROBJ": N3CommandHelp(
        "SUPEROBJ", "name: SUPEROBJ previous, {child1, child2, ...};",
        "Combines a previous object reference and a collection of child objects.",
        "The first operand is a scene pointer; the braces contain additional children."),
    "SRB": N3CommandHelp(
        "SRB", 'name: SRB vertex, size, "sprite";',
        "Places a PMP sprite at a vertex reference.",
        "Supply its anchor vertex, integer size and a quoted PMP resource name."),
    "PMP2": N3CommandHelp(
        "PMP2", 'name: PMP2 vertex, size, "sprite";',
        "Places a PMP2 sprite record at an anchor vertex.",
        "As with SRB, supply vertex, size and the quoted PMP resource name."),
    "RECOLOR": N3CommandHelp(
        "RECOLOR", "name: RECOLOR (old:new, old:new, ...);",
        "Defines a set of numeric palette-index replacement pairs.",
        "Each pair maps one integer palette index to another. Separate pairs with commas."),
    "DYNO": N3CommandHelp(
        "DYNO", "name: DYNO {n1, n2, n3, n4};",
        "Stores four integer dynamic parameters in a DYNO node.",
        "The CAD compiler preserves the four values as a record; their broader "
        "gameplay semantics are not specified by this syntax."),
    "DATA": N3CommandHelp(
        "DATA", "name: DATA {integer1, integer2, ...};",
        "Stores an opaque integer payload.",
        "Used in some track and extended N3 records. This compiler preserves "
        "the supplied integers without assigning undocumented meanings."),
    "COMMENT": N3CommandHelp(
        "Comment", "% explanation or metadata",
        "Documents source without creating geometry.",
        "A line beginning with % is a comment. Recognized metadata includes "
        "% ICR2_ROOT: offset and % ICR2_OFFSET: offset in CAD exports."),
    "SCALE": N3CommandHelp(
        "ICR2_COORD_SCALE", "% ICR2_COORD_SCALE: 1",
        "Sets the multiplier used when compiling source XYZ coordinates.",
        "A positive value of 1 uses raw Papyrus units. Without this hint, "
        "fractional coordinates default to 6000 and integer coordinates to 1."),
    "OFFSET": N3CommandHelp(
        "ICR2_OFFSET", "% ICR2_OFFSET: 123",
        "Annotates a source statement with its original binary body offset.",
        "Used by conservative CAD binary patch-import. Standalone source "
        "compilation may assign new offsets when creating a new 3DO."),
    "ROOT_HINT": N3CommandHelp(
        "ICR2_ROOT", "% ICR2_ROOT: 123",
        "Records the original binary root-object offset.",
        "Annotated CAD export metadata. Standalone N3 normally uses "
        "the name root for the top-level render node."),
}

# Command order matters: specific prefixes precede broad categories.
_HEAD = re.compile(r"^[ \t]*[A-Za-z_][A-Za-z_0-9-]*[ \t]*:[ \t]*(.*)$", re.S)
_COMMAND = re.compile(r"^([A-Za-z_][A-Za-z_0-9-]*)\b", re.I)
_BSP = {"FACE", "FACE2", "BSPF", "BSPA", "BSP2", "BSPN"}
_MAX_CONTEXT_LINES = 48


def _no_comment(text: str) -> str:
    quoted = False
    for i, char in enumerate(text):
        if char == '"':
            quoted = not quoted
        elif char == "%" and not quoted:
            return text[:i]
    return text


def help_for_statement(statement: str) -> N3CommandHelp | None:
    """Find N3 command help from complete *or still-being-typed* source."""
    lines = statement.splitlines()
    if not lines:
        return None
    first = lines[0].strip()
    if first.startswith("%"):
        upper = first.upper()
        if re.match(r"%\s*ICR2_COORD_SCALE\b", upper):
            return COMMAND_HELP["SCALE"]
        if re.match(r"%\s*ICR2_OFFSET\b", upper):
            return COMMAND_HELP["OFFSET"]
        if re.match(r"%\s*ICR2_ROOT\b", upper):
            return COMMAND_HELP["ROOT_HINT"]
        return COMMAND_HELP["COMMENT"]
    clean = "\n".join(_no_comment(line) for line in lines).strip()
    if re.match(r"^3D(?:\s+VERSION)?\b", clean, re.I):
        return COMMAND_HELP["VERSION"]
    decl = _HEAD.match(clean)
    if decl is not None:
        clean = decl.group(1).lstrip()
        if not clean:
            return COMMAND_HELP["DECLARATION"]
    if re.match(r"^\[\s*<", clean, re.S):
        return COMMAND_HELP["VERTEX"]
    cmd = _COMMAND.match(clean)
    if cmd is None:
        return None
    name = cmd.group(1).upper()
    if name == "POLY":
        return COMMAND_HELP["POLY_T" if re.match(r"^POLY\s+\[T\]", clean, re.I) else "POLY"]
    if name == "SWITCH":
        return COMMAND_HELP["SWITCH"]
    if name in COMMAND_HELP:
        return COMMAND_HELP[name]
    return None


def help_for_lines(lines: list[str] | tuple[str, ...],
                   line: int) -> N3CommandHelp | None:
    """Help for the statement containing the specified zero-based line.

    Operates on a short sliding window in the GUI. Semicolons and new
    declarations bound the search: an empty line or comment cannot inherit
    a neighboring command's help. Multiline and unfinished commands work.
    """
    if not 0 <= line < len(lines):
        return None
    current = lines[line]
    if current.lstrip().startswith("%"):
        return help_for_statement(current)
    if not current.strip():
        return None
    beginning = max(0, line - _MAX_CONTEXT_LINES + 1)
    start = None
    for i in range(line, beginning - 1, -1):
        code = _no_comment(lines[i]).strip()
        if not code:
            if i == line:
                return None
            continue
        if i < line and ";" in code:
            break
        if _HEAD.match(code) or re.match(r"^3D\s+VERSION\b", code, re.I):
            start = i
            break
    if start is None:
        return None
    return help_for_statement("\n".join(lines[start:line + 1]))
