from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types

if "numpy" not in sys.modules:
    sys.modules["numpy"] = types.ModuleType("numpy")

from sg_viewer.model.preview_fsection import PreviewFSection


_CONNECT_OPS_PATH = Path(__file__).resolve().parents[1] / "sg_viewer" / "preview" / "runtime_ops" / "connect_ops.py"
_SPEC = importlib.util.spec_from_file_location("connect_ops_module", _CONNECT_OPS_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_CONNECT_OPS = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_CONNECT_OPS)
_RuntimeCoreConnectOpsMixin = _CONNECT_OPS._RuntimeCoreConnectOpsMixin


class _DummyRuntime(_RuntimeCoreConnectOpsMixin):
    def __init__(self, fsects_by_section: list[list[PreviewFSection]]) -> None:
        self._fsects_by_section = fsects_by_section


def test_sync_fsects_on_connection_keeps_source_and_target_unchanged() -> None:
    source_fsects = [
        PreviewFSection(start_dlat=1.0, end_dlat=2.0, surface_type=5, type2=0),
        PreviewFSection(start_dlat=3.0, end_dlat=4.0, surface_type=1, type2=0),
    ]
    target_fsects = [
        PreviewFSection(start_dlat=10.0, end_dlat=20.0, surface_type=6, type2=0),
        PreviewFSection(start_dlat=30.0, end_dlat=40.0, surface_type=2, type2=1),
    ]
    runtime = _DummyRuntime([list(source_fsects), list(target_fsects)])

    runtime._sync_fsects_on_connection((0, "end"), (1, "start"))

    assert runtime._fsects_by_section[0] == source_fsects
    assert runtime._fsects_by_section[1] == target_fsects


def test_sync_fsects_on_connection_ignores_invalid_endtypes_without_changes() -> None:
    fsects = [
        [PreviewFSection(start_dlat=1.0, end_dlat=2.0, surface_type=5, type2=0)],
        [PreviewFSection(start_dlat=3.0, end_dlat=4.0, surface_type=1, type2=0)],
    ]
    runtime = _DummyRuntime([list(fsects[0]), list(fsects[1])])

    runtime._sync_fsects_on_connection((0, "bad"), (1, "start"))

    assert runtime._fsects_by_section == fsects
