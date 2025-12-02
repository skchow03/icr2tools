import os
from typing import Iterable

from icr2_core.trk.trk_classes import TRKFile
from icr2_core.dat.unpackdat import extract_file_bytes, list_dat_entries


def _choose_trk_entry(entry_names: Iterable[str], track_folder: str, dat_name: str) -> str | None:
    """Pick the most appropriate TRK entry name from ``entry_names``.

    Preference order:
    1. Track folder name (case-insensitive)
    2. .DAT file stem
    3. First available entry
    """

    folder_name = os.path.basename(track_folder).lower()
    dat_stem = os.path.splitext(dat_name)[0].lower()

    for candidate in entry_names:
        if os.path.splitext(candidate)[0].lower() == folder_name:
            return candidate

    for candidate in entry_names:
        if os.path.splitext(candidate)[0].lower() == dat_stem:
            return candidate

    return next(iter(entry_names), None)


def load_trk_from_folder(track_folder: str) -> TRKFile:
    # look for .DAT
    dat_files = [f for f in os.listdir(track_folder) if f.lower().endswith(".dat")]
    if dat_files:
        dat_name = dat_files[0]
        dat_path = os.path.join(track_folder, dat_name)
        entries = [name for name, _, _ in list_dat_entries(dat_path) if name.lower().endswith(".trk")]

        trk_name = _choose_trk_entry(entries, track_folder, dat_name)
        if trk_name:
            raw = extract_file_bytes(dat_path, trk_name)
            return TRKFile.from_bytes(raw)
        raise FileNotFoundError(f"No TRK entry in {dat_path}")

    # else, look for .TRK directly
    for f in os.listdir(track_folder):
        if f.lower().endswith(".trk"):
            return TRKFile.from_trk(os.path.join(track_folder, f))

    raise FileNotFoundError(f"No TRK or DAT file in {track_folder}")
