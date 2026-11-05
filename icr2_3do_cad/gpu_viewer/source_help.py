"""Contextual, read-only syntax help for the N3 features supported by ICR2 CAD.

Based on n3_compile.Compiler._expression and text_3d.parse_document.
This is documentation only: no completion, source mutation, or compilation.
The pure helpers are intentionally independent of Qt for regression testing.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
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

    def tooltip_html(self, note: str = "") -> str:
        """Bound Qt's rich-text tooltip to a readable width (not screen-wide).

        A table with an explicit width is supported by Qt's QTextDocument
        rich-text layout; CSS max-width alone is not consistently honored by
        QToolTip on Windows. Escaping prevents N3 angle brackets, % comments
        and quoted filenames from being interpreted as markup.
        """
        heading = escape(self.name)
        description = escape(self.description)
        syntax = escape(self.syntax)
        detail = escape(self.detail)
        preface = f"<small>{escape(note)}</small><br/>" if note else ""
        return (
            '<table width="370" cellpadding="1" cellspacing="0" border="0">'
            '<tr><td width="370">'
            f'{preface}<b>{heading}</b>'
            f'<p>{description}</p>'
            f'<p><b>Syntax:</b> {syntax}</p>'
            f'<p>{detail}</p>'
            '</td></tr></table>'
        )


# FACE/BSP rules below follow the real Model.visible_polygons() ICR2 viewer
# traversal and the N3 compiler's text-to-binary child-slot permutation.
# Front = positive side of the oriented plane (v1 -> v2 -> v3).
# Distinguish being visited by a BSP branch from actual pixel visibility:
# occlusion and clipping can still hide a visited polygon. This is the CAD
# renderer's established behavior, not a bit-perfect claim about the game.
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
        "Solid palette-colored polygon; add [T] after POLY to make it textured.",
        "The color is a numeric palette index or a color-bearing vertex reference (p.c). "
        "Vertex order controls face orientation; the compiler closes an unclosed polygon automatically. "
        "To convert to textured: change POLY <42> {a,b,c} to POLY [T] <42> {a,b,c}; "
        "give every referenced vertex T=<U,V> coordinates and assign a texture via "
        "MATERIAL MIP=\"name\", GROUP=3, yourPoly (or an ancestor MATERIAL). "
        "Adding [T] alone does not supply UVs or a texture."),
    "POLY_T": N3CommandHelp(
        "POLY [T]", "name: POLY [T] <color> {v1, v2, v3, ...};",
        "Textured polygon; remove [T] after POLY to make it solid.",
        "Each referenced vertex needs T=<U,V>; a MATERIAL MIP=\"name\" wrapper "
        "(or a parent material) assigns the bitmap. Vertex winding still matters. "
        "To convert to solid: change POLY [T] <42> {a,b,c} to POLY <42> {a,b,c}; "
        "the <42> palette color is then used. Existing T=<U,V> on vertices can remain; "
        "they are ignored by this solid polygon. Remove or adjust the MIP MATERIAL "
        "wrapper only if it is no longer needed by other textured children."),
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
        "One-sided face: visit its child only from the front of the plane.",
        "Use for a surface that should disappear from behind, such as an exterior "
        "building wall or ground face. The winding v1 -> v2 -> v3 determines the "
        "front/positive side; from the back the child is culled. "
        "Points may be named vertices or inline [<X,Y,Z>]."),
    "FACE2": N3CommandHelp(
        "FACE2", "name: FACE2 (v1, v2, v3), frontChild, backChild;",
        "Two-sided face: draw one child from the front and another from behind.",
        "From the front/positive side, visit the first child; from the back/negative "
        "side, visit the second. Use the same child in both slots to show the "
        "same face on both sides, or different children for different front/back "
        "appearances (e.g. a sign). NIL hides the corresponding side. "
        "The three plane points set which direction is front."),
    "BSPF": N3CommandHelp(
        "BSPF", "name: BSPF (v1, v2, v3), child1, frontFace, child3;",
        "BSP sorting with a one-sided face: the middle child draws only from the front.",
        "Use for solid objects where back-facing surfaces should disappear "
        "(e.g. an exterior wall of a house). From the front, traversal is "
        "child3 -> frontFace -> child1. From behind, frontFace is culled and "
        "traversal is child1 -> child3. Thus the first and third children "
        "are visited from both sides, but the second is front-only. "
        "The plane's positive/front side comes from v1 -> v2 -> v3 winding; "
        "select the statement to see those arrows in the viewport."),
    "BSPA": N3CommandHelp(
        "BSPA", "name: BSPA (v1, v2, v3), child1, child2, child3;",
        "Three-child BSP sorter: all three children are visited from either side.",
        "Unlike BSPF, BSPA does not cull its middle child when seen from "
        "behind. From the front, traversal is child3 -> child2 -> child1; "
        "from the back it is child1 -> child2 -> child3. Use when three "
        "parts need view-dependent painter order, not one-sided hiding. "
        "Other FACE/BSP nodes inside these children may still cull geometry."),
    "BSP2": N3CommandHelp(
        "BSP2", "name: BSP2 (v1, v2, v3), far, backFace, frontFace, shared;",
        "Four-child BSP: choose different front/back faces while sorting other parts.",
        "Useful when a surface has a different appearance on each side, "
        "with other geometry still present. In N3 source order: child1=far "
        "subtree, child2=back-facing surface, child3=front-facing surface, "
        "child4=shared/continuing subtree. From the front, visit child1, "
        "child4, child3 (skip child2); from behind visit child2, child4, "
        "child1 (skip child3). NIL may be used for unused slots. "
        "This is the CAD viewer's current traversal behavior."),
    "BSPN": N3CommandHelp(
        "BSPN", "name: BSPN (v1, v2, v3), child1, child2;",
        "Two-child BSP sorter: both children are visited from both sides.",
        "Use to change draw order as the viewpoint crosses a plane, "
        "without hiding either child. From the front, visit child2 then "
        "child1; from behind, visit child1 then child2. This is a common "
        "solution for nearby objects whose front-to-back order reverses. "
        "Children may still contain their own one-sided FACE/BSP nodes."),
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
