from __future__ import annotations

from typing import Protocol


class _ActionSetupHost(Protocol):
    def _create_actions_impl(self) -> None: ...


class _MenuSetupHost(Protocol):
    def _create_menus_impl(self) -> None: ...


class ViewerActionBuilder:
    """Delegates legacy QAction construction away from SGViewerController.__init__."""

    def __init__(self, host: _ActionSetupHost) -> None:
        self._host = host

    def create_actions(self) -> None:
        self._host._create_actions_impl()


class ViewerMenuBuilder:
    """Delegates legacy menu construction away from SGViewerController.__init__."""

    def __init__(self, host: _MenuSetupHost) -> None:
        self._host = host

    def create_menus(self) -> None:
        self._host._create_menus_impl()
