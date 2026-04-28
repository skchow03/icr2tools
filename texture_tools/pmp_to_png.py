"""
pmp_to_png.py

Converts Papyrus ICR2 PMP sprite files to transparent PNGs.

Usage:
    python pmp_to_png.py input.pmp output.png SUNNY.PCX

Optional:
    python pmp_to_png.py input.pmp output.png SUNNY.PCX --crop

Requires:
    pip install pillow
"""

import argparse
from pathlib import Path
from PIL import Image


def load_palette(path: str):
    """
    Loads a 256-color palette from a PCX file or a raw 768-byte palette file.
    """

    path_obj = Path(path)
    suffix = path_obj.suffix.lower()

    if suffix == ".pcx":
        pcx = Image.open(path)

        raw_palette = pcx.getpalette()

        if raw_palette is None:
            raise ValueError(f"No palette found in PCX file: {path}")

        if len(raw_palette) < 768:
            raise ValueError(f"PCX palette is too small: {len(raw_palette)} values")

        palette = []

        for i in range(256):
            r = raw_palette[i * 3]
            g = raw_palette[i * 3 + 1]
            b = raw_palette[i * 3 + 2]
            palette.append((r, g, b, 255))

        return palette

    with open(path, "rb") as f:
        data = f.read()

    if len(data) < 768:
        raise ValueError(
            f"Palette file is too small: {len(data)} bytes. Expected at least 768."
        )

    raw = data[:768]

    max_value = max(raw)
    scale_vga = max_value <= 63

    palette = []

    for i in range(256):
        r = raw[i * 3]
        g = raw[i * 3 + 1]
        b = raw[i * 3 + 2]

        if scale_vga:
            r = round(r * 255 / 63)
            g = round(g * 255 / 63)
            b = round(b * 255 / 63)

        palette.append((r, g, b, 255))

    return palette


def parse_pmp(path: str):
    with open(path, "rb") as f:
        data = f.read()

    if len(data) < 12:
        raise ValueError("File is too small to be a valid PMP.")

    width = data[0]
    height = data[1]

    unknown_2 = data[2]
    unknown_3 = data[3]

    declared_run_data_size = int.from_bytes(data[4:8], "little")
    unknown_8_to_11 = data[8:12]

    run_data = data[12:]

    if len(run_data) % 4 != 0:
        print(f"Warning: run data is not divisible by 4: {len(run_data)} bytes")

    if declared_run_data_size != len(run_data):
        print(
            f"Warning: declared run data size is {declared_run_data_size}, "
            f"but actual run data size is {len(run_data)}"
        )

    runs = []
    max_x = 0
    max_y = 0
    bad_run_count = 0

    for i in range(0, len(run_data) - 3, 4):
        y = run_data[i]
        x_start = run_data[i + 1]
        x_end_exclusive = run_data[i + 2]
        color_index = run_data[i + 3]

        if x_start > x_end_exclusive:
            bad_run_count += 1
            continue

        runs.append((y, x_start, x_end_exclusive, color_index))

        max_y = max(max_y, y)
        max_x = max(max_x, x_end_exclusive)

    metadata = {
        "width": width,
        "height": height,
        "unknown_2": unknown_2,
        "unknown_3": unknown_3,
        "declared_run_data_size": declared_run_data_size,
        "actual_run_data_size": len(run_data),
        "unknown_8_to_11_hex": unknown_8_to_11.hex(" "),
        "run_count": len(runs),
        "bad_run_count": bad_run_count,
        "max_used_x_exclusive": max_x,
        "max_used_y_inclusive": max_y,
    }

    return metadata, runs


def convert_pmp_to_png(
    pmp_path: str,
    png_path: str,
    palette_path: str,
    crop: bool = False,
):
    palette = load_palette(palette_path)
    metadata, runs = parse_pmp(pmp_path)

    width = metadata["width"]
    height = metadata["height"]

    if width == 0 or height == 0:
        raise ValueError(f"Invalid PMP dimensions: {width}x{height}")

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pixels = img.load()

    skipped_out_of_bounds = 0

    for y, x_start, x_end_exclusive, color_index in runs:
        if y >= height:
            skipped_out_of_bounds += 1
            continue

        if x_start >= width:
            skipped_out_of_bounds += 1
            continue

        clipped_x_start = max(0, x_start)
        clipped_x_end = min(x_end_exclusive, width)

        if clipped_x_start >= clipped_x_end:
            skipped_out_of_bounds += 1
            continue

        rgba = palette[color_index]

        for x in range(clipped_x_start, clipped_x_end):
            pixels[x, y] = rgba

    if crop:
        bbox = img.getbbox()
        if bbox:
            img = img.crop(bbox)

    img.save(png_path)

    print("Converted PMP to PNG")
    print(f"Input:   {pmp_path}")
    print(f"Output:  {png_path}")
    print(f"Palette: {palette_path}")
    print()
    print("PMP metadata:")
    for key, value in metadata.items():
        print(f"  {key}: {value}")

    if skipped_out_of_bounds:
        print(f"Warning: skipped {skipped_out_of_bounds} out-of-bounds runs")


def main():
    parser = argparse.ArgumentParser(
        description="Convert ICR2 PMP sprite files to transparent PNG."
    )

    parser.add_argument("input_pmp", help="Input PMP file")
    parser.add_argument("output_png", help="Output PNG file")
    parser.add_argument("palette", help="Palette source, usually SUNNY.PCX")
    parser.add_argument(
        "--crop",
        action="store_true",
        help="Crop transparent border around sprite after conversion",
    )

    args = parser.parse_args()

    input_pmp = Path(args.input_pmp)
    output_png = Path(args.output_png)
    palette = Path(args.palette)

    if not input_pmp.exists():
        raise FileNotFoundError(f"Input PMP not found: {input_pmp}")

    if not palette.exists():
        raise FileNotFoundError(f"Palette file not found: {palette}")

    convert_pmp_to_png(
        str(input_pmp),
        str(output_png),
        str(palette),
        crop=args.crop,
    )


if __name__ == "__main__":
    main()