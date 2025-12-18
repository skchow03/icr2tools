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
