"""Config clipboard window with hover preview (Step 9).

Renamed from the misnamed `history_window.py`. Renders the in-memory config
clipboard (Ctrl+C checkpoints) with hover-preview, click-to-load, right-click
rename, and delete. Reads/writes `self.clipboard_state` (a `ConfigClipboardState`)
and raises the same one-shot flags the orchestrator already handles. Combined
into UI via multiple inheritance.
"""
from imgui_bundle import imgui


class ConfigClipboardWindowMixin:
    """Mixin for the config clipboard window."""

    def _init_config_clipboard_flags(self):
        """Initialize config-clipboard one-shot flags. Called from UI.__init__."""
        self._request_preview_clipboard_config = False
        self._request_clear_clipboard_preview = False
        self._request_load_clipboard_config = False
        self._request_delete_clipboard_config = False
        self._clipboard_config_index = -1

    def _marshal_config_clipboard_state(self, state):
        """Copy config-clipboard one-shot flags into state, then reset them."""
        state.request_preview_clipboard_config = self._request_preview_clipboard_config
        state.request_clear_clipboard_preview = self._request_clear_clipboard_preview
        state.request_load_clipboard_config = self._request_load_clipboard_config
        state.request_delete_clipboard_config = self._request_delete_clipboard_config
        state.clipboard_config_index = self._clipboard_config_index

        self._request_preview_clipboard_config = False
        self._request_clear_clipboard_preview = False
        self._request_load_clipboard_config = False
        self._request_delete_clipboard_config = False
        self._clipboard_config_index = -1

    def render_config_clipboard_window(self):
        """Render config clipboard window with hover preview."""
        cs = self.clipboard_state

        expanded, opened = imgui.begin("Config Clipboard - EXPERIMENTAL", True)
        if not opened:
            self.state.preferences.ui_windows.show_config_clipboard_window = False
            imgui.end()
            return

        imgui.text_colored(imgui.ImVec4(0.6, 0.6, 0.6, 1.0), "Press Ctrl+C to add a checkpoint")
        imgui.separator()

        if not cs.entries:
            imgui.text_colored(imgui.ImVec4(0.6, 0.6, 0.6, 1.0), "No checkpoints yet")
            imgui.end()
            return

        # Render entries (newest first)
        hovered_this_frame = None

        for i in range(len(cs.entries) - 1, -1, -1):
            entry = cs.entries[i]

            # Selectable label for click/hover detection
            # Use allow_overlap so the X button can receive clicks on the same line
            clicked, _ = imgui.selectable(
                f"{entry.label}##clip_{i}",
                cs.previewing_index == i,
                imgui.SelectableFlags_.allow_overlap,
                imgui.ImVec2(0, 0)
            )

            if imgui.is_item_hovered():
                hovered_this_frame = i

            # Right-click opens rename popup
            if imgui.is_item_clicked(imgui.MouseButton_.right):
                cs.renaming_index = i
                cs.rename_buffer = entry.label
                imgui.open_popup(f"rename_clip_{i}")

            # X button on the same line
            imgui.same_line()
            imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.8, 0.2, 0.2, 1.0))
            imgui.push_style_color(imgui.Col_.button_hovered, imgui.ImVec4(1.0, 0.3, 0.3, 1.0))
            if imgui.small_button(f"X##clip_{i}"):
                self._request_delete_clipboard_config = True
                self._clipboard_config_index = i
            imgui.pop_style_color(2)

            if imgui.is_item_hovered():
                hovered_this_frame = i

            if clicked:
                self._request_load_clipboard_config = True
                self._clipboard_config_index = i

            # Rename popup
            if imgui.begin_popup(f"rename_clip_{i}"):
                imgui.text("Rename:")
                imgui.set_next_item_width(200)
                # Auto-focus the input on first appearance
                if imgui.is_window_appearing():
                    imgui.set_keyboard_focus_here()
                changed, cs.rename_buffer = imgui.input_text(
                    f"##rename_input_{i}", cs.rename_buffer)
                if imgui.is_item_deactivated_after_edit():
                    # Enter pressed or focus lost after editing — commit rename
                    if cs.rename_buffer.strip():
                        cs.entries[i].label = cs.rename_buffer.strip()
                    cs.renaming_index = None
                    imgui.close_current_popup()
                imgui.end_popup()

        # Handle preview state changes
        if hovered_this_frame != cs.previewing_index:
            if cs.previewing_index is not None:
                self._request_clear_clipboard_preview = True

            if hovered_this_frame is not None:
                self._request_preview_clipboard_config = True
                self._clipboard_config_index = hovered_this_frame
                cs.previewing_index = hovered_this_frame
            else:
                cs.previewing_index = None

        imgui.end()
