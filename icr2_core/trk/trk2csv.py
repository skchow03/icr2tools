from __future__ import annotations

from pathlib import Path
import sys

import numpy as np


def convert_trk_to_csv(trk_file: Path, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    trk_name = trk_file.stem
    base_path = output_dir / trk_name
    arr = np.fromfile(trk_file, dtype=np.int32)
    output_files: list[Path] = []

    raw_path = base_path.with_name(f"{trk_name}-0-raw.csv")
    np.savetxt(raw_path, arr.reshape((len(arr), 1)), delimiter=",", fmt="%i")
    output_files.append(raw_path)

    # Read and write header
    header = arr[:7]
    (
        _file_type,
        _version,
        _track_length,
        num_xsects,
        num_sects,
        fsects_bytes,
        sect_data_bytes,
    ) = header
    header_labels = [
        "type",
        "unknown1",
        "track_length",
        "number_of_xsects",
        "number_of_sects",
        "byte_length_fsects",
        "byte_length_sect_data",
    ]

    header_path = base_path.with_name(f"{trk_name}-1-header.csv")
    with open(header_path, "w") as output:
        output.write(",".join(header_labels) + "\n")
        output.write(",".join(map(str, header)) + "\n")
    output_files.append(header_path)

    # Read and write xsects DLATs
    xsects = arr[7:17]
    xsect_dlat_path = base_path.with_name(f"{trk_name}-2-xsect_dlats.csv")
    with open(xsect_dlat_path, "w") as output:
        output.write("xsect,dlat\n")
        for i, xsect in enumerate(xsects):
            output.write(f"{i},{xsect}\n")
    output_files.append(xsect_dlat_path)

    # Calculate and write section offsets
    sect_offsets_end = 17 + num_sects
    sect_offsets = arr[17:sect_offsets_end].tolist()
    sect_offsets = [int(x / 4) for x in sect_offsets]
    sect_offsets.append(int(sect_data_bytes / 4))

    sect_offsets_path = base_path.with_name(f"{trk_name}-3-sect_offsets.csv")
    with open(sect_offsets_path, "w") as output:
        output.write("sect,sect_offset\n")
        for i, sect_offset in enumerate(sect_offsets[:-1]):
            output.write(f"{i},{sect_offset}\n")
    output_files.append(sect_offsets_path)

    # Xsect data
    xsect_data_end = sect_offsets_end + 8 * num_sects * num_xsects
    xsect_data = arr[sect_offsets_end:xsect_data_end]
    xsect_data = xsect_data.reshape((num_sects * num_xsects, 8))
    xsect_path = base_path.with_name(f"{trk_name}-4-xsect.csv")
    with open(xsect_path, "w") as output:
        output.write(
            "sect, xsect, grade1, grade2, grade3, alt, grade4, grade5, pos1, pos2\n"
        )
        c = 0
        for i in range(0, num_sects):
            for j in range(0, num_xsects):
                output.write(f"{i},{j}")
                for k in range(0, 8):
                    output.write(f",{xsect_data[c][k]}")
                output.write("\n")
                c += 1
    output_files.append(xsect_path)

    # fsects ground
    fsects_data_end = int(xsect_data_end + fsects_bytes / 4)
    fsects_data = arr[xsect_data_end:fsects_data_end].reshape((-1, 3))

    # section data
    sects_data = arr[fsects_data_end:]

    sects_data_path = base_path.with_name(f"{trk_name}-6-sects_data.csv")
    fsect_ground_path = base_path.with_name(f"{trk_name}-5-fsect-ground.csv")
    with open(sects_data_path, "w") as output_sects:
        output_sects.write(
            "sect,type,start_dlong,length,heading,ang1,ang2,ang3,ang4,ang5,unknown_counter,"
            "ground_fsects,ground_counter,num_wall_fsects"
        )
        for i in range(0, 10):
            output_sects.write(
                f",boundary{i}_type,boundary{i}_dlat_start,boundary{i}_dlat_end,"
                "placeholder1,placeholder2"
            )
        output_sects.write("\n")

        with open(fsect_ground_path, "w") as output_fsects:
            output_fsects.write("sect,fsect_start, fsect_end, fsect_ground_type\n")

            fsect_index = 0

            for i in range(num_sects):
                sect_start = sect_offsets[i]
                sect_end = sect_offsets[i + 1]
                cur_sect = sects_data[sect_start:sect_end]
                num_ground_fsects = cur_sect[10]
                output_sects.write(f"{i},")
                output_sects.write(",".join(map(str, cur_sect)) + "\n")

                for _ in range(num_ground_fsects):
                    output_fsects.write(f"{i},")
                    fsect = fsects_data[fsect_index]
                    output_fsects.write(",".join(map(str, fsect)) + "\n")
                    fsect_index += 1
    output_files.extend([fsect_ground_path, sects_data_path])

    return output_files


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python trk2csv.py <TRK file>")
        return 1

    trk_file = Path(sys.argv[1])
    convert_trk_to_csv(trk_file, trk_file.parent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

            
