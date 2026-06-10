"""Scheduled Renders window: queue render specs for batch rendering."""
import shutil
from imgui_bundle import imgui
from pathlib import Path


class ScheduledRendersWindowMixin:
    """Mixin for the Scheduled Renders window. Combined into UI via multiple inheritance."""

    def _init_scheduled_renders_state(self):
        """Initialize scheduled renders state. Called from UI.__init__."""
        self._render_queue = []  # list of (RenderSpec, display_name, dir_path)
        self._render_spec_files = []  # scanned .frs directory paths
        self._render_specs_scanned = False  # auto-scan on first open
        self._selected_spec_index = 0  # dropdown selection index
        self._queue_renaming_index = None  # which queue item is being renamed
        self._queue_rename_buffer = ""  # text buffer for rename popup
        self._delete_all_specs_confirm = False  # "are you sure?" guard

        # One-shot flags for preview
        self._request_preview_render_spec = False
        self._preview_render_spec_path = ""

    def _refresh_render_spec_files(self):
        """Scan disk for available .frs directories."""
        if self.render_spec_service is not None:
            self._render_spec_files = self.render_spec_service.list_available_specs()
        else:
            self._render_spec_files = []

    def render_scheduled_renders_window(self):
        """Render the Scheduled Renders window."""
        expanded, opened = imgui.begin("Scheduled Renders", True)
        if not opened:
            self.state.preferences.show_scheduled_renders_window = False
            imgui.end()
            return

        if not expanded:
            imgui.end()
            return

        # Auto-scan on first open
        if not self._render_specs_scanned:
            self._refresh_render_spec_files()
            self._render_specs_scanned = True

        # --- Available specs dropdown + Load / Load All buttons ---
        imgui.text("Available:")
        imgui.same_line()

        # Refresh button
        if imgui.small_button("Refresh"):
            self._refresh_render_spec_files()

        # Build display names for dropdown
        spec_names = [p.stem for p in self._render_spec_files]
        if not spec_names:
            spec_names = ["(none)"]

        # Clamp selection index
        if self._selected_spec_index >= len(spec_names):
            self._selected_spec_index = 0

        imgui.set_next_item_width(-1)
        changed, self._selected_spec_index = imgui.combo(
            "##spec_dropdown",
            self._selected_spec_index,
            spec_names
        )

        load_disabled = not self._render_spec_files
        if load_disabled:
            imgui.begin_disabled()
        if imgui.button("Load"):
            self._load_spec_into_queue(self._render_spec_files[self._selected_spec_index])
        imgui.same_line()
        if imgui.button("Load All"):
            for spec_path in self._render_spec_files:
                self._load_spec_into_queue(spec_path)
        if load_disabled:
            imgui.end_disabled()

        imgui.separator()

        # --- Render Queue ---
        imgui.text("Render Queue:")

        if not self._render_queue:
            imgui.text_colored(imgui.ImVec4(0.6, 0.6, 0.6, 1.0), "  (empty)")
        else:
            to_remove = None
            for i, (spec, display_name, dir_path) in enumerate(self._render_queue):
                # Selectable for click-to-preview
                clicked, _ = imgui.selectable(
                    f"  {display_name}##queue_{i}",
                    False,
                    imgui.SelectableFlags_.allow_overlap,
                    imgui.ImVec2(0, 0)
                )

                # Click to preview (destructive apply)
                if clicked:
                    self._request_preview_render_spec = True
                    self._preview_render_spec_path = str(dir_path)

                # Right-click opens rename popup
                if imgui.is_item_clicked(imgui.MouseButton_.right):
                    self._queue_renaming_index = i
                    self._queue_rename_buffer = display_name
                    imgui.open_popup(f"rename_queue_{i}")

                # Tooltip for click/right-click
                if imgui.is_item_hovered():
                    imgui.set_tooltip("Click to preview (applies state)\nRight-click to rename")

                # X button to remove from queue
                imgui.same_line()
                imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.8, 0.2, 0.2, 1.0))
                imgui.push_style_color(imgui.Col_.button_hovered, imgui.ImVec4(1.0, 0.3, 0.3, 1.0))
                if imgui.small_button(f"X##queue_{i}"):
                    to_remove = i
                imgui.pop_style_color(2)

                # Rename popup
                if imgui.begin_popup(f"rename_queue_{i}"):
                    imgui.text("Rename:")
                    imgui.set_next_item_width(200)
                    if imgui.is_window_appearing():
                        imgui.set_keyboard_focus_here()
                    changed, self._queue_rename_buffer = imgui.input_text(
                        f"##rename_queue_input_{i}", self._queue_rename_buffer, 256)
                    if imgui.is_item_deactivated_after_edit():
                        if self._queue_rename_buffer.strip():
                            spec_item, _old_name, path = self._render_queue[i]
                            self._render_queue[i] = (spec_item, self._queue_rename_buffer.strip(), path)
                        self._queue_renaming_index = None
                        imgui.close_current_popup()
                    imgui.end_popup()

            # Process removal after iteration
            if to_remove is not None:
                self._render_queue.pop(to_remove)

        imgui.separator()

        # --- Execute button (greyed out — wired in Step 4) ---
        imgui.begin_disabled()
        imgui.button("Execute All Renders")
        imgui.end_disabled()
        if imgui.is_item_hovered(imgui.HoveredFlags_.allow_when_disabled):
            imgui.set_tooltip("Coming soon: batch render all queued specs")

        # --- Delete All Specs from disk ---
        imgui.spacing()
        if not self._delete_all_specs_confirm:
            imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.5, 0.15, 0.15, 1.0))
            imgui.push_style_color(imgui.Col_.button_hovered, imgui.ImVec4(0.7, 0.2, 0.2, 1.0))
            if imgui.button("Delete All Specs"):
                self._delete_all_specs_confirm = True
            imgui.pop_style_color(2)
        else:
            imgui.text_colored(imgui.ImVec4(1.0, 0.4, 0.4, 1.0), "Delete all .frs folders from disk?")
            if imgui.button("Yes, Delete All"):
                self._delete_all_specs_from_disk()
                self._delete_all_specs_confirm = False
            imgui.same_line()
            if imgui.button("Cancel"):
                self._delete_all_specs_confirm = False

        imgui.end()

    def _load_spec_into_queue(self, dir_path: Path):
        """Load a render spec's metadata and add it to the queue."""
        if self.render_spec_service is None:
            return
        spec = self.render_spec_service.load_metadata(dir_path)
        if spec is not None:
            self._render_queue.append((spec, spec.display_name, dir_path))
            print(f"Loaded render spec into queue: {spec.display_name}")
        else:
            print(f"Failed to load render spec from: {dir_path}")

    def _delete_all_specs_from_disk(self):
        """Delete all .frs directories from the RenderSpecs folder."""
        if self.render_spec_service is None:
            return
        specs = self.render_spec_service.list_available_specs()
        count = 0
        for spec_path in specs:
            try:
                shutil.rmtree(spec_path)
                count += 1
            except Exception as e:
                print(f"Failed to delete {spec_path}: {e}")
        print(f"Deleted {count} render spec(s) from disk")
        self._render_queue.clear()
        self._refresh_render_spec_files()
