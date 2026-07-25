// networked.art/everything artifact: final brightness and asinh tone mapping.
//
// The render target is the configured canvas texture format. No blending is
// required. The accumulation texture is read-only and is swapped only by the
// accumulation pass.

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
@group(0) @binding(1) var accumulation_texture: texture_2d<f32>;
@group(0) @binding(2) var linear_sampler: sampler;

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

fn inverse_hyperbolic_sine(value: f32) -> f32 {
    return log(value + sqrt(value * value + 1.0));
}

@fragment
fn fs_main(input: FullscreenOutput) -> @location(0) vec4<f32> {
    var color =
        textureSample(accumulation_texture, linear_sampler, input.uv).rgb;
    color *= 3.0 * max(globals.appearance.z, 0.0);

    let color_length = length(color);
    let softness = max(globals.appearance.w, 0.000001);
    if (color_length > 0.0) {
        color *= inverse_hyperbolic_sine(color_length * softness)
            / (color_length * softness);
    }
    return vec4<f32>(color, 1.0);
}
