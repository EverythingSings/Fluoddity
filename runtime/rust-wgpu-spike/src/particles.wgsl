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

struct Particle {
    x: f32,
    y: f32,
    vx: f32,
    vy: f32,
    cohort: u32,
    rule_seed: u32,
    _pad0: u32,
    _pad1: u32,
};

struct NativeSetting {
    slider_value: f32,
    min_value: f32,
    max_value: f32,
    x_sweep: f32,
    y_sweep: f32,
    cohort_sweep: f32,
    jitter: f32,
    _pad0: f32,
};

const SETTING_AXIAL_FORCE: u32 = 0u;
const SETTING_LATERAL_FORCE: u32 = 1u;
const SETTING_SENSOR_GAIN: u32 = 2u;
const SETTING_MUTATION_SCALE: u32 = 3u;
const SETTING_DRAG: u32 = 4u;
const SETTING_STRAFE_POWER: u32 = 5u;
const SETTING_SENSOR_ANGLE: u32 = 6u;
const SETTING_GLOBAL_FORCE_MULT: u32 = 7u;
const SETTING_SENSOR_DISTANCE: u32 = 8u;
const SETTING_TRAIL_PERSISTENCE: u32 = 9u;
const SETTING_TRAIL_DIFFUSION: u32 = 10u;
const SETTING_HAZARD_RATE: u32 = 11u;

@group(0) @binding(0)
var<storage, read_write> pixels: array<atomic<u32>>;

@group(0) @binding(1)
var<uniform> params: Params;

@group(0) @binding(2)
var<storage, read_write> particles: array<Particle>;

@group(0) @binding(3)
var<storage, read> trail_source: array<u32>;

@group(0) @binding(4)
var<storage, read> rule_coefficients: array<f32>;

@group(0) @binding(6)
var<storage, read> physics_settings: array<NativeSetting>;

@group(0) @binding(7)
var<storage, read_write> trail_target: array<atomic<u32>>;

fn pack_rgba8(r: u32, g: u32, b: u32, a: u32) -> u32 {
    return (a << 24u) | (b << 16u) | (g << 8u) | r;
}

fn attraction(pos: vec2<f32>, center: vec2<f32>, radius: f32, enabled: bool) -> vec2<f32> {
    let to_center = center - pos;
    let dist = max(length(to_center), 0.0001);
    let influence = select(0.0, smoothstep(radius * 3.0, radius * 0.35, dist), enabled);
    return normalize(to_center) * influence;
}

fn trail_at(pos: vec2<f32>) -> f32 {
    let sample_pos = clamp(pos, vec2<f32>(0.0, 0.0), vec2<f32>(0.9999, 0.9999));
    let px = min(u32(sample_pos.x * f32(params.width)), params.width - 1u);
    let py = min(u32(sample_pos.y * f32(params.height)), params.height - 1u);
    let index = py * params.width + px;
    return min(f32(trail_source[index]) / 65535.0, 1.0);
}

fn rotate(v: vec2<f32>, angle: f32) -> vec2<f32> {
    let c = cos(angle);
    let s = sin(angle);
    return vec2<f32>(v.x * c - v.y * s, v.x * s + v.y * c);
}

fn safe_norm(v: vec2<f32>) -> vec2<f32> {
    if (length(v) < 0.00001) {
        return vec2<f32>(0.0, -1.0);
    }
    return normalize(v);
}

fn y_reflect(v: vec2<f32>) -> vec2<f32> {
    return vec2<f32>(v.x, -v.y);
}

fn hsv_to_rgb(h: f32, s: f32, v: f32) -> vec3<f32> {
    let k = vec3<f32>(fract(h + 1.0), fract(h + 2.0 / 3.0), fract(h + 1.0 / 3.0));
    let p = abs(k * 6.0 - vec3<f32>(3.0));
    return v * mix(vec3<f32>(1.0), clamp(p - vec3<f32>(1.0), vec3<f32>(0.0), vec3<f32>(1.0)), s);
}

