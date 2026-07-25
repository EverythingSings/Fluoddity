// networked.art/everything artifact: temporal accumulation.
//
// The previous accumulation and destination must be different rgba16float
// textures. The buffer stays in linear, un-tonemapped space; present.wgsl
// performs display mapping. This removes the desktop shader's need to undo
// tonemapping before blending and makes ping-pong behavior deterministic.

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

@group(0) @binding(0) var<uniform> globals: Globals;
@group(0) @binding(1) var previous_accumulation: texture_2d<f32>;
@group(0) @binding(2) var current_particles: texture_2d<f32>;
@group(0) @binding(3) var linear_sampler: sampler;

struct FullscreenOutput {
    @builtin(position) position: vec4<f32>,
    @location(0) uv: vec2<f32>,
};

@vertex
fn vs_main(@builtin(vertex_index) vertex_index: u32) -> FullscreenOutput {
    let positions = array<vec2<f32>, 3>(
        vec2<f32>(-1.0, -1.0),
        vec2<f32>( 3.0, -1.0),
        vec2<f32>(-1.0,  3.0),
    );
    let position = positions[vertex_index];
    var output: FullscreenOutput;
    output.position = vec4<f32>(position, 0.0, 1.0);
    output.uv = vec2<f32>(
        position.x * 0.5 + 0.5,
        0.5 - position.y * 0.5,
    );
    return output;
}

@fragment
fn fs_main(input: FullscreenOutput) -> @location(0) vec4<f32> {
    var current_color =
        textureSample(current_particles, linear_sampler, input.uv).rgb;
    if (globals.flags.w != 0u) {
        current_color = exp(
            current_color * globals.render.x * 10.0,
        );
    }
    if (globals.sim.x == 0u) {
        return vec4<f32>(current_color, 1.0);
    }

    let previous_color =
        textureSample(previous_accumulation, linear_sampler, input.uv).rgb;
    let exposure = clamp(globals.interaction.w, 0.0, 0.9999);
    return vec4<f32>(
        mix(current_color, previous_color, exposure),
        1.0,
    );
}
