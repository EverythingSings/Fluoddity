// networked.art/everything artifact: five-tap trail resolve and interactive drawing.
//
// The previous trail and destination must be different textures. Draw a
// fullscreen triangle into an rgba16float destination, then swap trail roles.
// Pointer coordinates use browser convention: (0,0) is the top-left.

struct PhysicsSetting {
    first: vec4<f32>,
    second: vec4<f32>,
};

struct SettingsBuffer {
    settings: array<PhysicsSetting, 12>,
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

@group(0) @binding(0) var<uniform> globals: Globals;
@group(0) @binding(1) var previous_trail: texture_2d<f32>;
@group(0) @binding(2) var brush_texture: texture_2d<f32>;
@group(0) @binding(3) var linear_sampler: sampler;
@group(0) @binding(4) var<storage, read> settings_buffer: SettingsBuffer;

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

fn canvas_setting_hash(position: vec2<f32>, frame: f32) -> f32 {
    return fract(
        sin(dot(
            position + vec2<f32>(frame * 0.01),
            vec2<f32>(12.9898, 78.233),
        )) * 43758.5453
    );
}

fn calculate_setting(
    setting_index: u32,
    entity_position: vec2<f32>,
    cohort: f32,
) -> f32 {
    let setting = settings_buffer.settings[setting_index];
    let slider_value = setting.first.x;
    let minimum = setting.first.y;
    let maximum = setting.first.z;
    let x_sweep = setting.first.w;
    let y_sweep = setting.second.x;
    let cohort_sweep = setting.second.y;
    let jitter = setting.second.z;

    if (
        x_sweep == 0.0
        && y_sweep == 0.0
        && cohort_sweep == 0.0
        && jitter == 0.0
    ) {
        return slider_value;
    }

    let sweep_position = (entity_position + vec2<f32>(1.0)) * 0.5;
    let sweep_cohort = cohort / max(f32(globals.sim.z), 1.0);
    var result = 0.0;
    var active_sweeps = 0u;

    if (x_sweep != 0.0) {
        result += select(
            mix(maximum, minimum, sweep_position.x),
            mix(minimum, maximum, sweep_position.x),
            x_sweep > 0.0,
        );
        active_sweeps += 1u;
    }
    if (y_sweep != 0.0) {
        result += select(
            mix(maximum, minimum, sweep_position.y),
            mix(minimum, maximum, sweep_position.y),
            y_sweep > 0.0,
        );
        active_sweeps += 1u;
    }
    if (cohort_sweep != 0.0) {
        result += select(
            mix(maximum, minimum, sweep_cohort),
            mix(minimum, maximum, sweep_cohort),
            cohort_sweep > 0.0,
        );
        active_sweeps += 1u;
    }

    if (active_sweeps > 0u) {
        result /= f32(active_sweeps);
    } else {
        result = slider_value;
    }

    if (jitter != 0.0) {
        let random_value =
            canvas_setting_hash(sweep_position, f32(globals.sim.x))
            * 2.0 - 1.0;
        result += jitter * result * random_value;
    }
    return result;
}

fn wrapped_sample(texture: texture_2d<f32>, uv: vec2<f32>) -> vec4<f32> {
    var sample_uv = uv;
    if (globals.sim.w == 2u) {
        sample_uv = fract(sample_uv);
    }
    return textureSample(texture, linear_sampler, sample_uv);
}

fn five_tap_blur(uv: vec2<f32>, diffusion_constant: f32) -> vec4<f32> {
    let dimensions = vec2<f32>(textureDimensions(previous_trail));
    let texel = vec2<f32>(1.0) / dimensions;
    let center = wrapped_sample(previous_trail, uv);
    let north = wrapped_sample(
        previous_trail,
        uv + vec2<f32>(0.0, -texel.y),
    );
    let south = wrapped_sample(
        previous_trail,
        uv + vec2<f32>(0.0, texel.y),
    );
    let west = wrapped_sample(
        previous_trail,
        uv + vec2<f32>(-texel.x, 0.0),
    );
    let east = wrapped_sample(
        previous_trail,
        uv + vec2<f32>(texel.x, 0.0),
    );
    return (
        center * diffusion_constant + north + south + west + east
    ) / (4.0 + diffusion_constant);
}

fn aspect_correct_uv(uv_delta: vec2<f32>) -> vec2<f32> {
    let canvas_aspect = globals.canvas.x / max(globals.canvas.y, 1.0);
    return uv_delta * vec2<f32>(
        sqrt(canvas_aspect),
        inverseSqrt(canvas_aspect),
    );
}

fn entity_axis_delta(uv_delta: vec2<f32>) -> vec2<f32> {
    return vec2<f32>(uv_delta.x, -uv_delta.y);
}

fn safe_normalize(value: vec2<f32>) -> vec2<f32> {
    let magnitude = length(value);
    if (magnitude == 0.0) {
        return vec2<f32>(0.0);
    }
    return value / magnitude;
}

fn draw_vector(uv: vec2<f32>) -> vec2<f32> {
    let pointer_velocity =
        entity_axis_delta(globals.pointer.xy - globals.pointer.zw);
    let mode = globals.flags.z;
    if (mode == 0u) {
        return pointer_velocity;
    }
    if (mode == 1u) {
        return -pointer_velocity;
    }
    if (mode == 2u) {
        return 0.01 * vec2<f32>(
            sin(globals.interaction.z),
            cos(globals.interaction.z),
        );
    }
    if (mode == 3u) {
        let toward_pointer = entity_axis_delta(globals.pointer.xy - uv);
        return 0.01 * safe_normalize(aspect_correct_uv(toward_pointer));
    }
    if (mode == 4u) {
        let away_from_pointer = entity_axis_delta(uv - globals.pointer.xy);
        return 0.01 * safe_normalize(aspect_correct_uv(away_from_pointer));
    }
    return vec2<f32>(0.0);
}

fn draw_kernel(distance: f32, size: f32) -> f32 {
    let sigma = max(size, 0.000001);
    return exp(-(distance * distance) / (2.0 * sigma * sigma));
}

@fragment
fn fs_main(input: FullscreenOutput) -> @location(0) vec4<f32> {
    if (globals.sim.x == 0u) {
        return vec4<f32>(0.0, 0.0, 0.0, 1.0);
    }

    let canvas_aspect = globals.canvas.x / max(globals.canvas.y, 1.0);
    let half_extent = vec2<f32>(
        sqrt(canvas_aspect),
        inverseSqrt(canvas_aspect),
    );
    let entity_position = vec2<f32>(
        (input.uv.x * 2.0 - 1.0) * half_extent.x,
        (1.0 - input.uv.y * 2.0) * half_extent.y,
    );

    var diffusion = clamp(
        calculate_setting(11u, entity_position, 0.0),
        0.001,
        1.0,
    );
    diffusion *= diffusion;
    let diffusion_constant = 4.0 / (pow(5.0, diffusion) - 1.0);
    let blurred_trail = five_tap_blur(input.uv, diffusion_constant);

    let persistence = clamp(
        calculate_setting(10u, entity_position, 0.0),
        0.0,
        0.999,
    );
    let particle_brush =
        textureSample(brush_texture, linear_sampler, input.uv);
    var result =
        blurred_trail * persistence + particle_brush * (1.0 - persistence);

    let draw_size = max(globals.interaction.x, 0.000001);
    if (
        globals.flags.x != 0u
        && globals.flags.y == 0u
        && globals.interaction.y > 0.0
    ) {
        let distance_to_pointer =
            length(aspect_correct_uv(input.uv - globals.pointer.xy));
        let vector =
            draw_vector(input.uv) * globals.interaction.y / 5.0;
        let kernel_weight = draw_kernel(distance_to_pointer, draw_size);
        let drawn_velocity = result.xy
            + vector * kernel_weight / draw_size * (1.0 - persistence);
        result = vec4<f32>(drawn_velocity, result.zw);
    }

    if (globals.flags.x != 0u && globals.flags.y != 0u) {
        let erase_distance =
            length(aspect_correct_uv(input.uv - globals.pointer.xy));
        if (erase_distance < draw_size * 2.0) {
            result = vec4<f32>(0.0, 0.0, 0.0, 1.0);
        }
    }
    return result;
}
