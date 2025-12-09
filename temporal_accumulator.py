import moderngl
import numpy as np

def create_temporal_accumulation_shader(ctx, motion_blur_samples):
    """Create a shader program for temporal accumulation (no spatial supersampling)."""

    vertex_shader = """
    #version 330 core
    in vec2 position;
    out vec2 uv;

    void main() {
        uv = position * 0.5 + 0.5;  // Convert from [-1,1] to [0,1]
        gl_Position = vec4(position, 0.0, 1.0);
    }
    """

    fragment_shader = f"""
    #version 330 core
    uniform sampler2D input_frame;
    uniform sampler2D accumulation_buffer;
    uniform bool is_first_frame;

    in vec2 uv;
    out vec4 fragColor;

    void main() {{
        // Sample the input frame
        vec3 current_color = texture(input_frame, uv).rgb;

        // Divide by number of samples (for averaging)
        current_color /= {motion_blur_samples}.0;

        // Add to or replace accumulation
        if (is_first_frame) {{
            fragColor = vec4(current_color, 1.0);
        }} else {{
            vec3 previous_accumulation = texture(accumulation_buffer, uv).rgb;
            fragColor = vec4(previous_accumulation + current_color, 1.0);
        }}
    }}
    """

    return ctx.program(vertex_shader=vertex_shader, fragment_shader=fragment_shader)


def setup_temporal_accumulation(ctx, width, height, motion_blur_samples):
    """Set up GPU-based temporal accumulation system."""

    # Create accumulation texture and framebuffer
    accumulation_texture = ctx.texture((width, height), 4, dtype='f4')
    accumulation_texture.filter = (moderngl.NEAREST, moderngl.NEAREST)

    accumulation_fbo = ctx.framebuffer(color_attachments=[accumulation_texture])

    # Create shader program
    shader = create_temporal_accumulation_shader(ctx, motion_blur_samples)

    # Create a fullscreen quad
    vertices = np.array([
        -1.0, -1.0,
         1.0, -1.0,
         1.0,  1.0,
        -1.0,  1.0,
    ], dtype=np.float32)

    indices = np.array([0, 1, 2, 0, 2, 3], dtype=np.uint32)

    vbo = ctx.buffer(vertices.tobytes())
    ibo = ctx.buffer(indices.tobytes())
    vao = ctx.vertex_array(shader, [(vbo, '2f', 'position')], ibo)

    return {
        'accumulation_fbo': accumulation_fbo,
        'accumulation_texture': accumulation_texture,
        'shader': shader,
        'vao': vao,
        'motion_blur_samples': motion_blur_samples,
        'frame_count': 0,
        'width': width,
        'height': height
    }


class TemporalAccumulator:
    """GPU-based temporal accumulation for motion blur in the main view."""

    def __init__(self, ctx, texture):
        """
        Initialize temporal accumulator.

        Args:
            ctx: moderngl.Context
            texture: The texture to accumulate (determines size)
        """
        self.ctx = ctx
        self.width, self.height = texture.size
        self.resources = None
        self.current_samples = 1

    def accumulate_frame(self, input_texture, motion_blur_samples):
        """
        Accumulate a frame into the temporal buffer.

        Args:
            input_texture: moderngl.Texture to accumulate
            motion_blur_samples: Number of frames to accumulate before outputting

        Returns:
            The accumulated texture if ready, None if still accumulating
        """
        # Check if we need to recreate resources
        input_width, input_height = input_texture.size
        recreate_resources = (
            self.resources is None or
            self.resources['motion_blur_samples'] != motion_blur_samples or
            self.resources['width'] != input_width or
            self.resources['height'] != input_height
        )

        if recreate_resources:
            # Clean up old resources if they exist
            if self.resources is not None:
                self.cleanup_resources()

            # Create new resources
            self.resources = setup_temporal_accumulation(
                self.ctx, input_width, input_height, motion_blur_samples
            )
            self.width = input_width
            self.height = input_height

        # Determine if this is the first frame of a new accumulation cycle
        is_first_frame = (self.resources['frame_count'] % motion_blur_samples) == 0
        self.resources['frame_count'] += 1

        # Bind textures
        input_texture.use(location=0)  # input_frame
        self.resources['accumulation_texture'].use(location=1)  # accumulation_buffer

        # Set uniforms
        self.resources['shader']['input_frame'] = 0
        self.resources['shader']['accumulation_buffer'] = 1
        self.resources['shader']['is_first_frame'] = is_first_frame

        # Render to accumulation buffer
        self.resources['accumulation_fbo'].use()
        if is_first_frame:
            self.resources['accumulation_fbo'].clear()
        self.resources['vao'].render()

        # Check if we should return the accumulated result
        if self.resources['frame_count'] % motion_blur_samples == 0:
            return self.resources['accumulation_texture']

        return None

    def get_accumulated_texture(self):
        """Get the current accumulated texture (even if not fully accumulated)."""
        if self.resources is None:
            return None
        return self.resources['accumulation_texture']

    def reset(self):
        """Clear the accumulation buffer and reset frame count."""
        if self.resources is not None:
            self.resources['frame_count'] = 0
            self.resources['accumulation_fbo'].clear()

    def cleanup_resources(self):
        """Clean up GPU resources."""
        if self.resources is not None:
            self.resources['accumulation_fbo'].release()
            self.resources['accumulation_texture'].release()
            self.resources['shader'].release()
            self.resources['vao'].release()
            self.resources = None

    def cleanup(self):
        """Clean up GPU resources when completely done."""
        self.cleanup_resources()
