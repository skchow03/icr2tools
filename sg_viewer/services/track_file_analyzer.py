"""Inventory and validate the files used by an ICR2 track."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct


# The playable-track checklist documented at https://skchow.com/indy/track-files/.
# Names containing ``{track}`` use the track directory's name.
REQUIRED_TRACK_FILES = (
    "{track}.3do",
    "{track}.trk",
    "{track}.txt",
    "sunny.pcx",
    "race.lp",
    "maxrace.lp",
    "minrace.lp",
    "pass1.lp",
    "pass2.lp",
    "pit.lp",
    "pace.lp",
)


@dataclass(frozen=True)
class AssetDetail:
    name: str
    size: int | None
    width: int | None = None
    height: int | None = None

    @property
    def missing(self) -> bool:
        return self.size is None


@dataclass(frozen=True)
class TrackFileAnalysis:
    folder: Path
    track_name: str
    required_missing: tuple[str, ...]
    three_do_files: tuple[AssetDetail, ...]
    mip_files: tuple[AssetDetail, ...]
    pmp_files: tuple[AssetDetail, ...]
    unused_mip_files: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def is_complete(self) -> bool:
        return not self.required_missing and not any(
            item.missing
            for item in (*self.three_do_files, *self.mip_files, *self.pmp_files)
        )

    def format_report(self) -> str:
        status = "COMPLETE" if self.is_complete else "INCOMPLETE"
        lines = [
            "ICR2 Track File Analysis",
            "=" * 24,
            f"Folder: {self.folder}",
            f"Track name: {self.track_name}",
            f"Completeness: {status}",
            "Checklist: https://skchow.com/indy/track-files/",
            "",
            "Required playable-track files",
            "-----------------------------",
        ]
        if self.required_missing:
            lines.extend(f"[MISSING] {name}" for name in self.required_missing)
        else:
            lines.append("All required files are present.")

        def add_assets(title: str, assets: tuple[AssetDetail, ...]) -> None:
            lines.extend(("", title, "-" * len(title)))
            if not assets:
                lines.append("None")
                return
            for asset in assets:
                if asset.missing:
                    lines.append(f"[MISSING] {asset.name}")
                elif asset.width is not None and asset.height is not None:
                    lines.append(
                        f"{asset.name}: {asset.width} x {asset.height}, {asset.size} bytes"
                    )
                else:
                    lines.append(f"{asset.name}: {asset.size} bytes")

        add_assets("Referenced 3DO files", self.three_do_files)
        add_assets("Referenced MIP files", self.mip_files)
        add_assets("Referenced PMP files", self.pmp_files)
        lines.extend(("", "Unused MIP files", "----------------"))
        lines.extend(self.unused_mip_files or ("None",))
        if self.warnings:
            lines.extend(("", "Warnings", "--------", *self.warnings))
        lines.extend(
            (
                "",
                "Totals",
                "------",
                f"3DO files: {len(self.three_do_files)}",
                f"MIP files: {len(self.mip_files)}",
                f"PMP files: {len(self.pmp_files)}",
                f"Unused MIP files: {len(self.unused_mip_files)}",
                "Referenced asset size: "
                f"{sum(a.size or 0 for a in (*self.three_do_files, *self.mip_files, *self.pmp_files))} bytes",
            )
        )
        return "\n".join(lines) + "\n"


def _file_map(folder: Path) -> dict[str, Path]:
    return {path.name.casefold(): path for path in folder.iterdir() if path.is_file()}


def _read_asset_names(path: Path) -> tuple[list[str], list[str], list[str]]:
    with path.open("rb") as stream:
        stream.seek(8)
        counts = stream.read(12)
        if len(counts) != 12:
            raise ValueError("header is shorter than 20 bytes")
        mip_count, pmp_count, three_do_count = struct.unpack("<III", counts)
        if any(count > 100_000 for count in (mip_count, pmp_count, three_do_count)):
            raise ValueError("header contains unreasonable asset counts")

        def names(count: int, suffix: str) -> list[str]:
            result = []
            for _ in range(count):
                raw = stream.read(8)
                if len(raw) != 8:
                    raise ValueError("asset table is truncated")
                stem = raw.split(b"\0", 1)[0].decode("latin1").strip()
                if stem and stem.isprintable():
                    result.append(stem + suffix)
            return result

        return names(mip_count, ".mip"), names(pmp_count, ".pmp"), names(three_do_count, ".3do")


def _detail(name: str, files: dict[str, Path], *, read_dimensions: bool = False) -> AssetDetail:
    path = files.get(name.casefold())
    if path is None:
        return AssetDetail(name=name, size=None)
    width = height = None
    if read_dimensions:
        try:
            with path.open("rb") as stream:
                stream.seek(8)
                raw = stream.read(8)
                if len(raw) == 8:
                    width, height = struct.unpack("<II", raw)
        except OSError:
            pass
    return AssetDetail(name=path.name, size=path.stat().st_size, width=width, height=height)


def analyze_track_folder(folder: Path | str) -> TrackFileAnalysis:
    """Analyze required files and recursively referenced 3DO/MIP/PMP assets."""
    folder = Path(folder).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError(f"Not a track folder: {folder}")
    track_name = folder.name
    files = _file_map(folder)
    required = tuple(name.format(track=track_name) for name in REQUIRED_TRACK_FILES)
    required_missing = tuple(name for name in required if name.casefold() not in files)

    root_names = [f"{track_name}.3do", "sky.3do", "horiz.3do"]
    pending = list(root_names)
    seen: set[str] = set()
    display_names: dict[str, str] = {}
    mip_names: set[str] = set()
    pmp_names: set[str] = set()
    warnings: list[str] = []
    while pending:
        requested = pending.pop(0)
        key = requested.casefold()
        if key in seen:
            continue
        seen.add(key)
        path = files.get(key)
        display_names[key] = path.name if path else requested
        if path is None:
            continue
        try:
            mips, pmps, children = _read_asset_names(path)
        except (OSError, ValueError, struct.error) as exc:
            warnings.append(f"Could not read {path.name}: {exc}")
            continue
        mip_names.update(mips)
        pmp_names.update(pmps)
        pending.extend(children)

    three_do = tuple(_detail(display_names[key], files) for key in sorted(seen))
    mips = tuple(_detail(name, files, read_dimensions=True) for name in sorted(mip_names, key=str.casefold))
    pmps = tuple(_detail(name, files) for name in sorted(pmp_names, key=str.casefold))
    used_mips = {name.casefold() for name in mip_names}
    unused = tuple(
        sorted(
            (path.name for key, path in files.items() if key.endswith(".mip") and key not in used_mips),
            key=str.casefold,
        )
    )
    return TrackFileAnalysis(folder, track_name, required_missing, three_do, mips, pmps, unused, tuple(warnings))
