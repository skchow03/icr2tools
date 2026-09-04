import importlib
import sys
import types

import pytest


@pytest.fixture
def memory_viewer(monkeypatch):
    """Import the Windows-only viewer with its process modules stubbed."""
    pymem = types.ModuleType("pymem")
    pymem.Pymem = object
    monkeypatch.setitem(sys.modules, "pymem", pymem)
    monkeypatch.setitem(sys.modules, "win32gui", types.ModuleType("win32gui"))
    monkeypatch.setitem(sys.modules, "win32process", types.ModuleType("win32process"))
    sys.modules.pop("icr2_core.icr2_memory", None)
    sys.modules.pop("icr2timing.memory_viewer", None)
    return importlib.import_module("icr2timing.memory_viewer")


def test_load_watches_accepts_16_16_type(tmp_path, memory_viewer):
    watches_path = tmp_path / "watches.ini"
    watches_path.write_text(
        "[Speed]\nDOS102 = 0x1234\ntype = 16.16\ncount = 2\n",
        encoding="utf-8",
    )

    watches = memory_viewer.load_watches(watches_path, "DOS102")

    assert watches == [memory_viewer.Watch("Speed", 0x1234, "16.16", 2, "auto")]


@pytest.mark.parametrize(
    ("raw_value", "count", "expected"),
    [
        (98304, 1, 1.5),
        (-32768, 1, -0.5),
        ([65536, -147456, 0], 3, [1.0, -2.25, 0.0]),
    ],
)
def test_read_watch_value_decodes_signed_16_16(memory_viewer, raw_value, count, expected):
    class Memory:
        def read(self, address, type_name, read_count):
            assert (address, type_name, read_count) == (0x1234, "i32", count)
            return raw_value

    watch = memory_viewer.Watch("Value", 0x1234, "16.16", count, "auto")

    assert memory_viewer.read_watch_value(Memory(), watch) == expected


def test_format_16_16_value_as_decimal(memory_viewer):
    watch = memory_viewer.Watch("Value", 0x1234, "16.16", 1, "auto")

    assert memory_viewer.format_value(-2.25, watch) == "-2.25"
