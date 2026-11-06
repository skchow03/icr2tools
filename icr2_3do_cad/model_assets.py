"""Resolve referenced 3DO/N3 objects without changing source files.

The 3DO CAD prefers a *parseable* binary .3do across its established search
directories, then tries a compilable .3d if no valid binary can be found.
This is separate from the conservative CAD editor's original-binary importer.
"""
from __future__ import annotations

from pathlib import Path

from three_do import Model


def candidate_model_paths(name, folders):
    """Yield matching paths, all .3do candidates before any .3d candidate.

    DOS asset names are case-insensitive on both Windows and Linux; directory
    priority is otherwise the caller's original order. Suppress duplicate
    matches caused by overlapping search roots and repeated extension casing.
    """
    stem = Path(name).stem.casefold()
    directories = []
    seen_dirs = set()
    for folder in folders:
        if folder is None:
            continue
        directory = Path(folder)
        if not directory.is_dir():
            continue
        key = directory.resolve()
        if key not in seen_dirs:
            seen_dirs.add(key)
            directories.append(directory)
    seen_files = set()
    for extension in (".3do", ".3d"):
        wanted = stem + extension
        for directory in directories:
            exact = directory / wanted
            matches = [exact] if exact.is_file() else []
            # Search for case variants too (or the sole match on Linux).
            matches.extend(sorted(
                (entry for entry in directory.iterdir()
                 if entry.is_file() and entry.name.casefold() == wanted
                 and entry != exact),
                key=lambda entry: entry.name.casefold()))
            for path in matches:
                key = path.resolve()
                if key not in seen_files:
                    seen_files.add(key)
                    yield path


def reference_directories(parent_path, objects_folder=None, extra_dirs=()):
    """Match the historical ExternalResolver search paths and priorities."""
    parent = Path(parent_path).parent
    return (parent, objects_folder, *extra_dirs, parent / "3do",
            parent / "obj", parent.parent / "obj", parent.parent / "cars",
            parent.parent)


def load_model_candidate(path):
    """Validate a 3DO or compile an N3 file in memory. Never writes to disk."""
    path = Path(path)
    if path.suffix.casefold() == ".3do":
        return Model(path, associate_planes=False)
    if path.suffix.casefold() == ".3d":
        from n3_compile import compile_n3_text
        text = path.read_text(encoding="utf-8-sig")
        model, _ = compile_n3_text(text, path, associate_planes=False)
        return model
    raise ValueError(f"Unsupported referenced model: {path.name}")


def choose_reference(name, folders, cache, *, override=None, on_activity=None):
    """Return (path, model, warnings), trying bad candidates non-fatally.

    The caller owns the cache so repeated instances of the same wheel/helmet
    share one validated Model. Explicit user overrides retain highest priority;
    if one is unusable, normal search continues and the warning is preserved.
    """
    warnings = []
    paths = []
    if override is not None:
        preferred = Path(override)
        if preferred.is_file():
            paths.append(preferred)
        else:
            warnings.append(f"{name}: assigned object missing: {preferred.name}")
    paths.extend(candidate_model_paths(name, folders))
    checked = set()
    for path in paths:
        resolved = path.resolve()
        if resolved in checked:
            continue
        checked.add(resolved)
        cached = resolved in cache
        if not cached:
            if on_activity:
                on_activity(f"Parsing referenced model: {path.name} [{path}]")
            try:
                cache[resolved] = load_model_candidate(path)
            except (OSError, ValueError, UnicodeError, OverflowError) as exc:
                cache[resolved] = exc
        result = cache[resolved]
        if isinstance(result, Exception):
            if on_activity:
                on_activity(f"Referenced model rejected: {path.name}: {result}")
            warnings.append(f"{path.name}: invalid model ({result})")
            continue
        if on_activity:
            on_activity(f"Resolved {name} -> {path.name} (cached={cached})")
        return path, result, warnings
    if not paths:
        if on_activity:
            on_activity(f"Referenced object missing: {name}.3do / {name}.3d")
        warnings.append(f"Referenced object {name}.3do / {name}.3d not found")
    return None, None, warnings
