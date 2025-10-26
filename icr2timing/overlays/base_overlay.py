"""
base_overlay.py

Defines the BaseOverlay interface that all overlays must implement.
"""

from abc import ABC, abstractmethod

from icr2_core.model import RaceState


class BaseOverlay(ABC):
    """Abstract overlay interface."""

    @abstractmethod
    def widget(self):
        """Return the QWidget associated with this overlay."""
        pass

    @abstractmethod
    def on_state_updated(self, state: RaceState, update_bests: bool = True):
        """Handle a new RaceState snapshot."""
        pass

    @abstractmethod
    def on_error(self, msg: str):
        """Handle an error message."""
        pass