fn sensor_orientation(pos: vec2<f32>, velocity: vec2<f32>) -> vec2<f32> {
    var orientation = safe_norm(velocity);
    let mix_amt = select(0.0, params.orientation_mix, params.absolute_orientation > 0u);
    if (params.absolute_orientation == 1u) {
        orientation = safe_norm(mix(orientation, vec2<f32>(0.0, 1.0), mix_amt));
    } else if (params.absolute_orientation == 2u) {
        orientation = safe_norm(mix(orientation, -safe_norm(pos - vec2<f32>(0.5, 0.5)), mix_amt));
    }
    return orientation;
}

fn pcg_hash(seed: u32) -> u32 {
    let state = seed * 747796405u + 2891336453u;
    let word = ((state >> ((state >> 28u) + 4u)) ^ state) * 277803737u;
    return (word >> 22u) ^ word;
}

fn hash01(seed: u32, salt: u32) -> f32 {
    return f32(pcg_hash(seed ^ pcg_hash(salt))) / f32(0xffffffffu);
}

fn signed_hash(seed: u32, salt: u32) -> f32 {
    return hash01(seed, salt) * 2.0 - 1.0;
}

fn sweep_mix(setting: NativeSetting, mode: f32, t: f32) -> f32 {
    return select(
        mix(setting.max_value, setting.min_value, clamp(t, 0.0, 1.0)),
        mix(setting.min_value, setting.max_value, clamp(t, 0.0, 1.0)),
        mode > 0.0,
    );
}

fn setting_value(setting_index: u32, pos: vec2<f32>, cohort: u32, frame: u32) -> f32 {
    let setting = physics_settings[setting_index];
    if (setting.x_sweep == 0.0 && setting.y_sweep == 0.0 && setting.cohort_sweep == 0.0 && setting.jitter == 0.0) {
        return setting.slider_value;
    }
    var result = 0.0;
    var active_count = 0.0;
    if (setting.x_sweep != 0.0) {
        result = result + sweep_mix(setting, setting.x_sweep, pos.x);
        active_count = active_count + 1.0;
    }
    if (setting.y_sweep != 0.0) {
        result = result + sweep_mix(setting, setting.y_sweep, pos.y);
        active_count = active_count + 1.0;
    }
    if (setting.cohort_sweep != 0.0) {
        let cohort_t = f32(cohort) / f32(max(params.num_cohorts, 1u));
        result = result + sweep_mix(setting, setting.cohort_sweep, cohort_t);
        active_count = active_count + 1.0;
    }
    if (active_count == 0.0) {
        result = setting.slider_value;
    } else {
        result = result / active_count;
    }
    if (setting.jitter != 0.0) {
        let salt = u32(abs(result) * 100000.0) ^ (setting_index * 4099u);
        result = result + setting.jitter * result * signed_hash(frame, salt);
    }
    return result;
}

fn reset_position(index: u32, frame: u32) -> vec2<f32> {
    let seed = index ^ (frame * 747796405u) ^ params.rule_seed;
    if (params.initial_conditions == 2u) {
        let angle = hash01(seed, 601u) * 6.2831853;
        let radius = 0.23 + hash01(seed, 607u) * 0.08;
        return vec2<f32>(0.5 + cos(angle) * radius, 0.5 + sin(angle) * radius);
    }
    if (params.initial_conditions == 1u) {
        return vec2<f32>(0.08 + hash01(seed, 613u) * 0.84, 0.08 + hash01(seed, 617u) * 0.84);
    }
    let columns = 128u;
    let col = index % columns;
    let row = index / columns;
    return vec2<f32>(
        0.24 + (f32(col) / f32(columns - 1u)) * 0.52 + signed_hash(seed, 619u) * 0.003,
        0.24 + (f32(row) / 63.0) * 0.52 + signed_hash(seed, 631u) * 0.003,
    );
}

