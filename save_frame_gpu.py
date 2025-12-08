import moderngl
import numpy as np
from PIL import Image
import os

def create_supersample_shader(ctx, supersample_k,motion_blur_samples):
    """Create a shader program for supersampling and temporal accumulation."""
    
    vertex_shader = """
    #version 330 core
    in vec2 position;
    out vec2 uv;
    
    void main() {
        uv = position * 0.5 + 0.5;  // Convert from [-1,1] to [0,1]
        //FLIP UD
        gl_Position = vec4(position, 0.0, 1.0);
    }
    """
    
    # Generate the fragment shader with unrolled loops for better compatibility
    sample_code = ""
    for y in range(supersample_k):
        for x in range(supersample_k):
            sample_code += f"""
        // Sample {x},{y}
        sub_pixel_offset = vec2({x}.5, {y}.5) / {supersample_k}.0;
        //sample_pos = (input_region_start + sub_pixel_offset * input_region_size) / input_size;
        frag_shape = 1./input_size;
        sample_pos=uv-.5*frag_shape+(vec2({x}.5, {y}.5) / {supersample_k}.0)*frag_shape;
        
            
        sampcol =texture(input_frame, sample_pos).rgb;
        //SYNC WITH cam_brush_pp.frag!!!!!!!!!!!!
        sampcol.xyz/=pow(.0001+length(sampcol.xyz),.575);
        total_color += sampcol;
"""
    
    fragment_shader = f"""
    #version 330 core
    uniform sampler2D input_frame;
    uniform sampler2D accumulation_buffer;
    uniform bool is_first_frame;
    
    in vec2 uv;
    out vec4 fragColor;
    
    void main() {{

        vec3 total_color = vec3(0.0);
        vec2 input_size = vec2(textureSize(input_frame, 0));
        vec2 output_size = vec2(textureSize(accumulation_buffer, 0));
        
        // Each output pixel corresponds to a {supersample_k}x{supersample_k} region in input
        vec2 input_region_size = input_size / output_size;
        vec2 input_region_start = uv * input_region_size;
        
        vec2 sub_pixel_offset, sample_pos,frag_shape;
        
        // Sample {supersample_k}^2 points within this region
        vec3 sampcol;
{sample_code}
        
        // Average the samples
        total_color /= {supersample_k * supersample_k}.0;
        //Average over temporal samples
        total_color /= {motion_blur_samples}.0;
        
        // Add to or replace accumulation
        if (is_first_frame) {{
            fragColor = vec4(total_color, 1.0);
        }} else {{
            vec3 previous_accumulation = texture(accumulation_buffer, uv).rgb;
            fragColor = vec4(previous_accumulation + total_color, 1.0);
        }}
        //DEBUG if(uv.x!=-69420)fragColor=vec4(total_color,1);//length(uv-.5)>99999?vec4(0):vec4(total_color,1);//texture(input_frame,vec2(uv)).xyz,1);
    }}
    """
    
    return ctx.program(vertex_shader=vertex_shader, fragment_shader=fragment_shader)


def setup_gpu_motion_blur(ctx, input_width, input_height, motion_blur_samples, supersample_k):
    """Set up GPU-based motion blur system."""
    
    # Calculate output dimensions
    output_width = input_width // supersample_k
    output_height = input_height // supersample_k
    
    # Create accumulation texture and framebuffer
    accumulation_texture = ctx.texture((output_width, output_height), 4, dtype='f4',)
    accumulation_texture.filter = (moderngl.NEAREST, moderngl.NEAREST)
    
    accumulation_fbo = ctx.framebuffer(color_attachments=[accumulation_texture])
    
    # Create shader program
    shader = create_supersample_shader(ctx, supersample_k,motion_blur_samples)
    
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
        'supersample_k': supersample_k,
        'frame_count': 0,
        'output_counter': 0,
        'output_width': output_width,
        'output_height': output_height,
        'input_width': input_width,
        'input_height': input_height
    }


