struct Params {
    width: u32,
    height: u32,
    frame: u32,
    trial_count: u32,
    cursor_x: f32,
    cursor_y: f32,
    applying: u32,
    paused: u32,
    objective_zone_count: u32,
    zone0_x: f32,
    zone0_y: f32,
    zone0_radius: f32,
    zone1_x: f32,
    zone1_y: f32,
    zone1_radius: f32,
    _zone1_pad: f32,
    zone2_x: f32,
    zone2_y: f32,
    zone2_radius: f32,
    _zone2_pad: f32,
    hazard_center_x: f32,
    hazard_width: f32,
    hazard_strength: f32,
    hazard_enabled: u32,
    rival_x: f32,
    rival_y: f32,
    rival_radius: f32,
    rival_enabled: u32,
    rule_seed: u32,
    boundary_conditions: u32,
    initial_conditions: u32,
    num_cohorts: u32,
    sensor_distance: f32,
    sensor_angle: f32,
    sensor_gain: f32,
    mutation_scale: f32,
    drag: f32,
    strafe_power: f32,
    axial_force: f32,
    lateral_force: f32,
    global_force_mult: f32,
    trail_persistence: f32,
    trail_diffusion: f32,
    hazard_rate: f32,
    orientation_mix: f32,
    absolute_orientation: u32,
    disable_symmetry: u32,
    hue_sensitivity: f32,
    color_by_cohort: u32,
    watercolor_mode: u32,
    emboss_mode: u32,
    ink_weight: f32,
    emboss_intensity: f32,
    emboss_smoothness: f32,
    _appearance_pad0: f32,
    progress: f32,
    active_zone_mask: u32,
    run_status: u32,
    _runtime_pad0: u32,
};

struct VertexOut {
    @builtin(position) position: vec4<f32>,
    @location(0) uv: vec2<f32>,
};

@group(0) @binding(0)
var<storage, read> pixels: array<atomic<u32>>;

@group(0) @binding(1)
var<uniform> params: Params;

fn unpack_rgba8(pixel: u32) -> vec4<f32> {
    let r = f32((pixel >> 0u) & 0xffu) / 255.0;
    let g = f32((pixel >> 8u) & 0xffu) / 255.0;
    let b = f32((pixel >> 16u) & 0xffu) / 255.0;
    let a = f32((pixel >> 24u) & 0xffu) / 255.0;
    return vec4<f32>(r, g, b, a);
}

fn pixel_color(x: u32, y: u32) -> vec3<f32> {
    let index = y * params.width + x;
    return unpack_rgba8(atomicLoad(&pixels[index])).rgb;
}

fn luma(color: vec3<f32>) -> f32 {
    return dot(color, vec3<f32>(0.2126, 0.7152, 0.0722));
}

fn apply_watercolor(color: vec3<f32>) -> vec3<f32> {
    if (params.watercolor_mode == 0u) {
        return color;
    }
    let density = max(vec3<f32>(0.0), color) * max(params.ink_weight, 0.0);
    return vec3<f32>(1.0) - exp(-density);
}

fn emboss_multiplier(x: u32, y: u32) -> f32 {
    if (params.emboss_mode == 0u || params.emboss_intensity <= 0.0) {
        return 1.0;
    }
    let radius = max(1u, u32(round(clamp(params.emboss_smoothness * 12.0, 1.0, 16.0))));
    let left_x = select(x - radius, 0u, x < radius);
    let right_x = min(x + radius, params.width - 1u);
    let up_y = select(y - radius, 0u, y < radius);
    let down_y = min(y + radius, params.height - 1u);
    let dx = luma(pixel_color(right_x, y)) - luma(pixel_color(left_x, y));
    let dy = luma(pixel_color(x, down_y)) - luma(pixel_color(x, up_y));
    let light = normalize(vec3<f32>(-0.55, -0.65, 0.75));
    let normal = normalize(vec3<f32>(-dx, -dy, 0.12));
    let shade = dot(normal, light) * 0.5 + 0.5;
    return mix(1.0, 0.72 + shade * 0.56, clamp(params.emboss_intensity, 0.0, 1.0));
}

@vertex
fn vs_main(@builtin(vertex_index) vertex_index: u32) -> VertexOut {
    var positions = array<vec2<f32>, 3>(
        vec2<f32>(-1.0, -3.0),
        vec2<f32>(-1.0, 1.0),
        vec2<f32>(3.0, 1.0),
    );
    var out: VertexOut;
    out.position = vec4<f32>(positions[vertex_index], 0.0, 1.0);
    out.uv = out.position.xy * vec2<f32>(0.5, -0.5) + vec2<f32>(0.5, 0.5);
    return out;
}

@fragment
fn fs_main(in: VertexOut) -> @location(0) vec4<f32> {
    let x = min(u32(clamp(in.uv.x, 0.0, 0.999999) * f32(params.width)), params.width - 1u);
    let y = min(u32(clamp(in.uv.y, 0.0, 0.999999) * f32(params.height)), params.height - 1u);
    let index = y * params.width + x;
    let source = unpack_rgba8(atomicLoad(&pixels[index]));
    let watercolor = apply_watercolor(source.rgb);
    let embossed = watercolor * emboss_multiplier(x, y);
    return vec4<f32>(clamp(embossed, vec3<f32>(0.0), vec3<f32>(1.0)), source.a);
}