fn rule_frequency(seed: u32, center: u32) -> vec4<f32> {
    let scale = 0.75 + 2.25 * hash01(seed, center * 17u + 3u);
    return vec4<f32>(
        signed_hash(seed, center * 17u + 4u),
        signed_hash(seed, center * 17u + 5u),
        signed_hash(seed, center * 17u + 6u),
        signed_hash(seed, center * 17u + 7u),
    ) * scale;
}

fn rule_amplitude(seed: u32, center: u32) -> vec4<f32> {
    return vec4<f32>(
        signed_hash(seed, center * 17u + 8u),
        signed_hash(seed, center * 17u + 9u),
        signed_hash(seed, center * 17u + 10u),
        signed_hash(seed, center * 17u + 11u),
    );
}

fn saved_rule_frequency(center: u32) -> vec4<f32> {
    let offset = center * 8u;
    return vec4<f32>(
        rule_coefficients[offset + 0u],
        rule_coefficients[offset + 1u],
        rule_coefficients[offset + 2u],
        rule_coefficients[offset + 3u],
    );
}

fn saved_rule_amplitude(center: u32) -> vec4<f32> {
    let offset = center * 8u;
    return vec4<f32>(
        rule_coefficients[offset + 4u],
        rule_coefficients[offset + 5u],
        rule_coefficients[offset + 6u],
        rule_coefficients[offset + 7u],
    );
}

fn has_saved_rule() -> bool {
    return any(saved_rule_frequency(0u) != vec4<f32>(0.0)) || any(saved_rule_amplitude(5u) != vec4<f32>(0.0));
}

fn saved_fourier_rule(input: vec4<f32>) -> vec4<f32> {
    var result = vec4<f32>(0.0);
    for (var center = 0u; center < 10u; center = center + 1u) {
        let freq = saved_rule_frequency(center);
        let amp = saved_rule_amplitude(center);
        let phase = dot(input, freq);
        let phase_offset = 2.0 * f32(center) * 0.6283 + amp.w * 3.14159;
        let basis = vec4<f32>(
            sin(phase + phase_offset),
            cos(phase + phase_offset * 0.7),
            sin(phase * 2.0 + phase_offset * 1.3),
            cos(phase * 2.0 + phase_offset * 0.5),
        );
        result = result + amp * basis;
    }
    return result / 10.0;
}

fn fourier_rule(input: vec4<f32>, seed: u32) -> vec4<f32> {
    var result = vec4<f32>(0.0);
    for (var center = 0u; center < 6u; center = center + 1u) {
        let freq = rule_frequency(seed, center);
        let amp = rule_amplitude(seed, center);
        let phase_offset = f32(center) * 0.6283 + amp.w * 3.14159;
        let phase = dot(input, freq) + phase_offset;
        let basis = vec4<f32>(
            sin(phase),
            cos(phase + phase_offset * 0.7),
            sin(phase * 2.0 + phase_offset * 1.3),
            cos(phase * 2.0 + phase_offset * 0.5),
        );
        result = result + amp * basis;
    }
    return result / 6.0;
}

fn native_rule(input: vec4<f32>, seed: u32) -> vec4<f32> {
    let generated_rule = fourier_rule(input, seed);
    let saved_rule = saved_fourier_rule(input);
    return select(generated_rule, saved_rule, has_saved_rule());
}

