from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
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


def export_sg_to_csv(*, sg_path: Path) -> ExportResult:
    script_path = sg2csv_script_path()
    command = build_sg_to_csv_command(sg_path=sg_path)
    try:
        completed = subprocess.run(
            command,
            cwd=script_path.parent,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        error_output = stderr or stdout or str(exc)
        return ExportResult(
            success=False,
            message=f"SG saved but CSV export failed:\n{error_output}",
            stdout=stdout,
            stderr=stderr,
        )

    return ExportResult(
        success=True,
        message=f"Saved {sg_path} and exported CSVs next to it",
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


def export_sg_to_trk(*, sg_path: Path, trk_path: Path) -> ExportResult:
    script_path = sg2trk_script_path()
    command = build_sg_to_trk_command(sg_path=sg_path, trk_path=trk_path)
    try:
        completed = subprocess.run(
            command,
            cwd=script_path.parent,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        error_output = stderr or stdout or str(exc)
        return ExportResult(
            success=False,
            message=f"SG saved but TRK export failed:\n{error_output}",
            stdout=stdout,
            stderr=stderr,
        )

    if trk_path.exists():
        message = f"Saved TRK to {trk_path}"
    else:
        message = "TRK export completed."

    return ExportResult(
        success=True,
        message=message,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )
