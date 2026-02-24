from __future__ import annotations

from dataclasses import replace


def infer_section_connectivity(sections) -> None:
    """Normalize section ordering and index-based connectivity in place.

    Section table edits may change ``section_id`` and link fields. The preview
    model requires ``section_id == list index`` and connectivity links to point
    at those indices, so this helper reorders sections by ``section_id``,
    remaps links to the new indices, and updates the original list in place.
    """

    if not sections:
        return

    ordered_sections = sorted(sections, key=lambda section: int(section.section_id))
    id_to_new_index = {int(section.section_id): index for index, section in enumerate(ordered_sections)}
    count = len(ordered_sections)

    normalized = []
    for index, section in enumerate(ordered_sections):
        prev_index = id_to_new_index.get(int(section.previous_id), (index - 1) % count)
        next_index = id_to_new_index.get(int(section.next_id), (index + 1) % count)
        normalized.append(
            replace(
                section,
                section_id=index,
                previous_id=prev_index,
                next_id=next_index,
            )
        )

    sections[:] = normalized


def is_closed_loop(sections) -> bool:
    """
    Returns True iff sections form exactly one closed loop.
    """
    n = len(sections)
    if n == 0:
        return False

    # --- 1. Every section must have both links ---
    for i, s in enumerate(sections):
        if s.next_id is None or s.previous_id is None:
            return False
        if not (0 <= s.next_id < n):
            return False
        if not (0 <= s.previous_id < n):
            return False

    # --- 2. Walk forward from section 0 ---
    visited = set()
    i = 0

    while i not in visited:
        visited.add(i)
        i = sections[i].next_id

        # Defensive: broken pointer
        if i is None or not (0 <= i < n):
            return False

    # --- 3. Must return to start ---
    if i != 0:
        return False

    # --- 4. Must have visited all sections ---
    if len(visited) != n:
        return False

    # --- 5. Check backward consistency ---
    for j in visited:
        nxt = sections[j].next_id
        if sections[nxt].previous_id != j:
            return False

    return True


def loop_length(sections) -> float:
    """Return the total length of a closed loop of sections.

    Raises ValueError if the sections do not form a closed loop.
    """

    if not is_closed_loop(sections):
        raise ValueError("Track must be a closed loop to compute length")

    total = 0.0
    visited: set[int] = set()
    index = 0

    while index not in visited:
        visited.add(index)
        section = sections[index]
        total += float(getattr(section, "length", 0.0))
        index = section.next_id

    return total
