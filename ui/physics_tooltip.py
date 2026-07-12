"""Physics-parameter tooltip: animated shader graphic + hover tracking (Step 9).

Split out of the old `history_window.py` (which conflated the config clipboard
and this tooltip). Owns the tooltip GPU resources (`setup_tooltip_shader`) and
the shared `self.*` hover-tracking state that `slider_widgets` and
`physics_window` write via `render_custom_tooltip`. Combined into UI via multiple
inheritance.
"""
import time
import numpy as np
import moderngl
from imgui_bundle import imgui


class PhysicsTooltipMixin:
    """Mixin for the physics-slider tooltip graphic."""

    def setup_tooltip_shader(self):
        """Create shader program and texture for tooltip graphics."""
        # Tooltip hover-tracking state (shared with slider_widgets/physics_window)
        self.last_hovered_slider = None
        self.last_hovered_description = ""
        self.physics_window_interaction = False  # Track if we're interacting with sliders
        self.tooltip_start_time = time.time()  # Track time for animations

        # Simple vertex shader for full-screen quad
        vert_shader = """
        #version 150
        in vec2 in_vert;
        out vec2 texcoord;
        void main() {
            texcoord = in_vert * 0.5 + 0.5;
            gl_Position = vec4(in_vert, 0.0, 1.0);
        }
        """

        # Load fragment shader
        with open('shaders/tooltip_graphic.frag', 'r') as f:
            frag_shader = f.read()

        # Create shader program
        self.tooltip_program = self.ctx.program(
            vertex_shader=vert_shader,
            fragment_shader=frag_shader
        )

        # Create full-screen quad
        vertices = np.array([
            -1.0, -1.0,
             1.0, -1.0,
             1.0,  1.0,
            -1.0,  1.0,
        ], dtype='f4')

        vbo = self.ctx.buffer(vertices.tobytes())
        self.tooltip_vao = self.ctx.vertex_array(
            self.tooltip_program,
            [(vbo, '2f', 'in_vert')]
        )

        # Create framebuffer and texture for rendering
        self.tooltip_texture = self.ctx.texture(
            size=(self.tooltip_texture_size, self.tooltip_texture_size),
            components=4
        )
        self.tooltip_fbo = self.ctx.framebuffer(color_attachments=[self.tooltip_texture])
        self.tooltip_texture_id = imgui.ImTextureRef(self.tooltip_texture.glo)

    def update_tooltip_texture(self):
        """Render the tooltip graphic to texture using shader."""
        # Set time uniform for animations
        current_time = time.time() - self.tooltip_start_time
        self.tooltip_program['time'] = current_time * 3.0  # Speed up animation a bit

        # Set sensor angle (raw value, not normalized)
        self.tooltip_program['SENSOR_ANGLE'] = self.state.sim.SENSOR_ANGLE

        # Set MODE bools based on which slider is hovered
        self.tooltip_program['AXIAL_MODE'] = (self.last_hovered_slider == "Axial Force")
        self.tooltip_program['LATERAL_MODE'] = (self.last_hovered_slider == "Lateral Force")
        self.tooltip_program['SENSOR_MODE'] = (self.last_hovered_slider == "Sensor Gain")
        self.tooltip_program['DRAG_MODE'] = (self.last_hovered_slider == "Drag")
        self.tooltip_program['ANGLE_MODE'] = (self.last_hovered_slider == "Sensor Angle")
        self.tooltip_program['DISTANCE_MODE'] = (self.last_hovered_slider == "Sensor Distance")
        self.tooltip_program['TRAIL_MODE'] = (self.last_hovered_slider == "Trail Persistence")
        self.tooltip_program['DIFFUSION_MODE'] = (self.last_hovered_slider == "Trail Diffusion")
        self.tooltip_program['GLOBAL_MODE'] = (self.last_hovered_slider == "Global Force Mult")
        self.tooltip_program['STRAFE_MODE'] = (self.last_hovered_slider == "Strafe Power")
        self.tooltip_program['MUTATION_MODE'] = (self.last_hovered_slider == "Mutation Scale")

        # Render to framebuffer
        self.tooltip_fbo.use()
        self.ctx.clear(0.0, 0.0, 0.0, 1.0)
        self.tooltip_vao.render(mode=moderngl.TRIANGLE_FAN, vertices=4)
        self.ctx.screen.use()  # Return to default framebuffer

    def render_custom_tooltip(self, label: str, description: str):
        """Render a custom tooltip anchored to the right edge of a window.

        Args:
            label: The label of the slider
            description: Description text to display in the tooltip
        """
        # Track which slider is currently hovered
        if imgui.is_item_hovered():
            self.last_hovered_slider = label
            self.last_hovered_description = description

        # Track if any item is being actively manipulated (dragged)
        if imgui.is_item_active():
            self.physics_window_interaction = True

    def render_physics_tooltip(self):
        """Render the tooltip if mouse is over the Physics Settings window."""
        # Early exit if tooltips are disabled
        if not self.state.preferences.ui_windows.physics_tooltips_enabled:
            self.last_hovered_slider = None
            self.physics_window_interaction = False
            return

        # Check if physics settings window is hovered or if we're actively interacting with it
        physics_window_hovered = imgui.is_window_hovered()

        # First, check if we should show the tooltip at all
        # We need to render it at least once to check if IT is hovered
        should_show = (physics_window_hovered or
                      self.physics_window_interaction or
                      self.last_hovered_slider is not None)

        if not should_show:
            self.last_hovered_slider = None
            self.physics_window_interaction = False
            return

        if self.last_hovered_slider is None:
            self.physics_window_interaction = False
            return

        # Update the tooltip texture with current slider values
        self.update_tooltip_texture()

        # Get the position and size of the anchor window
        window_pos = imgui.get_window_pos()
        window_size = imgui.get_window_size()

        # Calculate tooltip position (right edge of the anchor window)
        tooltip_x = window_pos.x + window_size.x
        tooltip_y = window_pos.y

        # Set next window position
        imgui.set_next_window_pos(imgui.ImVec2(tooltip_x, tooltip_y))

        # Begin a borderless, no-move, no-focus tooltip window
        # Note: no_focus_on_appearing allows clicking to gain focus, just not automatic focus
        imgui.begin(
            "##SliderTooltip",
            flags=(
                imgui.WindowFlags_.no_title_bar |
                imgui.WindowFlags_.no_move |
                imgui.WindowFlags_.no_resize |
                imgui.WindowFlags_.always_auto_resize |
                imgui.WindowFlags_.no_focus_on_appearing |
                imgui.WindowFlags_.no_nav
            )
        )

        # Display the shader-rendered tooltip graphic
        imgui.image(
            self.tooltip_texture_id,
            imgui.ImVec2(self.tooltip_texture_size, self.tooltip_texture_size)
        )

        # Display slider name and description
        imgui.separator()
        imgui.text(f"Parameter: {self.last_hovered_slider}")
        imgui.separator()
        imgui.text_wrapped(self.last_hovered_description)

        # Check if tooltip itself is hovered (must be after content is rendered)
        tooltip_hovered = imgui.is_window_hovered()

        imgui.end()

        # Now decide if we should keep the tooltip visible next frame
        # Keep it if: physics window hovered, tooltip hovered, or actively dragging
        if not physics_window_hovered and not tooltip_hovered and not self.physics_window_interaction:
            self.last_hovered_slider = None

        # Reset interaction flag for next frame
        self.physics_window_interaction = False
