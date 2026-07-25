"""Local JSON command surface for repeatable generative-art searches.

The service intentionally has no network listener. A controller writes atomic
JSON files into an inbox, the App orchestrator applies them at the beginning of
the next frame, and a compact heartbeat reports render/recording state.
"""

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

from utilities.paths import get_screenshots_dir, get_user_data_dir, get_videos_dir


_SAFE_LABEL = re.compile(r"[^A-Za-z0-9._-]+")


class SearchOperatorService:
    """Consume local commands and publish runtime telemetry for search scripts."""

    VERSION = 1

    def __init__(self, root: Path | None = None, status_interval: float = 0.5):
        configured = os.environ.get("FLUODDITY_OPERATOR_DIR")
        self.root = Path(root or configured or (get_user_data_dir() / "OperatorRedo"))
        self.inbox = self.root / "inbox"
        self.receipts = self.root / "receipts"
        self.events_path = self.root / "events.jsonl"
        self.status_path = self.root / "status.json"
        self.status_interval = status_interval
        self._last_status_write = 0.0
        self._fps_ema = 0.0
        self._last_command: dict[str, Any] | None = None
        for directory in (self.root, self.inbox, self.receipts):
            directory.mkdir(parents=True, exist_ok=True)

    def apply_pending(self, app, ui_state, max_commands: int = 32) -> None:
        """Apply queued commands before the orchestrator processes one-shots."""
        for path in sorted(self.inbox.glob("*.json"))[:max_commands]:
            command_id = path.stem
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
            except Exception as exc:
                receipt = {
                    "version": self.VERSION,
                    "id": command_id,
                    "status": "error",
                    "applied_at": self._timestamp(),
                    "error": f"{type(exc).__name__}: {exc}",
                }
                print(f"[SearchOperator] Command {command_id} failed: {exc}")
            self._last_command = receipt
            self._atomic_json(self.receipts / f"{command_id}.json", receipt)
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def update_status(self, app, ui_state, dt: float) -> None:
        """Write a compact heartbeat used by search and render monitors."""
        if dt > 0:
            fps = 1.0 / dt
            self._fps_ema = fps if not self._fps_ema else self._fps_ema * 0.9 + fps * 0.1
        now = time.monotonic()
        if now - self._last_status_write < self.status_interval:
            return
        self._last_status_write = now

        import glfw

        optix = app.renderer_host.optix
        prefs = ui_state.preferences
        status = {
            "version": self.VERSION,
            "timestamp": self._timestamp(),
            "alive": True,
            "pid": os.getpid(),
            "frame_count": int(app.sim.frame_count),
            "simulation_time": float(app.sim.time),
            "fps_ema": round(self._fps_ema, 2),
            "recording": bool(app.video_service.is_active()),
            "recording_frame": int(app.video_service.current_frame),
            "recording_max_frames": int(prefs.recording.max_frames),
            "ui_visible": bool(app.ui.show_sidebar),
            "simulation": {
                "going": bool(ui_state.sim.going),
                "entity_count": int(app.sim.entity_count),
                "canvas_resolution": int(prefs.rendering.canvas_resolution),
                "rule_seed": float(ui_state.sim.rule_seed),
                "mutation_scale": float(ui_state.sim.MUTATION_SCALE),
                "trail_persistence": float(ui_state.sim.TRAIL_PERSISTENCE),
                "trail_diffusion": float(ui_state.sim.TRAIL_DIFFUSION),
                "cohorts": int(ui_state.sim.num_cohorts),
            },
            "renderer": {
                "selected": int(prefs.rendering.renderer),
                "rt_mode": int(prefs.rendering.rt_mode),
                "framebuffer_size": list(glfw.get_framebuffer_size(app.window)),
                "window_visible": bool(glfw.get_window_attrib(app.window, glfw.VISIBLE)),
                "optix_active": bool(optix is not None and not optix.failed),
                "optix_failed": bool(optix is not None and optix.failed),
                "optix_fail_reason": "" if optix is None else str(optix.fail_reason),
                "gas_time_ms": float(ui_state.camera.pathtracer_gas_time_ms),
                "render_time_ms": float(ui_state.camera.pathtracer_render_time_ms),
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
        if section == "preferences":
            self._apply_preferences(ui_state, values)
            return

        targets = {
            "sim": ui_state.sim,
            "camera": ui_state.camera,
            "controller": app.controller_cam,
        }
        if section not in targets:
            raise ValueError(f"unsupported state section {section!r}")
        target = targets[section]
        allowed = ({field.name for field in fields(target)} if is_dataclass(target)
                   else {"pos", "yaw", "pitch", "fov"})
        for name, value in values.items():
            if name not in allowed or name.startswith("_"):
                raise ValueError(f"unsupported field {section}.{name}")
            current = getattr(target, name)
            setattr(target, name, self._coerce_value(current, value, f"{section}.{name}"))
        if section == "controller" and ({"yaw", "pitch"} & values.keys()):
            app.controller_cam._update_vectors()

    def _apply_preferences(self, ui_state, values: dict[str, Any]) -> None:
        prefs = ui_state.preferences
        slice_names = {field.name for field in fields(prefs)}
        for slice_name, slice_values in values.items():
            if slice_name not in slice_names or slice_name.startswith("_"):
                raise ValueError(f"unsupported preference slice {slice_name!r}")
            if not isinstance(slice_values, dict):
                raise TypeError(f"preferences.{slice_name} must be an object")
            target = getattr(prefs, slice_name)
            allowed = {field.name for field in fields(target)}
            for name, value in slice_values.items():
                if name not in allowed or name.startswith("_"):
                    raise ValueError(f"unsupported field preferences.{slice_name}.{name}")
                current = getattr(target, name)
                setattr(target, name, self._coerce_value(
                    current, value, f"preferences.{slice_name}.{name}"))
        rendering = values.get("rendering", {})
        if {"entity_count", "canvas_resolution"} & rendering.keys():
            ui_state.request_world_size_change = True

    def _apply_action(self, app, ui_state, action: str | dict[str, Any]) -> None:
        options: dict[str, Any] = action if isinstance(action, dict) else {}
        name = str(options.get("name", "")) if options else str(action)
        if not name:
            raise ValueError("action name is required")

        if name == "pause":
            ui_state.sim.going = False
        elif name == "resume":
            ui_state.sim.going = True
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
        elif name == "renderer_optix":
            ui_state.preferences.rendering.renderer = 1
            ui_state.camera.optix_enabled = True
        elif name == "renderer_opengl":
            ui_state.preferences.rendering.renderer = 0
            ui_state.camera.optix_enabled = False
        elif name == "show_ui":
            app.ui.show_sidebar = True
        elif name == "hide_ui":
            app.ui.show_sidebar = False
        elif name == "screenshot":
            label = self._safe_label(str(options.get("label") or "search"))
            ui_state.preferences.recording.filename_prefix = label
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
        elif name == "window_size":
            import glfw

            width = int(options.get("width", 1280))
            height = int(options.get("height", 720))
            if width < 320 or height < 240 or width > 3840 or height > 2160:
                raise ValueError("window_size must be between 320x240 and 3840x2160")
            glfw.restore_window(app.window)
            glfw.set_window_size(app.window, width, height)
            if bool(options.get("hidden", False)):
                glfw.hide_window(app.window)
        elif name == "vsync_off":
            import glfw

            glfw.swap_interval(0)
        elif name == "vsync_on":
            import glfw

            glfw.swap_interval(1)
        elif name == "mark":
            self._append_event(app, "marker", str(options.get("label") or "interesting"),
                               options.get("note", ""))
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

    @staticmethod
    def _safe_label(value: str) -> str:
        return _SAFE_LABEL.sub("-", value).strip("-._")[:100] or "command"

    @staticmethod
    def _latest_artifact(directory: Path, pattern: str) -> str:
        matches = list(directory.rglob(pattern)) if directory.exists() else []
        return str(max(matches, key=lambda path: path.stat().st_mtime)) if matches else ""

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temporary, path)
