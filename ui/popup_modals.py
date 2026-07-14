"""Popup modal dialogs: Save, Overwrite, Delete confirmations."""
from imgui_bundle import imgui


class PopupModalsMixin:
    """Mixin for popup modal dialogs. Combined into UI via multiple inheritance."""

    def render_popup_modals(self):
        """Render popup modals (Save, Overwrite, Delete) - called regardless of sidebar visibility."""
        # Save popup modal
        if self.save_popup_open:
            imgui.open_popup("Save Config")

        if imgui.begin_popup_modal("Save Config", flags=imgui.WindowFlags_.always_auto_resize)[0]:
            imgui.text("Enter filename (without extension):")
            _, self.save_filename_buffer = imgui.input_text(
                "##filename",
                self.save_filename_buffer,
            )

            imgui.separator()
            if imgui.button("Save", imgui.ImVec2(120, 0)):
                if self.save_filename_buffer.strip():
                    filename = self.save_filename_buffer.strip()
                    filepath = self.user_configs_dir / f"{filename}.json"
                    if filepath.exists():
                        # File exists, need overwrite confirmation
                        # Close save popup first, then open overwrite popup
                        self.overwrite_confirm_filename = filename
                        self.save_popup_open = False
                        imgui.close_current_popup()
                    else:
                        # File doesn't exist, save directly
                        self._save_filename = filename
                        self._request_save_file = True
                        self.save_popup_open = False
                        imgui.close_current_popup()
            imgui.same_line()
            if imgui.button("Cancel", imgui.ImVec2(120, 0)):
                self.save_popup_open = False
                imgui.close_current_popup()
            imgui.end_popup()

        # Overwrite confirmation popup
        if self.overwrite_confirm_filename:
            imgui.open_popup("Overwrite?")

        if imgui.begin_popup_modal("Overwrite?", flags=imgui.WindowFlags_.always_auto_resize)[0]:
            imgui.text(f"File '{self.overwrite_confirm_filename}.json' already exists.")
            imgui.text("Do you want to overwrite it?")
            imgui.separator()
            if imgui.button("Overwrite", imgui.ImVec2(120, 0)):
                self._save_filename = self.overwrite_confirm_filename
                self._request_save_file = True
                self.overwrite_confirm_filename = None
                self.save_popup_open = False
                imgui.close_current_popup()
            imgui.same_line()
            if imgui.button("Cancel", imgui.ImVec2(120, 0)):
                self.overwrite_confirm_filename = None
                imgui.close_current_popup()
            imgui.end_popup()

        # Editor settings save popup
        if self.editor_save_popup_open:
            imgui.open_popup("Save Editor Settings")

        if imgui.begin_popup_modal("Save Editor Settings", flags=imgui.WindowFlags_.always_auto_resize)[0]:
            imgui.text("Enter a name (without extension):")
            _, self._save_editor_name_buffer = imgui.input_text(
                "##editor_name", self._save_editor_name_buffer)
            imgui.separator()
            if imgui.button("Save", imgui.ImVec2(120, 0)):
                name = self._save_editor_name_buffer.strip()
                if name:
                    self.editor_save_popup_open = False
                    imgui.close_current_popup()
                    # If a save with this name exists, confirm overwrite first.
                    if self.editor_saver and self.editor_saver.exists(name):
                        self._editor_overwrite_name = name
                    else:
                        self._save_editor_name = name
                        self._request_save_editor = True
            imgui.same_line()
            if imgui.button("Cancel", imgui.ImVec2(120, 0)):
                self.editor_save_popup_open = False
                imgui.close_current_popup()
            imgui.end_popup()

        # Editor settings overwrite confirmation
        if self._editor_overwrite_name:
            imgui.open_popup("Overwrite Editor Settings?")

        if imgui.begin_popup_modal("Overwrite Editor Settings?", flags=imgui.WindowFlags_.always_auto_resize)[0]:
            imgui.text(f"'{self._editor_overwrite_name}' already exists.")
            imgui.text("Do you want to overwrite it?")
            imgui.separator()
            if imgui.button("Overwrite", imgui.ImVec2(120, 0)):
                self._save_editor_name = self._editor_overwrite_name
                self._request_save_editor = True
                self._editor_overwrite_name = None
                imgui.close_current_popup()
            imgui.same_line()
            if imgui.button("Cancel", imgui.ImVec2(120, 0)):
                self._editor_overwrite_name = None
                imgui.close_current_popup()
            imgui.end_popup()

        # Simulation state save popup
        if self.simulation_save_popup_open:
            imgui.open_popup("Save Simulation State")

        if imgui.begin_popup_modal("Save Simulation State", flags=imgui.WindowFlags_.always_auto_resize)[0]:
            imgui.text("Enter a name (without extension):")
            _, self._save_simulation_name_buffer = imgui.input_text(
                "##simulation_name", self._save_simulation_name_buffer)
            imgui.separator()
            if imgui.button("Save", imgui.ImVec2(120, 0)):
                name = self._save_simulation_name_buffer.strip()
                if name:
                    self.simulation_save_popup_open = False
                    imgui.close_current_popup()
                    if self.simulation_saver and self.simulation_saver.exists(name):
                        self._simulation_overwrite_name = name
                    else:
                        self._save_simulation_name = name
                        self._request_save_simulation = True
            imgui.same_line()
            if imgui.button("Cancel", imgui.ImVec2(120, 0)):
                self.simulation_save_popup_open = False
                imgui.close_current_popup()
            imgui.end_popup()

        # Simulation state overwrite confirmation
        if self._simulation_overwrite_name:
            imgui.open_popup("Overwrite Simulation State?")

        if imgui.begin_popup_modal("Overwrite Simulation State?", flags=imgui.WindowFlags_.always_auto_resize)[0]:
            imgui.text(f"'{self._simulation_overwrite_name}' already exists.")
            imgui.text("Do you want to overwrite it?")
            imgui.separator()
            if imgui.button("Overwrite", imgui.ImVec2(120, 0)):
                self._save_simulation_name = self._simulation_overwrite_name
                self._request_save_simulation = True
                self._simulation_overwrite_name = None
                imgui.close_current_popup()
            imgui.same_line()
            if imgui.button("Cancel", imgui.ImVec2(120, 0)):
                self._simulation_overwrite_name = None
                imgui.close_current_popup()
            imgui.end_popup()

        # Render spec overwrite confirmation (save button lives in the Screen
        # Recording window; it routes here when the name already exists on disk).
        if self._render_spec_overwrite_name:
            imgui.open_popup("Overwrite Render Spec?")

        if imgui.begin_popup_modal("Overwrite Render Spec?", flags=imgui.WindowFlags_.always_auto_resize)[0]:
            imgui.text(f"'{self._render_spec_overwrite_name}' already exists.")
            imgui.text("Do you want to overwrite it?")
            imgui.separator()
            if imgui.button("Overwrite", imgui.ImVec2(120, 0)):
                self._save_render_spec_name = self._render_spec_overwrite_name
                self._request_save_render_spec = True
                self._render_spec_overwrite_name = None
                imgui.close_current_popup()
            imgui.same_line()
            if imgui.button("Cancel", imgui.ImVec2(120, 0)):
                self._render_spec_overwrite_name = None
                imgui.close_current_popup()
            imgui.end_popup()

        # Editor settings delete confirmation
        if self._editor_delete_path:
            imgui.open_popup("Delete Editor Settings?")

        if imgui.begin_popup_modal("Delete Editor Settings?", flags=imgui.WindowFlags_.always_auto_resize)[0]:
            name = self._editor_delete_path.name[:-len('.editor.json')]
            imgui.text(f"Are you sure you want to delete '{name}'?")
            imgui.separator()
            if imgui.button("Delete", imgui.ImVec2(120, 0)):
                if self.editor_saver:
                    self.editor_saver.delete(self._editor_delete_path)
                self._editor_delete_path = None
                self._refresh_editor_save_files()
                imgui.close_current_popup()
            imgui.same_line()
            if imgui.button("Cancel", imgui.ImVec2(120, 0)):
                self._editor_delete_path = None
                imgui.close_current_popup()
            imgui.end_popup()

        # Simulation state delete confirmation
        if self._simulation_delete_path:
            imgui.open_popup("Delete Simulation State?")

        if imgui.begin_popup_modal("Delete Simulation State?", flags=imgui.WindowFlags_.always_auto_resize)[0]:
            name = self._simulation_delete_path.name[:-len('.fsim')]
            imgui.text(f"Are you sure you want to delete '{name}'?")
            imgui.separator()
            if imgui.button("Delete", imgui.ImVec2(120, 0)):
                if self.simulation_saver:
                    self.simulation_saver.delete(self._simulation_delete_path)
                self._simulation_delete_path = None
                self._refresh_simulation_save_dirs()
                imgui.close_current_popup()
            imgui.same_line()
            if imgui.button("Cancel", imgui.ImVec2(120, 0)):
                self._simulation_delete_path = None
                imgui.close_current_popup()
            imgui.end_popup()

        # Delete confirmation popup
        if self.delete_confirm_filename:
            imgui.open_popup("Delete Config?")

        if imgui.begin_popup_modal("Delete Config?", flags=imgui.WindowFlags_.always_auto_resize)[0]:
            # Show category in dialog if not Custom (to clarify which file will be deleted)
            category_hint = f" ({self.delete_confirm_category})" if self.delete_confirm_category and self.delete_confirm_category != "Custom" else ""
            imgui.text(f"Are you sure you want to delete '{self.delete_confirm_filename}.json'{category_hint}?")
            imgui.separator()
            if imgui.button("Delete", imgui.ImVec2(120, 0)):
                self._delete_filename = self.delete_confirm_filename
                self._delete_category = self.delete_confirm_category or ""
                self._request_delete_file = True
                self.delete_confirm_filename = None
                self.delete_confirm_category = None
                imgui.close_current_popup()
            imgui.same_line()
            if imgui.button("Cancel", imgui.ImVec2(120, 0)):
                self.delete_confirm_filename = None
                self.delete_confirm_category = None
                imgui.close_current_popup()
            imgui.end_popup()
