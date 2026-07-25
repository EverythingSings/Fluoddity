"""Headless contract smoke for the local stream-operator interface."""

from __future__ import annotations

from pathlib import Path
import importlib.util
import json
import sys
import tempfile
from unittest.mock import patch

import glfw
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from controller_input import ControllerCam
from state import UIState

operator_spec = importlib.util.spec_from_file_location(
    "stream_operator_service", REPO_ROOT / "services" / "stream_operator.py"
)
operator_module = importlib.util.module_from_spec(operator_spec)
operator_spec.loader.exec_module(operator_module)
StreamOperatorService = operator_module.StreamOperatorService


class DummySim:
    frame_count = 42
    time = 1.25
    entity_count = 1024


class DummyVideo:
    def is_active(self):
        return False


class DummyUI:
    show_sidebar = True
    currently_open_project = "_Default"


class DummyApp:
    window = object()
    sim = DummySim()
    video_service = DummyVideo()
    ui = DummyUI()
    controller_cam = ControllerCam()
    _optix_interface = None
    _pathtracer_interface = None


def main() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        service = StreamOperatorService(root=root, status_interval=0.0)
        app = DummyApp()
        state = UIState()
        command = {
            "version": 1,
            "id": "smoke",
            "set": {
                "sim": {"MUTATION_SCALE": 0.125},
                "camera": {"orbit_rate": 0.002},
                "controller": {"pos": [1.0, 2.0, -4.0], "yaw": 0.5},
            },
            "actions": ["resume", "optix_on", "hide_ui", {"name": "mark", "label": "smoke"}],
        }
        (service.inbox / "smoke.json").write_text(json.dumps(command), encoding="utf-8")
        service.apply_pending(app, state)
        with (
            patch("glfw.get_framebuffer_size", return_value=(1280, 720)),
            patch(
                "glfw.get_window_attrib",
                side_effect=lambda _window, attribute: attribute == glfw.VISIBLE,
            ),
        ):
            service.update_status(app, state, 1 / 60)

        receipt = json.loads((service.receipts / "smoke.json").read_text(encoding="utf-8"))
        status = json.loads(service.status_path.read_text(encoding="utf-8"))
        assert receipt["status"] == "applied"
        assert state.sim.MUTATION_SCALE == 0.125
        assert state.camera.optix_enabled is True
        assert state.camera.orbit_rate == 0.002
        assert np.allclose(app.controller_cam.pos, [1.0, 2.0, -4.0])
        assert app.ui.show_sidebar is False
        assert status["frame_count"] == 42
        assert status["renderer"]["optix_requested"] is True
        assert service.events_path.exists()
        assert service.schema_path.exists()
        schema = json.loads(service.schema_path.read_text(encoding="utf-8"))
        assert "window_size" in schema["actions"]
        assert "MUTATION_SCALE" in schema["sections"]["sim"]
        print("stream operator smoke: PASS")


if __name__ == "__main__":
    main()
