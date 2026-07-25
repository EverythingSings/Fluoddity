"""Local command and telemetry surface for agent-operated Fluoddity sessions."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time
from typing import Any

import numpy as np

from utilities.paths import get_operator_dir, get_screenshots_dir, get_videos_dir


_SAFE_LABEL = re.compile(r"[^A-Za-z0-9._-]+")


class StreamOperatorService:
    """Consume atomic JSON commands and publish compact runtime telemetry."""

    VERSION = 1
    ACTIONS = (
        "pause", "resume", "toggle_pause", "reset", "full_reset",
        "new_simulation", "randomize", "reload_shaders", "camera_reset",
        "optix_on", "optix_off", "show_ui", "hide_ui", "screenshot",
        "record_start", "record_stop", "load_config", "mark",
        "window_size", "quit",
    )

    def __init__(self, root: Path | None = None, status_interval: float = 1.0):
        self.root = Path(root) if root is not None else get_operator_dir()
        self.inbox = self.root / "inbox"
        self.receipts = self.root / "receipts"
        self.events_path = self.root / "events.jsonl"
        self.status_path = self.root / "status.json"
        self.schema_path = self.root / "schema.json"
        self.status_interval = status_interval
        self._last_status_write = 0.0
        self._last_frame_time: float | None = None
        self._fps_ema = 0.0
        self._last_command: dict[str, Any] | None = None
        self._schema_written = False
        for directory in (self.root, self.inbox, self.receipts):
            directory.mkdir(parents=True, exist_ok=True)

    def apply_pending(self, app, ui_state, max_commands: int = 32) -> None:
        """Apply queued commands to the orchestrator-owned state before dispatch."""
        for path in sorted(self.inbox.glob("*.json"))[:max_commands]:
            command_id = path.stem
            receipt: dict[str, Any]
            try:
                command = json.loads(path.read_text(encoding="utf-8"))
                command_id = self._safe_label(str(command.get("id") or command_id))
                self._apply_command(app, ui_state, command)
                receipt = {
                    "version": self.VERSION,
                    "id": command_id,
                    "status": "applied",
                    "applied_at": self._timestamp(),
                    "frame_count": int(app.sim.frame_count),
                }
                self._last_command = receipt
            except Exception as exc:
                receipt = {
                    "version": self.VERSION,
                    "id": command_id,
                    "status": "error",
                    "applied_at": self._timestamp(),
                    "error": f"{type(exc).__name__}: {exc}",
                }
                self._last_command = receipt
                print(f"[Operator] Command {command_id} failed: {exc}")

            self._atomic_json(self.receipts / f"{command_id}.json", receipt)
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def update_status(self, app, ui_state, dt: float) -> None:
        """Publish a one-second runtime heartbeat for automation and monitoring."""
        import glfw

        if not self._schema_written:
            self._write_schema(app, ui_state)
            self._schema_written = True
        now = time.monotonic()
        if dt > 0:
            fps = 1.0 / dt
            self._fps_ema = fps if self._fps_ema == 0 else self._fps_ema * 0.9 + fps * 0.1
        self._last_frame_time = now
        if now - self._last_status_write < self.status_interval:
            return
        self._last_status_write = now

        optix = app._optix_interface
        pathtracer = app._pathtracer_interface
        controller = app.controller_cam
        status = {
            "version": self.VERSION,
            "timestamp": self._timestamp(),
            "alive": True,
            "frame_count": int(app.sim.frame_count),
            "simulation_time": float(app.sim.time),
            "fps_ema": round(self._fps_ema, 2),
            "recording": bool(app.video_service.is_active()),
            "ui_visible": bool(app.ui.show_sidebar),
            "project": str(getattr(app.ui, "currently_open_project", "")),
            "simulation": {
                "going": bool(ui_state.sim.going),
                "entity_count": int(app.sim.entity_count),
                "canvas_resolution": int(ui_state.preferences.canvas_resolution),
                "rule_seed": float(ui_state.sim.rule_seed),
                "mutation_scale": float(ui_state.sim.MUTATION_SCALE),
                "trail_persistence": float(ui_state.sim.TRAIL_PERSISTENCE),
                "trail_diffusion": float(ui_state.sim.TRAIL_DIFFUSION),
            },
            "camera": {
                "position": self._json_value(controller.pos),
                "yaw": float(controller.yaw),
                "pitch": float(controller.pitch),
                "fov": float(ui_state.camera.fov),
                "orbit_center": self._json_value(ui_state.camera.orbit_center),
                "orbit_rate": float(ui_state.camera.orbit_rate),
            },
            "renderer": {
                "framebuffer_size": list(glfw.get_framebuffer_size(app.window)),
                "window_visible": bool(glfw.get_window_attrib(app.window, glfw.VISIBLE)),
                "window_iconified": bool(glfw.get_window_attrib(app.window, glfw.ICONIFIED)),
                "render_3d": bool(ui_state.camera.render_3d),
                "optix_requested": bool(ui_state.camera.optix_enabled),
                "optix_active": bool(optix is not None and not optix.failed),
                "optix_failed": bool(optix is not None and optix.failed),
                "optix_fail_reason": "" if optix is None else str(optix.fail_reason),
                "gas_time_ms": float(ui_state.camera.optix_gas_time_ms),
                "render_time_ms": float(ui_state.camera.optix_render_time_ms),
                "rt_mode": int(ui_state.preferences.three_d_rt_mode),
                "pathtracer_active": bool(pathtracer is not None and not pathtracer.failed),
            },
            "artifacts": {
                "latest_screenshot": self._latest_artifact(get_screenshots_dir(), "*.png"),
                "latest_video": self._latest_artifact(get_videos_dir(), "*.mp4"),
                "events": str(self.events_path),
            },
            "last_command": self._last_command,
        }
        self._atomic_json(self.status_path, status)

    def _apply_command(self, app, ui_state, command: dict[str, Any]) -> None:
        if not isinstance(command, dict):
            raise TypeError("command must be a JSON object")
        version = int(command.get("version", self.VERSION))
        if version != self.VERSION:
            raise ValueError(f"unsupported command version {version}")

        updates = command.get("set", {})
        if updates:
            if not isinstance(updates, dict):
                raise TypeError("set must be an object")
            for section, values in updates.items():
                self._apply_section(app, ui_state, section, values)

        actions = command.get("actions", [])
        if isinstance(actions, (str, dict)):
            actions = [actions]
        if not isinstance(actions, list):
            raise TypeError("actions must be a list")
        for action in actions:
            self._apply_action(app, ui_state, action)

        label = command.get("label")
        if label:
            self._append_event(app, "command", str(label), command.get("note", ""))

    def _apply_section(self, app, ui_state, section: str, values: Any) -> None:
        if not isinstance(values, dict):
            raise TypeError(f"set.{section} must be an object")
        targets = {
            "sim": ui_state.sim,
            "camera": ui_state.camera,
            "preferences": ui_state.preferences,
            "controller": app.controller_cam,
        }
        if section not in targets:
            raise ValueError(f"unsupported state section {section!r}")
        target = targets[section]
        allowed = {field.name for field in fields(target)} if is_dataclass(target) else {
            "pos", "yaw", "pitch", "fov"
        }
        for name, value in values.items():
            if name not in allowed or name.startswith("_"):
                raise ValueError(f"unsupported field {section}.{name}")
            current = getattr(target, name)
            setattr(target, name, self._coerce_value(current, value, f"{section}.{name}"))

        if section == "controller" and ({"yaw", "pitch"} & values.keys()):
            app.controller_cam._update_vectors()
        if section == "preferences" and ({"entity_count", "canvas_resolution"} & values.keys()):
            ui_state.request_world_size_change = True

    def _apply_action(self, app, ui_state, action: str | dict[str, Any]) -> None:
        options: dict[str, Any] = {}
        if isinstance(action, dict):
            options = action
            name = str(action.get("name", ""))
        else:
            name = str(action)
        if not name:
            raise ValueError("action name is required")

        if name == "pause":
            ui_state.sim.going = False
        elif name == "resume":
            ui_state.sim.going = True
        elif name == "toggle_pause":
            ui_state.sim.going = not ui_state.sim.going
        elif name == "reset":
            ui_state.request_reset = True
        elif name in ("full_reset", "new_simulation"):
            ui_state.request_full_reset = True
        elif name == "randomize":
            ui_state.request_randomize_mutations = True
        elif name == "reload_shaders":
            ui_state.request_reload = True
        elif name == "camera_reset":
            app.controller_cam.reset()
            ui_state.request_camera_reset = True
        elif name == "optix_on":
            ui_state.camera.render_3d = True
            ui_state.camera.optix_enabled = True
        elif name == "optix_off":
            ui_state.camera.optix_enabled = False
        elif name == "show_ui":
            app.ui.show_sidebar = True
        elif name == "hide_ui":
            app.ui.show_sidebar = False
        elif name == "screenshot":
            label = self._safe_label(str(options.get("label") or "operator"))
            ui_state.preferences.filename_prefix = label
            ui_state.request_screenshot = True
            self._append_event(app, "capture_requested", label, options.get("note", ""))
        elif name == "record_start":
            if not app.video_service.is_active():
                ui_state.toggle_recording = True
        elif name == "record_stop":
            if app.video_service.is_active():
                ui_state.toggle_recording = True
        elif name == "load_config":
            filename = str(options.get("filename") or "")
            if not filename:
                raise ValueError("load_config requires filename")
            ui_state.load_filename = filename
            ui_state.load_category = str(options.get("category") or "")
            ui_state.request_load_file = True
        elif name == "mark":
            label = str(options.get("label") or "interesting")
            self._append_event(app, "marker", label, options.get("note", ""))
        elif name == "window_size":
            import glfw

            width = int(options.get("width", 1280))
            height = int(options.get("height", 720))
            if width < 320 or height < 240 or width > 7680 or height > 4320:
                raise ValueError("window_size is outside the supported 320x240 to 7680x4320 range")
            # A minimized GLFW window reports a 1x1 framebuffer, which silently
            # collapses offline path-traced recordings to 1x1. Restore it before
            # sizing; optionally hide it again so unattended renders do not
            # occupy the user's desktop.
            glfw.restore_window(app.window)
            glfw.set_window_size(app.window, width, height)
            if bool(options.get("hidden", False)):
                glfw.hide_window(app.window)
        elif name == "quit":
            import glfw

            glfw.set_window_should_close(app.window, True)
        else:
            raise ValueError(f"unsupported action {name!r}")

    @staticmethod
    def _coerce_value(current: Any, value: Any, label: str) -> Any:
        if isinstance(current, np.ndarray):
            result = np.asarray(value, dtype=current.dtype)
            if result.shape != current.shape:
                raise ValueError(f"{label} requires shape {current.shape}")
            return result
        if isinstance(current, bool):
            if not isinstance(value, bool):
                raise TypeError(f"{label} requires a boolean")
            return value
        if isinstance(current, int) and not isinstance(current, bool):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{label} requires a number")
            return int(value)
        if isinstance(current, float):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{label} requires a number")
            return float(value)
        if isinstance(current, list):
            if not isinstance(value, list):
                raise TypeError(f"{label} requires a list")
            return value
        if isinstance(current, dict):
            if not isinstance(value, dict):
                raise TypeError(f"{label} requires an object")
            return value
        if isinstance(current, str):
            if not isinstance(value, str):
                raise TypeError(f"{label} requires a string")
            return value
        return value

    def _append_event(self, app, kind: str, label: str, note: Any = "") -> None:
        event = {
            "version": self.VERSION,
            "timestamp": self._timestamp(),
            "kind": kind,
            "label": label,
            "note": str(note or ""),
            "frame_count": int(app.sim.frame_count),
        }
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, separators=(",", ":")) + "\n")

    def _write_schema(self, app, ui_state) -> None:
        def section_schema(target) -> dict[str, str]:
            names = {field.name for field in fields(target)} if is_dataclass(target) else {
                "pos", "yaw", "pitch", "fov"
            }
            return {
                name: type(getattr(target, name)).__name__
                for name in sorted(names)
                if not name.startswith("_")
            }

        schema = {
            "version": self.VERSION,
            "command_shape": {
                "set": {"section": {"field": "JSON value"}},
                "actions": ["action name or action object"],
                "label": "optional experiment label",
                "note": "optional note",
            },
            "sections": {
                "sim": section_schema(ui_state.sim),
                "camera": section_schema(ui_state.camera),
                "preferences": section_schema(ui_state.preferences),
                "controller": section_schema(app.controller_cam),
            },
            "actions": list(self.ACTIONS),
        }
        self._atomic_json(self.schema_path, schema)

    @staticmethod
    def _latest_artifact(directory: Path, pattern: str) -> dict[str, Any] | None:
        try:
            artifact = max(directory.glob(pattern), key=lambda path: path.stat().st_mtime)
        except (ValueError, FileNotFoundError):
            return None
        stat = artifact.stat()
        return {
            "path": str(artifact),
            "bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        }

    @staticmethod
    def _safe_label(label: str) -> str:
        cleaned = _SAFE_LABEL.sub("-", label).strip("-._")
        return cleaned[:80] or "operator"

    @staticmethod
    def _json_value(value: Any) -> Any:
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, np.generic):
            return value.item()
        return value

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _atomic_json(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(value, indent=2), encoding="utf-8")
        os.replace(tmp, path)
