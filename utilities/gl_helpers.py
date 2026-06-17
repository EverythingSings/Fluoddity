import math
import numpy as np
import moderngl
from PIL import Image
def create_grid_coords(N):
    W = math.ceil(math.sqrt(N))
    # Create indices 0, 1, 2, ..., N-1
    indices = np.arange(N)
    # Convert to x, y coordinates using row-major ordering
    y,x = indices % W,indices // W
    # Stack into N x 2 array
    return np.column_stack([x, y])/W

def read_shader(path:str):
    result=""
    with open(path, 'r') as file:
        
        result= file.read()
    return result
def prepend_defines(shader_source, defines):
    """Inject #define directives after the #version line.

    Args:
        shader_source: GLSL source string (must start with #version).
        defines: dict of {NAME: value} to inject as ``#define NAME value``.
    """
    content_to_insert = "".join(f"#define {name} {value}\n" for name, value in defines.items())
    return shader_prepend(shader_source, content_to_insert)
def shader_prepend(shader_source, content_to_insert):
    first_newline = shader_source.find('\n')
    return shader_source[:first_newline+1] + content_to_insert + shader_source[first_newline+1:]

MUTED_TRYSET_WARNINGS={}
def tryset(program:moderngl.Program,uniform,value):
    """
    Gracefully handle a uniform that doesn't appear in program.
    Uniforms are frequently optimized out if they are not used in the current version of the shader.
    """
    if uniform in program:
        program[uniform]=value
    else:
        global MUTED_TRYSET_WARNINGS
        if uniform not in MUTED_TRYSET_WARNINGS:
            MUTED_TRYSET_WARNINGS[uniform]=0
        MUTED_TRYSET_WARNINGS[uniform]+=1
        if MUTED_TRYSET_WARNINGS[uniform]<10:
            print('Warning: ',uniform,' not present in ',program)

def tryset_mat3(program: moderngl.Program, uniform, mat):
    """Upload a 3x3 matrix uniform (column-major float32).

    Gracefully handles optimized-away uniforms like tryset.
    """
    if uniform in program:
        program[uniform].write(mat.astype("f4").T.tobytes())
    else:
        global MUTED_TRYSET_WARNINGS
        if uniform not in MUTED_TRYSET_WARNINGS:
            MUTED_TRYSET_WARNINGS[uniform] = 0
        MUTED_TRYSET_WARNINGS[uniform] += 1
        if MUTED_TRYSET_WARNINGS[uniform] < 10:
            print('Warning: ', uniform, ' not present in ', program)

def tryset_mat4(program: moderngl.Program, uniform, mat):
    """Upload a 4x4 matrix uniform (column-major float32).

    Gracefully handles optimized-away uniforms like tryset.
    """
    if uniform in program:
        program[uniform].write(mat.astype("f4").T.tobytes())
    else:
        global MUTED_TRYSET_WARNINGS
        if uniform not in MUTED_TRYSET_WARNINGS:
            MUTED_TRYSET_WARNINGS[uniform] = 0
        MUTED_TRYSET_WARNINGS[uniform] += 1
        if MUTED_TRYSET_WARNINGS[uniform] < 10:
            print('Warning: ', uniform, ' not present in ', program)

def readback_rule(rule_buffer, rule_index):
    """
    Read back a single Rule from the buffer at the specified index.

    Structure:
    - FourierCenter: vec4 freq + vec4 amp + vec2 freq_ext + vec2 amp_ext = 12 floats = 48 bytes
    - Rule: 10 FourierCenters = 10 * 48 = 480 bytes
    """

    # Calculate the byte offset for the specific rule
    rule_size_bytes = 480  # 10 centers * 48 bytes per center
    offset = rule_index * rule_size_bytes

    # Read the specific rule from the buffer
    rule_bytes = rule_buffer.read(size=rule_size_bytes, offset=offset)

    # Convert bytes to numpy array
    # Each Rule contains 120 floats (10 centers * 12 floats per center)
    rule_data = np.frombuffer(rule_bytes, dtype=np.float32)

    # Reshape to [10 centers, 12 floats per center]
    rule_reshaped = rule_data.reshape(10, 12)

    return rule_reshaped
def set_rule_uniform(program, rule_data):
    """
    Set a Rule as a uniform in the shader program.

    Args:
        rule_data: numpy array of shape (10, 12) containing the rule data
    """

    for i in range(10):
        center_data = rule_data[i]
        frequency = center_data[:4]        # First 4 floats: frequency vec4
        amplitude = center_data[4:8]       # Next 4 floats: amplitude vec4
        frequency_ext = center_data[8:10]  # Next 2 floats: frequency_ext vec2
        amplitude_ext = center_data[10:12] # Last 2 floats: amplitude_ext vec2

        try:
            program[f'target_rule.centers[{i}].frequency'] = tuple(frequency)
            program[f'target_rule.centers[{i}].amplitude'] = tuple(amplitude)
            program[f'target_rule.centers[{i}].frequency_ext'] = tuple(frequency_ext)
            program[f'target_rule.centers[{i}].amplitude_ext'] = tuple(amplitude_ext)
        except Exception:
            print('failed rule uniforms')

def load_image_as_texture(ctx, image_path):
    """
    Load an arbitrary image file and convert it to a ModernGL RGBA texture.
    
    Args:
        ctx: ModernGL context
        image_path: Path to the image file (JPEG, PNG, etc.)
    
    Returns:
        moderngl.Texture: RGBA texture object
    """
    # Load and convert image to RGBA
    img = Image.open(image_path)
    img = img.convert('RGBA')  # Ensure RGBA format
    
    # Get image dimensions
    width, height = img.size
    
    # Get raw pixel data as bytes
    # PIL uses top-left origin, ModernGL uses bottom-left, so flip vertically
    img = img.transpose(Image.FLIP_TOP_BOTTOM)
    pixel_data = img.tobytes()
    
    # Create ModernGL texture
    texture = ctx.texture((width, height), 4, pixel_data)
    
    return texture