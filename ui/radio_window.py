"""Radio window: visibility filter by frequency band."""
from imgui_bundle import imgui


class RadioWindowMixin:
    """Mixin for the Radio window. Combined into UI via multiple inheritance."""

    def render_radio_window(self):
        """Render the Radio window with enable checkbox and two sliders."""
        visible, opened = imgui.begin("Radio", True)
        if not opened:
            self.state.preferences.ui_windows.show_radio_window = False
            imgui.end()
            return
        if visible:
            changed, val = imgui.checkbox(
                "Radio enabled",
                self.state.sim.RADIO_ENABLED > 0
            )
            if changed:
                self.state.sim.RADIO_ENABLED = 1 if val else 0

            changed, new_val = imgui.slider_float(
                "Target Frequency",
                self.state.sim.RADIO_TARGET_FREQ,
                -15.0, 15.0
            )
            if changed:
                self.state.sim.RADIO_TARGET_FREQ = new_val

            changed, new_val = imgui.slider_float(
                "Bandwidth",
                self.state.sim.RADIO_BANDWIDTH,
                0.0, 2.0
            )
            if changed:
                self.state.sim.RADIO_BANDWIDTH = new_val
        imgui.end()
