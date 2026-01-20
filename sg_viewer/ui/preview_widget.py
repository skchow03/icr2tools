"""Backward-compatible import for the SG preview widget."""
from sg_viewer.ui.preview_widget_qt import PreviewWidgetQt

SGPreviewWidget = PreviewWidgetQt

__all__ = ["PreviewWidgetQt", "SGPreviewWidget"]
