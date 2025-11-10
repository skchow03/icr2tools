import os

from icr2_core.trk.trk_classes import TRKFile
from icr2_core.dat.unpackdat import extract_file_bytes


def load_trk_from_folder(track_folder: str) -> TRKFile:
    folder_name = os.path.basename(os.path.normpath(track_folder))
    folder_name_lower = folder_name.lower()

    # look for a .DAT that matches the folder name
    for entry in os.listdir(track_folder):
        if entry.lower() == f"{folder_name_lower}.dat":
            dat_path = os.path.join(track_folder, entry)
            trk_name = f"{folder_name}.TRK"
            raw = extract_file_bytes(dat_path, trk_name)
            return TRKFile.from_bytes(raw)

    # else, look for a .TRK directly that matches the folder name
    for entry in os.listdir(track_folder):
        if entry.lower() == f"{folder_name_lower}.trk":
            return TRKFile.from_trk(os.path.join(track_folder, entry))

    raise FileNotFoundError(
        f"No TRK or DAT file matching folder name in {track_folder}"
    )
