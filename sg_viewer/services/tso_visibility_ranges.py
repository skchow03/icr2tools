from sg_viewer.io.track3d_parser import Track3DSectionDlongList


def build_subsection_dlong_metadata(
    rows: list[Track3DSectionDlongList],
) -> tuple[dict[tuple[int, int], tuple[int, int | None]], dict[int, tuple[int, ...]]]:
    ranges: dict[tuple[int, int], tuple[int, int | None]] = {}
    subindex_starts: dict[int, list[tuple[int, int]]] = {}
    rows_by_section: dict[int, list[tuple[int, int, int | None]]] = {}
    for row in rows:
        if not row.dlongs:
            continue
        section = int(row.section)
        sub_index = int(row.sub_index)
        start_dlong = int(row.dlongs[0])
        inclusive_end = int(row.dlongs[-1])
        if inclusive_end < start_dlong:
            start_dlong, inclusive_end = inclusive_end, start_dlong
        rows_by_section.setdefault(section, []).append((sub_index, start_dlong, inclusive_end))
        subindex_starts.setdefault(section, []).append((sub_index, start_dlong))

    for section, values in rows_by_section.items():
        ordered_values = sorted(values, key=lambda item: item[0])
        for index, (sub_index, start_dlong, inclusive_end) in enumerate(ordered_values):
            end_dlong: int | None = inclusive_end
            if index + 1 < len(ordered_values):
                next_start = ordered_values[index + 1][1]
                if next_start >= start_dlong:
                    end_dlong = next_start
            ranges[(section, sub_index)] = (start_dlong, end_dlong)

    normalized_subindex_starts = {
        section: tuple(start for _, start in sorted(values, key=lambda item: item[0]))
        for section, values in subindex_starts.items()
    }
    return ranges, normalized_subindex_starts
