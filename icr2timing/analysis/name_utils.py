"""
name_utils.py

Helpers for parsing and compacting driver names for display.
"""

from typing import Dict, List, Optional
import html

_SUFFIX_TOKENS = {"jr", "sr", "ii", "iii", "iv", "v"}


def split_name(name: str) -> (str, str):
    """Split into (first_name, last_name_with_suffix)."""
    name = name.strip()
    if not name:
        return "", ""
    parts = name.split()
    if len(parts) == 1:
        return parts[0], parts[0]
    last_tok = parts[-1]
    last_tok_norm = last_tok.rstrip('.').lower()
    if last_tok_norm in _SUFFIX_TOKENS and len(parts) >= 2:
        last_name = parts[-2] + " " + last_tok
        first_name = " ".join(parts[:-2]) if len(parts) > 2 else parts[0]
    else:
        last_name = parts[-1]
        first_name = " ".join(parts[:-1])
    return first_name, last_name


def shortest_unique_prefix(target: str, others: List[str]) -> Optional[str]:
    """Shortest unique prefix (capitalized) of target not shared by any in others."""
    if not target:
        return None
    target_lower = target.lower()
    others_lower = [o.lower() for o in others]
    for L in range(1, len(target)):
        pref = target_lower[:L]
        if any(o.startswith(pref) for o in others_lower):
            continue
        return target[:L].capitalize()
    return None


def compute_compact_names(state) -> Dict[int, str]:
    """
    Given a RaceState, return a mapping struct_index -> compact name
    (disambiguated if multiple drivers share last names).
    """
    shown = [i for i in state.order if i is not None]
    parsed: Dict[int, Dict[str, str]] = {}
    for idx in shown:
        drv = state.drivers.get(idx)
        raw = html.unescape(drv.name) if (drv and drv.name) else ""
        first, last = split_name(raw)
        parsed[idx] = {"first": first.strip(), "last": last.strip()}

    groups: Dict[str, List[int]] = {}
    for idx, parts in parsed.items():
        key = (parts["last"] or "").lower()
        groups.setdefault(key, []).append(idx)

    display: Dict[int, str] = {}
    for last_norm, idxs in groups.items():
        if not last_norm:
            for idx in idxs:
                first = parsed[idx]["first"]
                display[idx] = html.escape((first + " " + parsed[idx]["last"]).strip())
            continue
        if len(idxs) == 1:
            display[idxs[0]] = html.escape(parsed[idxs[0]]["last"])
            continue

        first_names = [parsed[i]["first"] or "" for i in idxs]
        initials_count: Dict[str, int] = {}
        for fn in first_names:
            init = fn[:1].upper() if fn else ""
            initials_count[init] = initials_count.get(init, 0) + 1

        for i, struct_idx in enumerate(idxs):
            fn = parsed[struct_idx]["first"]
            last_display = parsed[struct_idx]["last"]
            if not fn:
                display[struct_idx] = html.escape(last_display)
                continue
            init = fn[0].upper()
            if initials_count.get(init, 0) == 1:
                display[struct_idx] = html.escape(f"{init}. {last_display}")
                continue
            others = [n for j, n in enumerate(first_names) if idxs[j] != struct_idx]
            prefix = shortest_unique_prefix(fn, others)
            if prefix:
                display[struct_idx] = html.escape(f"{prefix}. {last_display}")
            else:
                display[struct_idx] = html.escape(f"{fn} {last_display}")
    return display


def compute_abbreviations(drivers: Dict[int, object]) -> Dict[int, str]:
    """
    Generate unique 3-letter abbreviations:
      - Default = first 3 letters of last name (uppercased).
      - If duplicates exist, use F1-style: first letter of first name + first two of last.
      - If still duplicates, extend further with more letters.
    """
    temp = {}
    for idx, d in drivers.items():
        name = (getattr(d, "name", "") or "").strip()
        if not name:
            temp[idx] = ("", "", "???", "???")
            continue

        first, last = split_name(name)
        first = first.upper()
        last = last.upper()

        base = last[:3].upper().ljust(3, "?")
        alt = (first[:1] + last[:2]).upper().ljust(3, "?") if first else base
        temp[idx] = (first, last, base, alt)

    # Count base occurrences
    base_counts: Dict[str, int] = {}
    for _, (_, _, base, _) in temp.items():
        base_counts[base] = base_counts.get(base, 0) + 1

    out = {}
    taken = set()
    for idx, (first, last, base, alt) in temp.items():
        if base_counts[base] == 1 and base not in taken:
            cand = base
        else:
            cand = alt
            extra = 1
            # Ensure uniqueness
            while cand in taken:
                if extra < len(first):
                    cand = (first[:1+extra] + last[:2])[:3].upper()
                elif extra < len(last):
                    cand = (first[:1] + last[:2+extra])[:3].upper()
                else:
                    cand = base[:2] + str(extra)
                extra += 1
        out[idx] = cand
        taken.add(cand)

    return out
