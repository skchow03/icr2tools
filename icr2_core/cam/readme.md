"""
# ICR2 Camera Tools

A simple Python utility for converting camera files in *IndyCar Racing 2* (`.scr` and `.cam`) to and from `.csv` format.

## File Structure
- `binutils.py`: Shared utilities for reading/writing 32-bit int binary files.
- `to_csv.py`: Functions for converting `.scr` and `.cam` files into CSV format.
- `from_csv.py`: Functions for converting CSVs back into `.scr` and `.cam` formats.

## Usage

```bash
# Convert .scr and .cam files to .csv
from to_csv import scr_to_csv, cam_to_csv
scr_to_csv('track.scr', 'scr.csv')
cam_to_csv('track.cam', 'cam.csv')

# Convert edited .csv files back to .scr and .cam
from from_csv import csv_to_scr, csv_to_cam
csv_to_scr('scr.csv', 'track.scr')
csv_to_cam('cam.csv', 'track.cam')
```

## Requirements
No external dependencies — uses only the Python standard library.

## License
MIT License — do whatever you want, just don't blame me if you crash into the Turn 1 wall.
"""
