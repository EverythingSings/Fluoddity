// networked.art/everything artifact: current particle color render.
//
// Draw with:
//   topology: triangle-strip
//   vertexCount: 4
//   instanceCount: globals.sim.y
//   target: rgba16float, cleared to zero each frame
//   blend (color and alpha): src-factor=src-alpha, dst-factor=one, op=add

struct Entity {
    pos: vec2<f32>,
    vel: vec2<f32>,
    size: f32,
    cohort: f32,
    padding: vec2<f32>,
    color: vec4<f32>,
};

struct EntityBuffer {
    entities: array<Entity>,
};

struct Globals {
    canvas: vec4<f32>,
    pointer: vec4<f32>,
    interaction: vec4<f32>,
    appearance: vec4<f32>,
    render: vec4<f32>,
    sim: vec4<u32>,
    modes: vec4<u32>,
    flags: vec4<u32>,
    rule_params: vec4<f32>,
};

@group(0) @binding(0) var<storage, read> entity_buffer: EntityBuffer;
@group(0) @binding(1) var<uniform> globals: Globals;

struct VertexOutput {
    @builtin(position) position: vec4<f32>,
    @location(0) uv: vec2<f32>,
    @location(1) color: vec4<f32>,
};

fn safe_axis(value: vec2<f32>) -> vec2<f32> {
    let magnitude = length(value);
    if (magnitude == 0.0) {
        return vec2<f32>(1.0, 0.0);
    }
    return value / magnitude;
}

fn axis_to_world(value: vec2<f32>, input_axis: vec2<f32>) -> vec2<f32> {
    let axis = safe_axis(input_axis);
    return value.x * axis
        + value.y * axis.yx * vec2<f32>(1.0, -1.0);
}

@vertex
fn vs_main(
    @builtin(vertex_index) vertex_index: u32,
    @builtin(instance_index) instance_index: u32,
) -> VertexOutput {
    let entity = entity_buffer.entities[instance_index];
    let offsets = array<vec2<f32>, 4>(
        vec2<f32>(-1.0, -1.0),
        vec2<f32>( 1.0, -1.0),
        vec2<f32>( 1.0,  1.0),
        vec2<f32>(-1.0,  1.0),
    );
    let uvs = array<vec2<f32>, 4>(
        vec2<f32>(0.0, 0.0),
        vec2<f32>(1.0, 0.0),
        vec2<f32>(1.0, 1.0),
        vec2<f32>(0.0, 1.0),
    );
    let canvas_aspect = globals.canvas.x / max(globals.canvas.y, 1.0);
    let half_extent = vec2<f32>(sqrt(canvas_aspect), inverseSqrt(canvas_aspect));
    let particle_scale = max(globals.render.y, 0.0);
    let local_offset =
        offsets[vertex_index] * entity.size * 1.5 * particle_scale;
    let world_offset = axis_to_world(local_offset, entity.vel);
    let vertex_position = entity.pos + world_offset;

    var output: VertexOutput;
    output.position = vec4<f32>(vertex_position / half_extent, 0.0, 1.0);
    output.uv = uvs[vertex_index];
    output.color = entity.color;
    return output;
}

fn hsv_to_rgb(hsv: vec3<f32>) -> vec3<f32> {
    let k = vec4<f32>(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);
    let p = abs(fract(vec3<f32>(hsv.x) + k.xyz) * 6.0 - vec3<f32>(k.w));
    return hsv.z * mix(
        vec3<f32>(k.x),
        clamp(p - vec3<f32>(k.x), vec3<f32>(0.0), vec3<f32>(1.0)),
        hsv.y,
    );
}

fn gaussian(position: vec2<f32>, sigma: f32) -> f32 {
    let sigma_squared = sigma * sigma;
    let normalization = 1.0 / (2.0 * 3.14159265359 * sigma_squared);
    let exponent = -dot(position, position) / (2.0 * sigma_squared);
    return normalization * exp(exponent);
}

@fragment
fn fs_main(input: VertexOutput) -> @location(0) vec4<f32> {
    let centered_uv = input.uv - vec2<f32>(0.5);
    if (length(centered_uv) > 0.5 || input.color.a == 0.0) {
        discard;
    }
    let kernel = 0.5 * gaussian(centered_uv, 0.163);
    var output_color: vec3<f32>;
    if (globals.flags.w != 0u) {
        var particle_chroma = hsv_to_rgb(
            vec3<f32>(input.color.xy, 1.0),
        );
        particle_chroma = clamp(
            particle_chroma,
            vec3<f32>(0.001),
            vec3<f32>(0.9),
        );
        output_color = log(particle_chroma) * input.color.z;
    } else {
        output_color = hsv_to_rgb(input.color.xyz);
    }
    return vec4<f32>(output_color, input.color.a * kernel);
}
