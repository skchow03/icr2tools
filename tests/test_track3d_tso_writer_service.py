from sg_viewer.services.track3d_tso_writer import (
    format_tso_dynamic_line,
    replace_tso_dynamic_section_in_3d_text,
    track3d_newline_style,
)
from sg_viewer.services.trackside_objects import TracksideObject


def test_format_tso_dynamic_line_normalizes_filename() -> None:
    obj = TracksideObject(" tree.3do ", 1, 2, 3, 4, 5, 6)
    assert format_tso_dynamic_line("__TSO7", obj) == '__TSO7: DYNAMIC 1, 2, 3, 4, 5, 6, 1, EXTERN "tree";'


def test_track3d_newline_style_prefers_first_newline_style() -> None:
    assert track3d_newline_style("a\r\nb\n") == "\r\n"
    assert track3d_newline_style("a\nb\r\n") == "\n"


def test_replace_tso_dynamic_section_updates_deletes_and_appends() -> None:
    text = (
        'Header\n'
        '__TSO0: DYNAMIC 1, 2, 3, 4, 5, 6, 1, EXTERN "old";\n'
        '__TSO1: DYNAMIC 10, 20, 30, 40, 50, 60, 1, EXTERN "keep";\n'
        'Footer\n'
    )
    objects = [
        TracksideObject("keep", 10, 20, 30, 40, 50, 60),
        TracksideObject("new", 7, 8, 9, 10, 11, 12),
    ]

    updated, existing_count, deleted_count = replace_tso_dynamic_section_in_3d_text(text, objects)

    assert existing_count == 2
    assert deleted_count == 0
    assert '__TSO1: DYNAMIC 10, 20, 30, 40, 50, 60, 1, EXTERN "keep";' in updated
    assert '__TSO0: DYNAMIC 7, 8, 9, 10, 11, 12, 1, EXTERN "new";' in updated
    assert 'EXTERN "old"' not in updated