@compute @workgroup_size(64, 1, 1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let index = gid.x;
    if (index >= arrayLength(&particles)) {
        return;
    }

    var p = particles[index];
    let pos = vec2<f32>(p.x, p.y);
    let cohort_count = max(params.num_cohorts, 1u);
    let cohort = p.cohort % cohort_count;
    let hazard_rate = setting_value(SETTING_HAZARD_RATE, pos, cohort, params.frame);
    if (hazard_rate > hash01(index ^ params.frame, 701u)) {
        let reset_pos = reset_position(index, params.frame);
        let reset_angle = hash01(index ^ params.frame, 709u) * 6.2831853;
        p.x = reset_pos.x;
        p.y = reset_pos.y;
        p.vx = cos(reset_angle) * 0.0015;
        p.vy = sin(reset_angle) * 0.0015;
        particles[index] = p;
        return;
    }
    let cursor = vec2<f32>(params.cursor_x, params.cursor_y);
    let zone_force = attraction(pos, vec2<f32>(params.zone0_x, params.zone0_y), params.zone0_radius, params.objective_zone_count > 0u)
        + attraction(pos, vec2<f32>(params.zone1_x, params.zone1_y), params.zone1_radius, params.objective_zone_count > 1u)
        + attraction(pos, vec2<f32>(params.zone2_x, params.zone2_y), params.zone2_radius, params.objective_zone_count > 2u);
    let cursor_force = attraction(pos, cursor, 0.12, params.applying == 1u);
    let rival_force = -attraction(pos, vec2<f32>(params.rival_x, params.rival_y), max(params.rival_radius, 0.0001), params.rival_enabled == 1u) * 0.45;
    let hazard_band = select(
        0.0,
        smoothstep(max(params.hazard_width, 0.0001) * 0.7, max(params.hazard_width, 0.0001) * 0.3, abs(p.x - params.hazard_center_x)) * params.hazard_strength,
        params.hazard_enabled == 1u,
    );
    let pause_scale = select(1.0, 0.0, params.paused == 1u);
    let swirl = vec2<f32>(sin(f32(index) * 0.37 + f32(params.frame) * 0.013), cos(f32(index) * 0.29 + f32(params.frame) * 0.011)) * 0.00018;

    var velocity = vec2<f32>(p.vx, p.vy);
    let forward = sensor_orientation(pos, velocity);
    let sensor_distance = setting_value(SETTING_SENSOR_DISTANCE, pos, cohort, params.frame);
    let sensor_angle = setting_value(SETTING_SENSOR_ANGLE, pos, cohort, params.frame);
    let left_sensor = pos + rotate(forward, sensor_angle) * sensor_distance;
    let right_sensor = pos + rotate(forward, -sensor_angle) * sensor_distance;
    let left_trail = trail_at(left_sensor);
    let right_trail = trail_at(right_sensor);
    let speed = length(velocity);
    let mutation_scale = setting_value(SETTING_MUTATION_SCALE, pos, cohort, params.frame);
    let sensor_gain = setting_value(SETTING_SENSOR_GAIN, pos, cohort, params.frame);
    let mutation_phase = sin(f32(params.frame) * 0.002 + f32(p.cohort) * 0.37) * mutation_scale;
    let trail_delta = (right_trail - left_trail) * sensor_gain;
    let trail_sum = (left_trail + right_trail) * 0.5 * sensor_gain;
    let rule_input = vec4<f32>(left_trail, right_trail, trail_delta, speed * 120.0 + mutation_phase);
    let rule_seed = p.rule_seed ^ params.rule_seed ^ (cohort * 0x9e37u);
    let base_rule = native_rule(rule_input, rule_seed);
    let mirror_input = vec4<f32>(right_trail, -right_trail, left_trail, -left_trail);
    let mirror_rule_raw = native_rule(mirror_input, rule_seed);
    let mirror_rule = vec4<f32>(mirror_rule_raw.x, -mirror_rule_raw.y, mirror_rule_raw.z, -mirror_rule_raw.w);
    let rule = select((base_rule + mirror_rule) * 0.5, base_rule, params.disable_symmetry == 1u);
    let axial_force = setting_value(SETTING_AXIAL_FORCE, pos, cohort, params.frame);
    let lateral_force = setting_value(SETTING_LATERAL_FORCE, pos, cohort, params.frame);
    let global_force_mult = setting_value(SETTING_GLOBAL_FORCE_MULT, pos, cohort, params.frame);
    let strafe_power = setting_value(SETTING_STRAFE_POWER, pos, cohort, params.frame);
    let trail_turn = rotate(forward, clamp(trail_delta * 1.4 + rule.x * 0.95, -0.9, 0.9)) * (0.00062 * global_force_mult);
    let trail_seek = forward * (trail_sum * axial_force * 0.00036 + rule.y * 0.00034 * global_force_mult);
    let strafe = vec2<f32>(-forward.y, forward.x) * (rule.z * strafe_power + lateral_force * 0.08) * 0.00042;
    let rule_drive = vec2<f32>(rule.x + rule.w * 0.35, rule.y - rule.z * 0.35) * (0.00072 * global_force_mult);

    let drag = setting_value(SETTING_DRAG, pos, cohort, params.frame);
    let damping = clamp(0.992 - drag * 0.014 - hazard_band * 0.08, 0.90, 0.995);
    velocity = velocity * damping + (zone_force * 0.00034 + cursor_force * 0.0009 + rival_force * 0.00032 + trail_turn + trail_seek + strafe + rule_drive + swirl) * pause_scale;
    velocity = clamp(velocity, vec2<f32>(-0.006, -0.006), vec2<f32>(0.006, 0.006));
    var next_pos = pos + velocity * pause_scale;
    let out_of_bounds = next_pos.x < 0.04 || next_pos.x > 0.96 || next_pos.y < 0.04 || next_pos.y > 0.96;
    if (params.boundary_conditions == 2u) {
        next_pos = fract(next_pos);
        next_pos = clamp(next_pos, vec2<f32>(0.02, 0.02), vec2<f32>(0.98, 0.98));
    } else if (params.boundary_conditions == 1u && out_of_bounds) {
        next_pos = reset_position(index, params.frame);
        let reset_angle = hash01(index ^ params.frame, 643u) * 6.2831853;
        velocity = vec2<f32>(cos(reset_angle), sin(reset_angle)) * 0.0015;
    } else {
        if (next_pos.x < 0.04 || next_pos.x > 0.96) {
            velocity.x = -velocity.x * 0.8;
        }
        if (next_pos.y < 0.04 || next_pos.y > 0.96) {
            velocity.y = -velocity.y * 0.8;
        }
        next_pos = clamp(next_pos, vec2<f32>(0.04, 0.04), vec2<f32>(0.96, 0.96));
    }

    p.x = next_pos.x;
    p.y = next_pos.y;
    p.vx = velocity.x;
    p.vy = velocity.y;
    particles[index] = p;

    let px = min(u32(next_pos.x * f32(params.width)), params.width - 1u);
    let py = min(u32(next_pos.y * f32(params.height)), params.height - 1u);
    let pixel_index = py * params.width + px;
    let trail_diffusion = setting_value(SETTING_TRAIL_DIFFUSION, pos, cohort, params.frame);
    let rule_deposit = length(rule.xy) * 420.0 + abs(rule.w) * 180.0;
    atomicAdd(&trail_target[pixel_index], u32(clamp(512.0 + trail_diffusion * 256.0 + rule_deposit, 256.0, 2048.0)));
    let display_speed = min(length(velocity) * 9000.0, 1.0);
    let rule_hue = fract(rule.x * params.hue_sensitivity + rule.w * 0.13 + 0.5);
    let cohort_hue = hash01(cohort, 811u);
    let hue = select(rule_hue, cohort_hue, params.color_by_cohort == 1u);
    let rgb = hsv_to_rgb(hue, 0.78, 0.70 + display_speed * 0.30) * 255.0;
    let r = u32(clamp(rgb.r, 0.0, 255.0));
    let g = u32(clamp(rgb.g, 0.0, 255.0));
    let b = u32(clamp(rgb.b, 0.0, 255.0));
    atomicMax(&pixels[pixel_index], pack_rgba8(r, g, b, 255u));
}
