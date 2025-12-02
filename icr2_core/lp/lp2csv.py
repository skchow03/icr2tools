from __future__ import annotations

import argparse
from pathlib import Path

from icr2_core.lp.loader import LpData, load_lp_file, records_to_rows
from icr2_core.trk.trk_classes import TRKFile


def write_csv(output_file: Path, lp_data: LpData) -> None:
    print(f"Writing to {output_file} - {lp_data.num_records} records")
    with output_file.open("w") as o:
        o.write("DLONG,LP speed,Coriolis,DLAT\n")
        for row in records_to_rows(lp_data.records):
            o.write(f"{row[0]},{row[1]},{row[2]},{row[3]}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="ICR2 .LP to .CSV converter v2.5")
    parser.add_argument("LP_file", help="input .LP file")
    parser.add_argument("TRK_file", help="input .trk file")
    parser.add_argument("CSV_file", help="output .CSV file")

    args = parser.parse_args()

    input_file = Path(args.LP_file)
    output_file = Path(args.CSV_file)
    trkfile = Path(args.TRK_file)

    print(f"Loading track file {trkfile}")
    trk = TRKFile.from_trk(trkfile)

    lp_data = load_lp_file(input_file, track_length=trk.trklength)
    write_csv(output_file, lp_data)


if __name__ == "__main__":
    main()
