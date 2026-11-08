"""Assemble the 1911 Marmon Wasp as three N3 objects with real DYNAMIC wheel references.

This is a packaging/placement adapter. Geometry is generated and compiled by the
repository's existing Stage 2 and CAD compiler; this module invents no binary bytes.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil

from .stage2 import validate_source, validate_path


# Raw Papyrus coordinates (6000 / foot).
# Both wheel variants are defined in their own local coordinates at (0,0,0).
# Indy 500 2011 published specifications: 116-inch wheelbase and 187-inch
# overall length. Wheels have 34-inch OD: radius = 8500 raw ICR2 units.
# Front wheel x=2300 raw, radiator face x=2340 raw (0.08 inch difference).
# Rear center x=60300 raw => 58000 / 6000 * 12 = exactly 116 inches.
# Front tire leading x=-6200 raw, tail tip x=87300 raw => 93500 raw
# / 6000 * 12 = exactly 187 inches. The length is a fit to the reported
# specification, whereas the radiator/axle overlap is based on side photos.
WHEEL_PLACEMENTS = (
    ("front_left", "FWHEEL", (2300, -17400, 8500)),
    ("front_right", "FWHEEL", (2300, 17400, 8500)),
    ("rear_left", "RWHEEL", (60300, -16800, 8500)),
    ("rear_right", "RWHEEL", (60300, 16800, 8500)),
)
NOMINAL_WHEELBASE_IN = 116
NOMINAL_OVERALL_IN = 187
FRONT_RADIATOR_RAW_X = 2340
BODY_TAIL_RAW_X = 87300
TIRE_RADIUS_RAW = 8500
ROOT_RE = re.compile(r"(?m)^root:\s*LIST\s*\{([^{}]*)\};[ \t]*$")


def assemble(body_dir: Path, front_dir: Path, rear_dir: Path, output: Path):
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite {output}")
    for directory in (body_dir, front_dir, rear_dir):
        if not (directory / "model.3D").is_file() or not (directory / "model.3do").is_file():
            raise FileNotFoundError(f"Expected validated Stage 2 model files in {directory}")

    body = (body_dir / "model.3D").read_text(encoding="utf-8")
    if "wheel_FL_locator" in body or "wheel_RL_locator" in body:
        raise ValueError("Body recipe still includes wheel cubes; remove them first")
    front_x = WHEEL_PLACEMENTS[0][2][0]
    rear_x = WHEEL_PLACEMENTS[2][2][0]
    wheelbase_in = (rear_x - front_x) / 6000 * 12
    length_in = (BODY_TAIL_RAW_X - (front_x - TIRE_RADIUS_RAW)) / 6000 * 12
    radiator_to_front_axle_in = (front_x - FRONT_RADIATOR_RAW_X) / 6000 * 12
    if abs(wheelbase_in - NOMINAL_WHEELBASE_IN) > 0.001:
        raise ValueError(f"Wheelbase mismatch: {wheelbase_in} inches")
    if abs(length_in - NOMINAL_OVERALL_IN) > 0.001:
        raise ValueError(f"Overall length mismatch: {length_in} inches")
    if abs(radiator_to_front_axle_in) > 1:
        raise ValueError("Front axle not aligned with radiator front")

    roots = list(ROOT_RE.finditer(body))
    if len(roots) != 1:
        raise ValueError(f"Expected one root LIST in body source, found {len(roots)}")

    m = roots[0]
    wheel_symbols = []
    placement_lines = []
    for name, target, (x, y, z) in WHEEL_PLACEMENTS:
        symbol = "wasp_" + name
        wheel_symbols.append(symbol)
        placement_lines.append(
            f'{symbol}: DYNAMIC {x}, {y}, {z}, 0, 0, 0, 1, EXTERN "{target}";'
        )

    existing = m.group(1).strip()
    new_root = f'root: LIST {{{existing}, {", ".join(wheel_symbols)}}};'
    wasp_text = (
        body[:m.start()] +
        '\n% Four wheel references; the two wheel meshes are external and shared.\n' +
        '\n'.join(placement_lines) + '\n' + new_root +
        body[m.end():]
    )

    # Real N3 compiler and parser verify all parent source records and external names.
    model, result = validate_source(wasp_text, model_path=output / "WASP.3D")
    if set(model.external_names) != {"FWHEEL", "RWHEEL"}:
        raise ValueError(f"Incorrect external filenames: {model.external_names}")
    if len(model.dynamics) != 4:
        raise ValueError(f"Expected four DYNAMIC wheel objects; found {len(model.dynamics)}")
    placements = {(tuple(obj.xyz), obj.name) for obj in model.dynamics.values()}
    expected = {(loc, ref) for _name, ref, loc in WHEEL_PLACEMENTS}
    if placements != expected:
        raise ValueError(f"Wrong wheel instance placements: {placements!r}")

    output.mkdir(parents=True, exist_ok=False)
    (output / "WASP.3D").write_text(wasp_text, encoding="utf-8")
    (output / "WASP.3do").write_bytes(model.raw)

    for obj_name, directory in (("FWHEEL", front_dir), ("RWHEEL", rear_dir)):
        shutil.copy2(directory / "model.3D", output / (obj_name + ".3D"))
        shutil.copy2(directory / "model.3do", output / (obj_name + ".3do"))

    checks = {}
    for name in ("WASP", "FWHEEL", "RWHEEL"):
        binary = output / (name + ".3do")
        check = validate_path(binary)
        if check["parser_warnings"]:
            raise RuntimeError(f"Parser warnings in {name}: {check['parser_warnings']}")
        checks[name] = check

    for recname, directory in (
        ("body_recipe.json", body_dir),
        ("front_wheel_recipe.json", front_dir),
        ("rear_wheel_recipe.json", rear_dir),
    ):
        shutil.copy2(directory / "recipe.json", output / recname)

    (output / "README.txt").write_text(
        "1911 MARMON WASP - THREE-OBJECT ICR2 N3 ASSEMBLY\n"
        "================================================\n"
        "Edit WASP.3D (main body), FWHEEL.3D (front wheel) and RWHEEL.3D (rear wheel).\n"
        "Place WASP.3do, FWHEEL.3do and RWHEEL.3do together in the same model folder.\n"
        "WASP.3do holds four DYNAMIC external references, two to each wheel model.\n"
        "No wheel cubes remain in the parent; wheels originate at their own axle center.\n"
        "Wheel positions, raw Papyrus units (6000 per foot):\n" +
        "".join(
            f"  {name}: {target} at {tuple(loc)}\n"
            for name, target, loc in WHEEL_PLACEMENTS
        ) +
        "Axles and leaf springs are body geometry, not separate wheel geometry.\n"
        "Body U-shaped cockpit walls are solid, made of five joined facets per side.\n"
        "Tire size 34x4.5 inches, steel wheel covers nominal 25 inches; polygonal.\n"
        "BSP, LOD and in-game renderer still require testing. No MIP textures.\n",
        encoding="utf-8",
    )
    manifest = {
        "description": "Marmon Wasp body plus external front and rear wheels",
        "wheel_placements": [
            {"name": name, "external": target, "translation_raw": list(loc)}
            for name, target, loc in WHEEL_PLACEMENTS
        ],
        "external_names": list(model.external_names),
        "dimensions": {
            "wheelbase_inches": wheelbase_in,
            "overall_length_inches": length_in,
            "radiator_front_to_front_axle_inches": radiator_to_front_axle_in,
            "documented_source": "INDYCAR/IMS 2011 centennial specifications",
            "radiator_axle_alignment": "photograph-guided estimate; not a published measurement",
        },
        "source_files": ["WASP.3D", "FWHEEL.3D", "RWHEEL.3D"],
        "binary_files": ["WASP.3do", "FWHEEL.3do", "RWHEEL.3do"],
        "validation": checks,
        "body_with_placements": result,
        "sha256": {
            p.name: sha256(p.read_bytes()).hexdigest()
            for p in output.iterdir() if p.suffix.lower() == ".3do"
        },
    }
    (output / "assembly_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--body", type=Path, required=True)
    ap.add_argument("--front", type=Path, required=True)
    ap.add_argument("--rear", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args(argv)
    result = assemble(args.body, args.front, args.rear, args.output)
    print(json.dumps({
        "components": "WASP+FWHEEL+RWHEEL",
        "binary_polygons": {name: r["polygons"] for name, r in result["validation"].items()},
        "external_names": result["external_names"],
        "placements": result["wheel_placements"],
    }, indent=2))


if __name__ == "__main__":
    main()
