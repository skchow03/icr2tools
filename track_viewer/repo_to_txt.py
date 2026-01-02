import datetime
from pathlib import Path

# ---------- Defaults ----------
OUTPUT_FILENAME = "repo_dump.txt"

EXCLUDES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
}

INCLUDE_EXTENSIONS = {
    ".py", ".md", ".txt", ".json", ".yaml", ".yml",
    ".ini", ".cfg", ".toml", ".csv"
}

MAX_FILE_SIZE_KB = 512

# ---------- Helpers ----------
def is_binary(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return b"\0" in f.read(1024)
    except Exception:
        return True

def should_exclude(path: Path, root: Path) -> bool:
    return any(part in EXCLUDES for part in path.relative_to(root).parts)

# ---------- Main ----------
def export_script_folder():
    root = Path(__file__).resolve().parent
    output = root / OUTPUT_FILENAME
    now = datetime.datetime.now().isoformat(timespec="seconds")

    with open(output, "w", encoding="utf-8", errors="replace") as out:
        out.write("=== REPO EXPORT ===\n")
        out.write(f"root: {root}\n")
        out.write(f"generated: {now}\n\n")

        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue

            if should_exclude(path, root):
                continue

            if path.suffix.lower() not in INCLUDE_EXTENSIONS:
                continue

            if is_binary(path):
                continue

            size_kb = path.stat().st_size / 1024
            if size_kb > MAX_FILE_SIZE_KB:
                continue

            rel = path.relative_to(root)

            out.write(f"\n--- FILE: {rel} ---\n")
            out.write(f"LANGUAGE: {path.suffix.lstrip('.') or 'unknown'}\n")
            out.write(f"SIZE: {path.stat().st_size:,} bytes\n")
            out.write("-" * 40 + "\n")

            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    out.write(f.read())
            except Exception as e:
                out.write(f"[ERROR READING FILE: {e}]\n")

            out.write("\n")

    print(f"Repo exported to: {output}")

if __name__ == "__main__":
    export_script_folder()
