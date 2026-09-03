"""Live, text-based viewer for named ICR2 memory addresses.

Addresses in watches.ini are Ghidra image offsets. ICR2Memory translates them
to host addresses by adding the signature-derived EXE base.
"""

from __future__ import annotations

import argparse
import configparser
import csv
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

# Running this file directly puts only ``icr2timing`` on sys.path.  Add the
# repository root so the sibling ``icr2_core`` package can be imported.
if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from icr2_core.icr2_memory import ICR2Memory, WindowNotFoundError


SUPPORTED_TYPES = set(ICR2Memory.TYPE_MAP) | {"bytes"}


@dataclass(frozen=True)
class Watch:
    name: str
    ghidra_address: int
    type_name: str
    count: int
    display: str


def parse_int(value: str) -> int:
    """Parse 0x12, 12h, or decimal 18."""
    value = value.strip().replace("_", "")
    if value.lower().endswith("h"):
        return int(value[:-1], 16)
    return int(value, 0)


def load_watches(path: Path, version: str) -> list[Watch]:
    parser = configparser.ConfigParser(inline_comment_prefixes=(";", "#"))
    if not parser.read(path, encoding="utf-8"):
        raise FileNotFoundError(f"Watch file not found: {path}")

    watches: list[Watch] = []
    for name in parser.sections():
        section = parser[name]
        address_text = section.get(version, fallback="").strip()
        if not address_text:
            continue
        type_name = section.get("type", "u32").lower()
        if type_name not in SUPPORTED_TYPES:
            raise ValueError(f"[{name}] has unsupported type {type_name!r}")
        count = section.getint("count", fallback=1)
        if count < 1:
            raise ValueError(f"[{name}] count must be at least 1")
        watches.append(Watch(name, parse_int(address_text), type_name, count,
                             section.get("display", "auto").lower()))
    if not watches:
        raise ValueError(f"No watches in {path} define an address for {version}")
    return watches


def format_scalar(value, type_name: str, display: str) -> str:
    if type_name.startswith("f"):
        return f"{value:.6g}"
    if display == "hex":
        width = ICR2Memory.TYPE_MAP[type_name][1] * 2
        mask = (1 << (width * 4)) - 1
        return f"0x{int(value) & mask:0{width}X}"
    if display == "both" or display == "auto":
        width = ICR2Memory.TYPE_MAP[type_name][1] * 2
        mask = (1 << (width * 4)) - 1
        return f"{value} (0x{int(value) & mask:0{width}X})"
    return str(value)


def format_value(value, watch: Watch) -> str:
    if watch.type_name == "bytes":
        return value.hex(" ").upper()
    if watch.count == 1:
        return format_scalar(value, watch.type_name, watch.display)
    return "[" + ", ".join(format_scalar(v, watch.type_name, watch.display)
                            for v in value) + "]"


def append_changes(path: Path, version: str, changes: list[tuple[Watch, object]]) -> None:
    new_file = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if new_file:
            writer.writerow(("timestamp", "version", "name", "ghidra_address", "value"))
        stamp = datetime.now().isoformat(timespec="milliseconds")
        for watch, value in changes:
            writer.writerow((stamp, version, watch.name,
                             f"0x{watch.ghidra_address:X}", format_value(value, watch)))


def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def run(args: argparse.Namespace) -> int:
    version = args.version.upper()
    watches = load_watches(args.watches, version)
    keywords = [x.strip() for x in args.window_keywords.split(",") if x.strip()] or None

    with ICR2Memory(version=version, window_keywords=keywords, verbose=False) as memory:
        previous: dict[str, object] = {}
        while True:
            rows = []
            changes = []
            for watch in watches:
                try:
                    value = memory.read(watch.ghidra_address, watch.type_name, watch.count)
                    changed = watch.name in previous and previous[watch.name] != value
                    if changed:
                        changes.append((watch, value))
                    previous[watch.name] = value
                    rows.append((watch, value, changed, None))
                except Exception as exc:
                    rows.append((watch, None, False, str(exc)))

            if args.log and changes:
                append_changes(args.log, version, changes)

            clear_screen()
            print(f"ICR2 Memory Viewer | {version} | PID {memory.pid} | "
                  f"EXE base 0x{memory.exe_base:08X}")
            print(f"Updated {datetime.now().strftime('%H:%M:%S.%f')[:-3]} | "
                  f"Ctrl+C to quit | * changed since last poll")
            print("-" * 100)
            print(f"{' ':1} {'Name':30} {'Ghidra':12} {'Runtime':12} Value")
            for watch, value, changed, error in rows:
                runtime = memory.exe_base + watch.ghidra_address
                rendered = f"ERROR: {error}" if error else format_value(value, watch)
                print(f"{'*' if changed else ' ':1} {watch.name[:30]:30} "
                      f"0x{watch.ghidra_address:08X} 0x{runtime:08X} {rendered}")

            if args.once:
                return 0
            time.sleep(max(0.02, args.interval / 1000.0))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Monitor named ICR2 Ghidra addresses live")
    parser.add_argument("--version", choices=("DOS", "REND32A", "WINDY"),
                        help="ICR2 executable variant (defaults to settings.ini)")
    parser.add_argument("--watches", type=Path,
                        default=Path(__file__).with_name("watches.ini"))
    parser.add_argument("--interval", type=int, default=100,
                        help="Polling interval in milliseconds (default: 100)")
    parser.add_argument("--window-keywords", default="",
                        help="Comma-separated override for target window keywords")
    parser.add_argument("--log", type=Path,
                        help="Append changed values to this CSV file")
    parser.add_argument("--once", action="store_true", help="Read once and exit")
    return parser


def configured_version() -> str:
    settings = configparser.ConfigParser()
    settings.read(Path(sys.argv[0]).resolve().parent / "settings.ini")
    return settings.get("memory", "version", fallback="DOS").upper()


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.version = args.version or configured_version()
    try:
        return run(args)
    except (WindowNotFoundError, FileNotFoundError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"error: {exc}\n")
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
