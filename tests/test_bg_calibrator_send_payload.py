import json

import pytest

try:
    from PyQt5 import QtWidgets
    from sg_viewer.ui import bg_calibrator_minimal
except ImportError:  # pragma: no cover
    pytest.skip("PyQt5 not available", allow_module_level=True)


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    yield app


def test_send_values_includes_current_image_path(qapp, monkeypatch, tmp_path):
    sent = {}

    class _FakeSocket:
        def __init__(self, _parent):
            self.connected_endpoint = None

        def connectToServer(self, endpoint):
            self.connected_endpoint = endpoint

        def waitForConnected(self, _timeout):
            return True

        def write(self, payload):
            sent["payload"] = payload
            self._bytes_pending = 0
            return len(payload)

        def flush(self):
            return None

        def waitForBytesWritten(self, _timeout):
            return True

        def bytesToWrite(self):
            return getattr(self, "_bytes_pending", 0)

        def disconnectFromServer(self):
            return None

    monkeypatch.setattr(bg_calibrator_minimal.QtNetwork, "QLocalSocket", _FakeSocket)
    monkeypatch.setattr(
        bg_calibrator_minimal.QtWidgets.QMessageBox,
        "information",
        lambda *_args, **_kwargs: None,
    )

    window = bg_calibrator_minimal.Calibrator(send_endpoint="test-endpoint")
    try:
        image_path = tmp_path / "calibration-background.png"
        image_path.write_bytes(b"placeholder")
        window.current_image_path = str(image_path)
        window.out_scale.setText("42.0")
        window.out_ul.setText("1.25, 2.5")

        window.send_values_to_main_app()

        payload = json.loads(sent["payload"].decode("utf-8"))
        assert payload["units_per_pixel"] == 42.0
        assert payload["upper_left"] == [1.25, 2.5]
        assert payload["image_path"] == str(image_path)
    finally:
        window.close()
