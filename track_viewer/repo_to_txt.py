import datetime
import re
from pathlib import Path
from typing import List, Dict

# ---------- Defaults ----------
OUTPUT_FILENAME = "repo_dump_v2.txt"

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

MAX_CHUNK_LINES = 400

# ---------- Helpers ----------
def is_binary(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return b"\0" in f.read(1024)
    except Exception:
        return True

def should_exclude(path: Path, root: Path) -> bool:
    return any(part in EXCLUDES for part in path.relative_to(root).parts)

def count_lines(path: Path) -> int:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0

def extract_python_symbols(text: str) -> Dict[str, List[str]]:
    classes = sorted(set(re.findall(r"^class\s+([A-Za-z_][A-Za-z0-9_]*)", text, re.M)))
    functions = sorted(set(re.findall(r"^def\s+([A-Za-z_][A-Za-z0-9_]*)", text, re.M)))
    imports = sorted(set(re.findall(r"^(?:from|import)\s+([A-Za-z0-9_\.]+)", text, re.M)))
    return {
        "classes": classes,
        "functions": functions,
        "imports": imports,
    }

def extract_markdown_headings(text: str) -> List[str]:
    return sorted(set(re.findall(r"^(#+)\s+(.*)", text, re.M)))

def extract_top_level_keys(text: str) -> List[str]:
    return sorted(set(re.findall(r"^\s*([A-Za-z0-9_\-]+)\s*:", text, re.M)))

def chunk_text(lines: List[str], max_lines: int):
    for i in range(0, len(lines), max_lines):
        yield i + 1, min(i + max_lines, len(lines)), lines[i:i + max_lines]

# ---------- Main ----------
def export_repo():
    root = Path(__file__).resolve().parent
    output = root / OUTPUT_FILENAME
    now = datetime.datetime.now().isoformat(timespec="seconds")

    files = []
    file_id = 1

    # First pass: collect metadata
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if should_exclude(path, root):
            continue
        if path.suffix.lower() not in INCLUDE_EXTENSIONS:
            continue
        if is_binary(path):
            continue

        rel = path.relative_to(root)
        size = path.stat().st_size
        lines = count_lines(path)

        files.append({
            "id": file_id,
            "path": rel,
            "suffix": path.suffix.lower(),
            "size": size,
            "lines": lines,
            "path_obj": path,
        })
        file_id += 1

    with open(output, "w", encoding="utf-8", errors="replace") as out:
        # ---------- Header ----------
        out.write("=== REPO EXPORT V2 ===\n")
        out.write(f"root: {root}\n")
        out.write(f"generated: {now}\n")
        out.write(f"file_count: {len(files)}\n\n")

        # ---------- Table of Contents ----------
        out.write("=== TABLE OF CONTENTS ===\n")
        for f in files:
            out.write(
                f"[{f['id']:03d}] {f['path']} | "
                f"{f['suffix'] or 'unknown'} | "
                f"{f['lines']} lines | "
                f"{f['size']} bytes\n"
            )
        out.write("\n")

        # ---------- File Dumps ----------
        for f in files:
            path = f["path_obj"]
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                text = f"[ERROR READING FILE: {e}]"

            out.write("<<<FILE_BEGIN>>>\n")
            out.write(f"FILE_ID: {f['id']}\n")
            out.write(f"PATH: {f['path']}\n")
            out.write(f"LANGUAGE: {f['suffix'].lstrip('.') or 'unknown'}\n")
            out.write(f"LINES: {f['lines']}\n")
            out.write(f"SIZE_BYTES: {f['size']}\n")

            # ---------- Structural Hints ----------
            if f["suffix"] == ".py":
                symbols = extract_python_symbols(text)
                out.write(f"PY_CLASSES: {symbols['classes']}\n")
                out.write(f"PY_FUNCTIONS: {symbols['functions']}\n")
                out.write(f"PY_IMPORTS: {symbols['imports']}\n")

            elif f["suffix"] == ".md":
                headings = extract_markdown_headings(text)
                out.write(f"MD_HEADINGS: {headings}\n")

            elif f["suffix"] in {".yaml", ".yml", ".json", ".toml", ".cfg", ".ini"}:
                keys = extract_top_level_keys(text)
                out.write(f"TOP_LEVEL_KEYS: {keys}\n")

            out.write("<<<FILE_CONTENT>>>\n")

            lines = text.splitlines()
            if len(lines) <= MAX_CHUNK_LINES:
                out.write(text)
                out.write("\n")
            else:
                chunk_id = 1
                for start, end, chunk in chunk_text(lines, MAX_CHUNK_LINES):
                    out.write(
                        f"\n<<<CHUNK {chunk_id} | LINES {start}-{end}>>>\n"
                    )
                    out.write("\n".join(chunk))
                    out.write("\n")
                    chunk_id += 1

            out.write("<<<FILE_END>>>\n\n")

    print(f"Repo exported to: {output}")

if __name__ == "__main__":
    export_repo()
