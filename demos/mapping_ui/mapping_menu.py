"""Mapping menu: data model, pinnable window rendering, and custom slider UI."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import IntEnum
from imgui_bundle import imgui

from .params import (
    PARAM_BY_NAME, generate_uniforms_local, generate_uniforms_global,
    generate_function, get_function_prefix, get_function_suffix,
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class MappingType(IntEnum):
    NONE = 0
    JITTER = 1
    SWEEP = 2
    FIELD = 3
    SHADER = 4
    CUSTOM = 5


MAPPING_TYPE_NAMES = ["None", "Jitter", "Sweep", "Field", "Shader", "Custom"]


@dataclass
class CustomSlider:
    """A user-added custom slider within a Custom mapping."""
    name: str           # internal id, e.g. 'axial_force_custom_slider0'
    display_name: str   # shown as label and used as uniform name (can be renamed)
    value: float = 0.0
    min_val: float = 0.0
    max_val: float = 1.0


@dataclass
class MappingState:
    """Persistent state for one parameter's mapping configuration."""
    param_name: str
    mapping_type: MappingType = MappingType.NONE

    # Main slider range override (None = use ParamDef defaults)
    slider_min: float | None = None
    slider_max: float | None = None

    # Jitter
    jitter_amount: float = 0.5

    # Custom
    custom_sliders: list[CustomSlider] = field(default_factory=list)
    custom_code: str = ""
    _custom_code_buffer: str = ""  # live edit buffer (committed on Enter)
    _slider_counter: int = 0

    # Custom slider rename state
    _renaming_slider_idx: int | None = None
    _rename_buffer: str = ""


@dataclass
class MappingMenuWindow:
    """Tracks the windowing/pinning state of one open mapping menu."""
    param_name: str
    is_open: bool = True

    # Pinnable behaviour
    initial_pos: tuple[float, float] = (0.0, 0.0)
    has_been_positioned: bool = False
    is_pinned: bool = False
    _frames_since_open: int = 0

    # Uniforms display mode
    show_global_uniforms: bool = False


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_mapping_menu(
    menu: MappingMenuWindow,
    mapping: MappingState,
    all_mappings: dict[str, MappingState],
    close_distance: float = 120.0,
) -> bool:
    """Render a single mapping menu window.

    Returns True if the window should stay open, False if it should close.
    """
    pdef = PARAM_BY_NAME[menu.param_name]
    window_name = f"Mapping: {pdef.label}##{menu.param_name}"

    # First frame: position at mouse click location
    if not menu.has_been_positioned:
        imgui.set_next_window_pos(imgui.ImVec2(*menu.initial_pos))
        imgui.set_next_window_size(imgui.ImVec2(440, 0))
        menu.has_been_positioned = True

    # Pinned windows show the X close button
    if menu.is_pinned:
        expanded, still_open = imgui.begin(window_name, True)
        if not still_open:
            imgui.end()
            return False
    else:
        expanded = imgui.begin(window_name)
        still_open = True

    if not expanded:
        imgui.end()
        return still_open

    menu._frames_since_open += 1

    # --- Drag detection ---
    win_pos = imgui.get_window_pos()
    if menu._frames_since_open > 3 and not menu.is_pinned:
        dx = abs(win_pos.x - menu.initial_pos[0])
        dy = abs(win_pos.y - menu.initial_pos[1])
        if dx > 5.0 or dy > 5.0:
            menu.is_pinned = True

    # --- Auto-close for unpinned ---
    if not menu.is_pinned and menu._frames_since_open > 10:
        mouse = imgui.get_mouse_pos()
        win_size = imgui.get_window_size()
        ddx = max(win_pos.x - mouse.x, 0.0, mouse.x - (win_pos.x + win_size.x))
        ddy = max(win_pos.y - mouse.y, 0.0, mouse.y - (win_pos.y + win_size.y))
        dist = (ddx * ddx + ddy * ddy) ** 0.5
        if dist > close_distance:
            imgui.end()
            return False

    # === Min/Max range controls for main slider ===
    pdef = PARAM_BY_NAME[menu.param_name]
    if mapping.slider_min is None:
        mapping.slider_min = pdef.default_min
    if mapping.slider_max is None:
        mapping.slider_max = pdef.default_max

    imgui.text("Slider Range:")
    imgui.same_line()
    imgui.push_item_width(80)
    changed_min, new_min = imgui.drag_float(
        f"Min##{menu.param_name}_range", mapping.slider_min, 0.01, format="%.3f")
    if changed_min:
        mapping.slider_min = new_min
    imgui.same_line()
    changed_max, new_max = imgui.drag_float(
        f"Max##{menu.param_name}_range", mapping.slider_max, 0.01, format="%.3f")
    if changed_max:
        mapping.slider_max = new_max
    imgui.pop_item_width()

    imgui.separator()

    # === Radio buttons ===
    for i, type_name in enumerate(MAPPING_TYPE_NAMES):
        if i > 0:
            imgui.same_line()
        if imgui.radio_button(f"{type_name}##{menu.param_name}", int(mapping.mapping_type) == i):
            mapping.mapping_type = MappingType(i)
            # When switching to Custom, seed the code buffer from existing custom_code
            if mapping.mapping_type == MappingType.CUSTOM:
                mapping._custom_code_buffer = mapping.custom_code

    imgui.separator()

    # === Controls section ===
    _render_controls(menu, mapping)

    imgui.separator()

    # === Uniforms text box ===
    _render_uniforms_section(menu, mapping, all_mappings)

    imgui.separator()

    # === GLSL function text box ===
    _render_function_section(menu, mapping)

    imgui.end()
    return True


# ---------------------------------------------------------------------------
# Controls per mapping type
# ---------------------------------------------------------------------------

