from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys


@dataclass(frozen=True)
class ExportResult:
    success: bool
    message: str
    stdout: str = ""
    stderr: str = ""


def sg2csv_script_path() -> Path:
    return Path(__file__).resolve().parents[2] / "icr2_core" / "trk" / "sg2csv.py"


def sg2trk_script_path() -> Path:
    return Path(__file__).resolve().parents[2] / "icr2_core" / "trk" / "sg2trk.py"


def build_sg_to_csv_command(*, sg_path: Path) -> list[str]:
    return [sys.executable, str(sg2csv_script_path()), str(sg_path)]


def build_sg_to_trk_command(*, sg_path: Path, trk_path: Path) -> list[str]:
    return [
        sys.executable,
        str(sg2trk_script_path()),
        str(sg_path),
        "--format",
        "trk",
        "--output",
        str(trk_path.with_suffix("")),
    ]


def _load_sg_class():
    from icr2_core.trk.sg_classes import SGFile

    return SGFile


def _load_trk_export_dependencies():
    from icr2_core.trk.trk_classes import TRKFile
    from icr2_core.trk.trk_exporter import write_trk

    return TRKFile, write_trk


def export_sg_to_csv(*, sg_path: Path) -> ExportResult:
    try:
        sg_class = _load_sg_class()
        sgfile = sg_class.from_sg(str(sg_path))
        sgfile.output_sg_sections(str(sg_path) + "_sects.csv")
        sgfile.output_sg_header_xsects(str(sg_path) + "_header_xsects.csv")
    except Exception as exc:
        return ExportResult(success=False, message=f"SG saved but CSV export failed:\n{exc}")

    return ExportResult(success=True, message=f"Saved {sg_path} and exported CSVs next to it")


def export_sg_to_trk(*, sg_path: Path, trk_path: Path) -> ExportResult:
    try:
        trk_class, write_trk = _load_trk_export_dependencies()
        trk_file = trk_class.from_sg(str(sg_path))
        write_trk(trk_file, str(trk_path))
    except Exception as exc:
        return ExportResult(success=False, message=f"SG saved but TRK export failed:\n{exc}")

    if trk_path.exists():
        message = f"Saved TRK to {trk_path}"
    else:
        message = "TRK export completed."

    return ExportResult(success=True, message=message)
