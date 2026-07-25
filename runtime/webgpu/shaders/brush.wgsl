// networked.art/everything artifact: pre-update particle trail deposition.
//
// Draw with:
//   topology: triangle-strip
//   vertexCount: 4
//   instanceCount: globals.sim.y (active particle count)
//   target: rgba16float, cleared to zero every simulation step
//   blend (color and alpha): src-factor=src-alpha, dst-factor=one, op=add
//
// The source-alpha blend is intentional. The canonical OpenGL shader emits a
// Gaussian-weighted RGBA value and then applies SRC_ALPHA, ONE blending, so
// RGB receives a second Gaussian weighting.

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
    @location(1) velocity: vec2<f32>,
    @location(2) particle_alpha: f32,
};

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
    let vertex_position = entity.pos + offsets[vertex_index] * entity.size;

    var output: VertexOutput;
    output.position = vec4<f32>(vertex_position / half_extent, 0.0, 1.0);
    output.uv = uvs[vertex_index];
    output.velocity = entity.vel;
    output.particle_alpha = entity.color.a;
    return output;
}

fn gaussian(position: vec2<f32>, sigma: f32) -> f32 {
    let sigma_squared = sigma * sigma;
    let normalization = 1.0 / (2.0 * 3.14159265359 * sigma_squared);
    let exponent = -dot(position, position) / (2.0 * sigma_squared);
    return normalization * exp(exponent);
}

@fragment
fn fs_main(input: VertexOutput) -> @location(0) vec4<f32> {
    if (globals.sim.x == 0u) {
        return vec4<f32>(0.0);
    }
    let centered_uv = input.uv - vec2<f32>(0.5);
    if (length(centered_uv) > 0.5 || input.particle_alpha == 0.0) {
        discard;
    }

    let kernel = gaussian(centered_uv, 0.163);
    return vec4<f32>(input.velocity, 0.01, 1.0) * kernel;
}