def _render_controls(menu: MappingMenuWindow, mapping: MappingState):
    pname = menu.param_name

    if mapping.mapping_type == MappingType.NONE:
        imgui.text_colored(imgui.ImVec4(0.5, 0.5, 0.5, 1.0), "No mapping controls")

    elif mapping.mapping_type == MappingType.JITTER:
        changed, new_val = imgui.slider_float(
            f"Jitter Amount##{pname}", mapping.jitter_amount, 0.0, 2.0, "%.3f")
        if changed:
            mapping.jitter_amount = new_val

    elif mapping.mapping_type in (MappingType.SWEEP, MappingType.FIELD, MappingType.SHADER):
        imgui.text_colored(
            imgui.ImVec4(0.5, 0.5, 0.5, 1.0),
            f"({MAPPING_TYPE_NAMES[int(mapping.mapping_type)]} controls - placeholder)",
        )

    elif mapping.mapping_type == MappingType.CUSTOM:
        _render_custom_controls(menu, mapping)


def _render_custom_controls(menu: MappingMenuWindow, mapping: MappingState):
    pname = menu.param_name
    base = pname.lower()

    # "Add Slider" button
    if imgui.button(f"Add Slider##{pname}"):
        idx = mapping._slider_counter
        default_name = f"{base}_custom_slider{idx}"
        mapping.custom_sliders.append(CustomSlider(
            name=default_name,
            display_name=default_name,
        ))
        mapping._slider_counter += 1

    # Render custom sliders
    remove_idx = None
    for i, cs in enumerate(mapping.custom_sliders):
        imgui.push_item_width(imgui.get_content_region_avail().x * 0.7)
        changed, new_val = imgui.slider_float(
            f"{cs.display_name}##{pname}_cs_{i}", cs.value, cs.min_val, cs.max_val, "%.3f")
        if changed:
            cs.value = new_val
        imgui.pop_item_width()

        # Right-click context menu
        if imgui.begin_popup_context_item(f"cs_ctx_{pname}_{i}"):
            if imgui.menu_item("Remove", "", False, True)[0]:
                remove_idx = i

            if imgui.menu_item("Rename", "", False, True)[0]:
                mapping._renaming_slider_idx = i
                mapping._rename_buffer = cs.display_name

            imgui.separator()
            imgui.text("Range:")
            imgui.push_item_width(120)
            changed_min, new_min = imgui.drag_float(f"Min##cs_{pname}_{i}", cs.min_val, 0.01)
            if changed_min:
                cs.min_val = new_min
            changed_max, new_max = imgui.drag_float(f"Max##cs_{pname}_{i}", cs.max_val, 0.01)
            if changed_max:
                cs.max_val = new_max
            imgui.pop_item_width()

            imgui.end_popup()

    if remove_idx is not None:
        mapping.custom_sliders.pop(remove_idx)

    # Inline rename widget
    if mapping._renaming_slider_idx is not None:
        idx = mapping._renaming_slider_idx
        if 0 <= idx < len(mapping.custom_sliders):
            imgui.text("Rename slider:")
            imgui.same_line()
            imgui.push_item_width(imgui.get_content_region_avail().x)
            enter_pressed, mapping._rename_buffer = imgui.input_text(
                f"##rename_{pname}", mapping._rename_buffer,
                imgui.InputTextFlags_.enter_returns_true,
            )
            imgui.pop_item_width()
            if enter_pressed and mapping._rename_buffer.strip():
                mapping.custom_sliders[idx].display_name = mapping._rename_buffer.strip()
                mapping._renaming_slider_idx = None
        else:
            mapping._renaming_slider_idx = None


# ---------------------------------------------------------------------------
# Uniforms section
# ---------------------------------------------------------------------------

def _render_uniforms_section(
    menu: MappingMenuWindow,
    mapping: MappingState,
    all_mappings: dict[str, MappingState],
):
    pname = menu.param_name

    # Clickable header to toggle local / global
    if menu.show_global_uniforms:
        header = "//Custom Uniforms - Global"
    else:
        header = "//Custom Uniforms - Local"

    if imgui.button(f"{header}##{pname}_uniforms_toggle"):
        menu.show_global_uniforms = not menu.show_global_uniforms

    if menu.show_global_uniforms:
        text = generate_uniforms_global(all_mappings)
    else:
        text = generate_uniforms_local(pname, mapping)

    if not text:
        text = "// (none)"

    imgui.text_colored(imgui.ImVec4(0.6, 0.8, 0.6, 1.0), text)


# ---------------------------------------------------------------------------
# Function section
# ---------------------------------------------------------------------------

def _render_function_section(menu: MappingMenuWindow, mapping: MappingState):
    pname = menu.param_name

    if mapping.mapping_type == MappingType.CUSTOM:
        # Prefix (read-only)
        prefix = get_function_prefix(pname)
        imgui.text_colored(imgui.ImVec4(0.6, 0.8, 0.6, 1.0), prefix)

        # Editable code body (Enter to confirm)
        imgui.push_item_width(-1)
        enter_pressed, mapping._custom_code_buffer = imgui.input_text(
            f"##custom_code_{pname}",
            mapping._custom_code_buffer,
            imgui.InputTextFlags_.enter_returns_true,
        )
        imgui.pop_item_width()
        if enter_pressed:
            mapping.custom_code = mapping._custom_code_buffer

        # Suffix (read-only)
        suffix = get_function_suffix()
        imgui.text_colored(imgui.ImVec4(0.6, 0.8, 0.6, 1.0), suffix)
    else:
        # Full generated function (read-only plain text)
        func_text = generate_function(pname, mapping)
        imgui.text_colored(imgui.ImVec4(0.6, 0.8, 0.6, 1.0), func_text)