def save_frame_gpu(frame_data, ctx, motion_blur_samples=1, supersample_k=1, return_array=False):
    """
    Save a moderngl texture using GPU-accelerated motion blur and supersampling.

    Args:
        frame_data: moderngl.Texture object to save
        ctx: moderngl.Context
        motion_blur_samples: Number of frames to collect and average (1 = no blur)
        supersample_k: Super sampling factor (1 = no super sampling)
        return_array: If True, return numpy array instead of saving to file

    Returns:
        If return_array=True: numpy array (height, width, 3) of uint8 RGB data, or None if frame accumulating
        If return_array=False: str filename of saved image, or None if frame was accumulated
    """
    
    # Get input dimensions
    input_width, input_height = frame_data.size
    
    # Initialize function attributes on first call or when settings change
    if not hasattr(save_frame_gpu, 'gpu_resources'):
        save_frame_gpu.gpu_resources = None
    
    # Check if we need to recreate resources
    recreate_resources = (
        save_frame_gpu.gpu_resources is None or
        save_frame_gpu.gpu_resources['motion_blur_samples'] != motion_blur_samples or
        save_frame_gpu.gpu_resources['supersample_k'] != supersample_k or
        save_frame_gpu.gpu_resources['input_width'] != input_width or
        save_frame_gpu.gpu_resources['input_height'] != input_height
    )
    
    if recreate_resources:
        # Clean up old resources if they exist
        if save_frame_gpu.gpu_resources is not None:
            old_resources = save_frame_gpu.gpu_resources
            old_resources['accumulation_fbo'].release()
            old_resources['accumulation_texture'].release()
            old_resources['shader'].release()
            old_resources['vao'].release()
        
        # Create new resources
        save_frame_gpu.gpu_resources = setup_gpu_motion_blur(
            ctx, input_width, input_height, motion_blur_samples, supersample_k
        )
    
    # Get resources
    gpu_resources = save_frame_gpu.gpu_resources
    accumulation_fbo = gpu_resources['accumulation_fbo']
    shader = gpu_resources['shader']
    vao = gpu_resources['vao']
    
    # Increment frame count
    is_first_frame = (gpu_resources['frame_count'] % motion_blur_samples) == 0
    gpu_resources['frame_count'] += 1
    
    # Bind textures
    frame_data.use(location=0)  # input_frame
    gpu_resources['accumulation_texture'].use(location=1)  # accumulation_buffer
    
    # Set uniforms
    shader['input_frame'] = 0
    shader['accumulation_buffer'] = 1
    shader['is_first_frame'] = is_first_frame
    
    
    #
    # Render to accumulation buffer
    accumulation_fbo.use()
    #ctx.enable(moderngl.BLEND)
    #ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE
    if is_first_frame:
        accumulation_fbo.clear()
    vao.render()
    #print(np.frombuffer(gpu_resources['accumulation_texture'].read()))
    # Check if we should output a frame
    if gpu_resources['frame_count'] % motion_blur_samples == 0:
        # Read back the accumulated result
        data = gpu_resources['accumulation_texture'].read()

        # Convert to numpy array
        width = gpu_resources['output_width']
        height = gpu_resources['output_height']
        pixels = np.frombuffer(data, dtype=np.float32)
        pixels = pixels.reshape((height, width, 4))

        # Average by number of accumulated frames and convert to uint8

        pixels = pixels[:, :, :3];# / motion_blur_samples  # Average and drop alpha
        pixels = np.clip(pixels * 255, 0, 255).astype(np.uint8)
        # Flip vertically (OpenGL convention)
        pixels = np.flipud(pixels)

        # Return array directly if requested
        if return_array:
            gpu_resources['output_counter'] += 1
            return pixels

        # Otherwise save as PNG (legacy behavior)
        # Create PIL image and save as PNG
        img = Image.fromarray(pixels, 'RGB')

        # Create frames directory if it doesn't exist
        if not os.path.exists('frames'):
            os.mkdir('frames')

        # Increment output counter and save
        gpu_resources['output_counter'] += 1
        filename = f"frames/frame_{gpu_resources['output_counter']:04d}.png"
        img.save(filename)

        return filename

    return None


def clear_gpu_frame_cache():
    """Clear the GPU accumulation buffer and reset frame count."""
    if hasattr(save_frame_gpu, 'gpu_resources') and save_frame_gpu.gpu_resources is not None:
        save_frame_gpu.gpu_resources['frame_count'] = 0
        save_frame_gpu.gpu_resources['accumulation_fbo'].clear()


def reset_gpu_frame_counter():
    """Reset the output frame counter."""
    if hasattr(save_frame_gpu, 'gpu_resources') and save_frame_gpu.gpu_resources is not None:
        save_frame_gpu.gpu_resources['output_counter'] = 0


def cleanup_gpu_motion_blur():
    """Clean up GPU resources. Call this when completely done with motion blur."""
    if hasattr(save_frame_gpu, 'gpu_resources') and save_frame_gpu.gpu_resources is not None:
        gpu_resources = save_frame_gpu.gpu_resources
        gpu_resources['accumulation_fbo'].release()
        gpu_resources['accumulation_texture'].release()
        gpu_resources['shader'].release()
        gpu_resources['vao'].release()
        save_frame_gpu.gpu_resources = None


# Example usage:
"""
import moderngl

# Setup your context
ctx = moderngl.create_context()

# That's it! Just call this in your render loop:
for i in range(25):
    # Your rendering code here
    texture = render_your_scene(ctx)  # Creates a 1000x1000 texture
    
    # Simple interface - handles everything automatically
    result = save_frame_gpu(texture, ctx, motion_blur_samples=5, supersample_k=2)
    if result:
        print(f"Saved: {result}")

# This outputs 5 GIF files at 500x500 resolution
# Each frame has motion blur from 5 input frames and 4x spatial supersampling

# Optional: Reset for new animation sequence
reset_gpu_frame_counter()
clear_gpu_frame_cache()

# Optional: Clean up when completely done (releases GPU memory)
cleanup_gpu_motion_blur()
"""