"""Normalize GPU viewer load diagnostics into one human-readable report.

The worker already records nonfatal failures in several subsystems. Keep this
module Qt-free so omissions, duplicate messages, and missing-asset handling
can be verified independently of an OpenGL window.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LoadIssue:
    category: str
    message: str


def collect_load_issues(stats):
    """Return all reported failures, without silently truncating long lists.

    An optional asset that is simply not present (e.g. HORIZ on a track
    without a skybox) is not an error. Include failures recorded when a
    candidate was actually found but could not be loaded.
    """
    issues = []
    seen = set()

    def add(category, value):
        if value is None:
            return
        if isinstance(value, str):
            values = (value,)
        else:
            values = value
        for item in values:
            message = str(item).strip()
            if not message or (category, message) in seen:
                continue
            seen.add((category, message))
            issues.append(LoadIssue(category, message))

    add("Referenced objects", stats.get("external_warnings", ()))
    add("Missing MIP textures", stats.get("missing_textures", ()))
    add("Invalid MIP textures", stats.get("texture_errors", ()))
    add("PMP sprites", stats.get("pmp_warnings", ()))
    add("Palette", stats.get("palette_warning"))
    add("Skybox", stats.get("skybox_error"))
    add("Skybox MIP textures", stats.get("skybox_missing_mips", ()))
    add("Skybox MIP textures", stats.get("skybox_texture_errors", ()))
    add("Track navigation", stats.get("trk_error"))
    return tuple(issues)


def format_load_log(filename, issues):
    """Format a selectable/copyable log for the last model-load attempt."""
    name = Path(filename).name if filename else "(no model)"
    heading = f"Load error log — {name}"
    if not issues:
        return f"{heading}\n\nNo load errors or asset warnings were reported.\n"
    groups = {}
    for issue in issues:
        groups.setdefault(issue.category, []).append(issue.message)
    total = len(issues)
    lines = [heading, f"{total} issue{'s' if total != 1 else ''} reported", ""]
    for category, messages in groups.items():
        lines.append(f"{category} ({len(messages)})")
        lines.extend(f"  - {message}" for message in messages)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
