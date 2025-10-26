import os

from icr2_core.trk.trk_classes import TRKFile
from icr2_core.dat.unpackdat import extract_file_bytes


def load_trk_from_folder(track_folder: str) -> TRKFile:
    # look for .DAT
    dat_files = [f for f in os.listdir(track_folder) if f.lower().endswith(".dat")]
    if dat_files:
        dat_path = os.path.join(track_folder, dat_files[0])
        trk_name = os.path.splitext(dat_files[0])[0] + ".TRK"
        raw = extract_file_bytes(dat_path, trk_name)
        return TRKFile.from_bytes(raw)

    # else, look for .TRK directly
    for f in os.listdir(track_folder):
        if f.lower().endswith(".trk"):
            return TRKFile.from_trk(os.path.join(track_folder, f))

    raise FileNotFoundError(f"No TRK or DAT file in {track_folder}")
