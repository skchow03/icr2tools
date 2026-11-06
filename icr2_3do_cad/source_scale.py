"""Pure, conservative uniform scaling of editable Papyrus N3 source.

The scale pivot is model origin (0,0,0). Unlike changing the compiler's
ICR2_COORD_SCALE hint, this edits authored geometry coordinates. Keep UVs,
palette indices, rotations, names, material assignments and comments intact.
All edits are planned and range-checked before any Qt document is modified.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
import re
import struct

from n3_compile import _source_coordinate_scale
from text_3d import parse_document
from three_do import INT32_HI, INT32_LO, INT64_HI, INT64_LO


_NUM = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
_XYZ = re.compile(r"\[\s*<\s*("+_NUM+r")\s*,\s*("+_NUM+r")\s*,\s*("+_NUM+r")\s*>", re.S)
_DYNAMIC = re.compile(
    r"\bDYNAMIC\s+("+_NUM+r")\s*,\s*("+_NUM+r")\s*,\s*("+_NUM+r")\s*,",
    re.I | re.S)
_SPRITE = re.compile(
    r"\b(?:SRB|PMP2)\s+[A-Za-z_][A-Za-z_0-9-]*\s*,\s*("+_NUM+r")\s*,",
    re.I | re.S)
_SWITCH = re.compile(
    r"\bSWITCH\s+DISTANCE\s*\([^)]*\)\s*>\s*\{([^}]*)\}",
    re.I | re.S)
_THRESHOLD = re.compile(r"\(\s*([-+]?\d+)\s*\?")
_PLANE5 = re.compile(
    r"\b(?:FACE2?|BSPF|BSPA|BSP2|BSPN)\s*\(\s*"
    + r"([-+]?\d+)\s*,\s*" * 4 + r"([-+]?\d+)\s*\)", re.I | re.S)
_EXPLICIT_SCALE = re.compile(r"(?m)^\s*%\s*ICR2_COORD_SCALE\s*:", re.I)
_HEADER = re.compile(r"(?m)^([ \t]*3D[ \t]+VERSION[ \t]+3\.0[ \t]*;[^\r\n]*)(\r?\n|$)", re.I)


@dataclass(frozen=True)
class ScaleResult:
    source: str
    multiplier: Decimal
    xyz_values: int
    dynamic_values: int
    sprite_sizes: int
    lod_distances: int
    raw_planes: int
    inserted_scale_hint: bool

    @property
    def points(self) -> int:
        return self.xyz_values // 3

    def summary(self) -> str:
        # Dynamic triples and raw plane coefficients are reported separately.
        return (f"Uniform scale ×{self.multiplier}: {self.points} XYZ points, "
                f"{self.dynamic_values // 3} DYNAMIC positions, "
                f"{self.sprite_sizes} sprite sizes, "
                f"{self.lod_distances} SWITCH distances, "
                f"{self.raw_planes} raw plane equations")


def scale_multiplier(value, *, divide=False) -> Decimal:
    """Validate an exact positive decimal factor (never binary float math)."""
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Enter a positive numeric scale factor.") from exc
    if not number.is_finite() or number <= 0:
        raise ValueError("The scale factor must be positive and finite.")
    if number > Decimal("1e12") or number < Decimal("1e-12"):
        raise ValueError("Use a factor between 0.000000000001 and 1000000000000.")
    with localcontext() as ctx:
        ctx.prec = 65
        return Decimal(1) / number if divide else number


def _mask_comments_and_strings(source: str) -> str:
    """Keep offsets stable, but ignore strings and % comments while finding geometry."""
    chars = list(source)
    quoted = False
    comment = False
    for i, char in enumerate(source):
        if char in "\r\n":
            comment = False
            continue
        if comment:
            chars[i] = " "
        elif char == '"':
            quoted = not quoted
            chars[i] = " "
        elif char == "%" and not quoted:
            comment = True
            chars[i] = " "
        elif quoted:
            chars[i] = " "
    return "".join(chars)


def _format_decimal(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return "0" if rendered in ("-0", "") else rendered


def scale_n3_source(source: str, factor, *, divide=False) -> ScaleResult:
    """Scale geometric distances by an exact multiplier; return one complete edit.

    - [<X,Y,Z>] triples: all named vertices and inline plane/vertex operands
    - DYNAMIC XYZ positions, sprite sizes, SWITCH DISTANCE thresholds
    - raw five-word FACE/BSP plane *constant* (signed 64-bit D) while leaving
      its three normal components untouched, to preserve its plane
    - integer Papyrus coordinates rounded once, half-to-even, not reinterpreted
      as fractional feet; an implicit fractional scale of 6000 is pinned via
      an explicit source hint before it can change during recompilation

    No text is changed on invalid scaling, missing vectors or overflow.
    """
    multiplier = scale_multiplier(factor, divide=divide)
    if multiplier == 1:
        raise ValueError("A scale factor of 1 would not change the model.")
    try:
        parsed = parse_document(source, require_offsets=False)
        original_scale = _source_coordinate_scale(source, parsed.statements)
    except Exception as exc:
        raise ValueError(f"Scale requires valid N3 source: {exc}") from exc
    masked = _mask_comments_and_strings(source)
    edits = []
    xyz_values = dynamic_values = sprite_sizes = lod_distances = raw_planes = 0

    def replace_span(start, end, rendered):
        if source[start:end] != rendered:
            edits.append((start, end, rendered))

    with localcontext() as ctx:
        ctx.prec = 65

        def xyz_token(match, index):
            start, end = match.span(index)
            original = Decimal(source[start:end])
            raw = int((original * original_scale * multiplier).to_integral_value(
                rounding=ROUND_HALF_EVEN))
            if not INT32_LO <= raw <= INT32_HI:
                raise ValueError(
                    f"Scaled coordinate {source[start:end]} exceeds signed "
                    "32-bit Papyrus XYZ range; reduce the scale factor.")
            # 12 fractional digits are enough to round-trip raw integer units
            # for any supported positive ICR2_COORD_SCALE <= 1,000,000.
            authored = (Decimal(raw) / original_scale).quantize(
                Decimal("0.000000000001"))
            replace_span(start, end, _format_decimal(authored))

        for match in _XYZ.finditer(masked):
            for i in (1, 2, 3):
                xyz_token(match, i)
                xyz_values += 1

        for match in _DYNAMIC.finditer(masked):
            for i in (1, 2, 3):
                xyz_token(match, i)
                dynamic_values += 1

        def int_quantity(start, end, *, name, nonzero=False):
            before = Decimal(source[start:end])
            number = int((before * multiplier).to_integral_value(
                rounding=ROUND_HALF_EVEN))
            if not INT32_LO <= number <= INT32_HI:
                raise ValueError(f"Scaled {name} exceeds signed 32-bit range.")
            if nonzero and before != 0 and number == 0:
                raise ValueError(
                    f"Scale factor makes a {name} become zero; "
                    "use a larger result to preserve model behavior.")
            replace_span(start, end, str(number))

        for match in _SPRITE.finditer(masked):
            start, end = match.span(1)
            int_quantity(start, end, name="sprite size", nonzero=True)
            sprite_sizes += 1

        for switch in _SWITCH.finditer(masked):
            content_start = switch.start(1)
            for match in _THRESHOLD.finditer(masked[switch.start(1):switch.end(1)]):
                start, end = content_start + match.start(1), content_start + match.end(1)
                before = int(source[start:end])
                if before != 0:  # zero is the required terminal branch
                    int_quantity(start, end, name="SWITCH distance", nonzero=True)
                    lod_distances += 1

        for match in _PLANE5.finditer(masked):
            words = tuple(int(match.group(i)) for i in range(1, 6))
            if any(not INT32_LO <= value <= INT32_HI for value in words):
                raise ValueError("Raw plane coefficients must fit signed 32-bit words.")
            offset = struct.unpack("<q", struct.pack("<ii", *words[3:]))[0]
            scaled = int((Decimal(offset) * multiplier).to_integral_value(
                rounding=ROUND_HALF_EVEN))
            if not INT64_LO <= scaled <= INT64_HI:
                raise ValueError("Scaled raw FACE/BSP plane constant exceeds signed 64-bit range.")
            lo, hi = struct.unpack("<ii", struct.pack("<q", scaled))
            replace_span(*match.span(4), str(lo))
            replace_span(*match.span(5), str(hi))
            raw_planes += 1

    if xyz_values == 0 and dynamic_values == 0:
        raise ValueError("This source contains no N3 vertex or XYZ coordinates to scale.")

    # All edits must be nonoverlapping, preserving comments, UV and metadata.
    edits.sort(key=lambda item: item[0])
    if any(left[1] > right[0] for left, right in zip(edits, edits[1:])):
        raise ValueError("Overlapping geometry expressions; model was not changed.")
    output = source
    for start, end, value in reversed(edits):
        output = output[:start] + value + output[end:]

    inserted_hint = (original_scale != 1 and
                     not _EXPLICIT_SCALE.search(source))
    if inserted_hint:
        header = _HEADER.search(output)
        if header is None:
            raise ValueError("Cannot insert the coordinate-scale hint: missing 3D VERSION header.")
        nl = "\r\n" if "\r\n" in output else "\n"
        # Inserting after the header preserves the N3 compiler's original
        # 6000-unit interpretation even if scaling removes all fractions.
        location = header.end(1)
        if header.group(2):
            location = header.end()
            output = output[:location] + f"% ICR2_COORD_SCALE: {_format_decimal(original_scale)}{nl}" + output[location:]
        else:
            output = output[:location] + nl + f"% ICR2_COORD_SCALE: {_format_decimal(original_scale)}" + output[location:]

    return ScaleResult(output, multiplier, xyz_values, dynamic_values,
                       sprite_sizes, lod_distances, raw_planes, inserted_hint)
