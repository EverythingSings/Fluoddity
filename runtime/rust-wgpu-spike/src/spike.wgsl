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

@group(0) @binding(0)
var<storage, read_write> pixels: array<atomic<u32>>;

@group(0) @binding(1)
var<uniform> params: Params;

@group(0) @binding(3)
var<storage, read> trail_source: array<u32>;

@group(0) @binding(5)
var<storage, read> overlay_text: array<u32>;

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

@group(0) @binding(6)
var<storage, read> physics_settings: array<NativeSetting>;

@group(0) @binding(7)
var<storage, read_write> trail_target: array<atomic<u32>>;

const TEXT_COLUMNS: u32 = 96u;
const GLYPH_WIDTH: u32 = 5u;
const GLYPH_HEIGHT: u32 = 7u;
const SETTING_TRAIL_PERSISTENCE: u32 = 9u;

fn pack_rgba8(r: u32, g: u32, b: u32, a: u32) -> u32 {
    return (a << 24u) | (b << 16u) | (g << 8u) | r;
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

fn setting_value(setting_index: u32, pos: vec2<f32>, frame: u32) -> f32 {
    let setting = physics_settings[setting_index];
    if (setting.x_sweep == 0.0 && setting.y_sweep == 0.0 && setting.jitter == 0.0) {
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

fn zone_ring(x: f32, y: f32, center_x: f32, center_y: f32, radius: f32, enabled: bool) -> f32 {
    let ring = smoothstep(0.018, 0.006, abs(distance(vec2<f32>(x, y), vec2<f32>(center_x, center_y)) - radius));
    return select(0.0, ring, enabled);
}

fn rect_mask(p: vec2<f32>, min_p: vec2<f32>, max_p: vec2<f32>) -> f32 {
    let left = smoothstep(min_p.x - 0.002, min_p.x + 0.002, p.x);
    let right = 1.0 - smoothstep(max_p.x - 0.002, max_p.x + 0.002, p.x);
    let top = smoothstep(min_p.y - 0.002, min_p.y + 0.002, p.y);
    let bottom = 1.0 - smoothstep(max_p.y - 0.002, max_p.y + 0.002, p.y);
    return left * right * top * bottom;
}

fn rect_stroke(p: vec2<f32>, min_p: vec2<f32>, max_p: vec2<f32>, thickness: f32) -> f32 {
    let outer = rect_mask(p, min_p, max_p);
    let inner = rect_mask(p, min_p + vec2<f32>(thickness), max_p - vec2<f32>(thickness));
    return clamp(outer - inner, 0.0, 1.0);
}

fn circle_stroke(p: vec2<f32>, center: vec2<f32>, radius: f32, thickness: f32) -> f32 {
    return smoothstep(thickness, 0.0, abs(distance(p, center) - radius));
}

fn objective_pip(p: vec2<f32>, center: vec2<f32>, enabled: bool) -> f32 {
    let active_pip = circle_stroke(p, center, 0.014, 0.004);
    let inactive = circle_stroke(p, center, 0.010, 0.002) * 0.35;
    return select(inactive, active_pip, enabled);
}

fn zone_active(index: u32) -> bool {
    return ((params.active_zone_mask >> index) & 1u) == 1u;
}

fn glyph_row(ch: u32, row: u32) -> u32 {
    var bits = 0u;
    switch ch {
        case 48u: { let rows = array<u32, 7>(14u, 17u, 19u, 21u, 25u, 17u, 14u); bits = rows[row]; } // 0
        case 49u: { let rows = array<u32, 7>(4u, 12u, 4u, 4u, 4u, 4u, 14u); bits = rows[row]; } // 1
        case 50u: { let rows = array<u32, 7>(14u, 17u, 1u, 2u, 4u, 8u, 31u); bits = rows[row]; } // 2
        case 51u: { let rows = array<u32, 7>(30u, 1u, 1u, 14u, 1u, 1u, 30u); bits = rows[row]; } // 3
        case 52u: { let rows = array<u32, 7>(2u, 6u, 10u, 18u, 31u, 2u, 2u); bits = rows[row]; } // 4
        case 53u: { let rows = array<u32, 7>(31u, 16u, 30u, 1u, 1u, 17u, 14u); bits = rows[row]; } // 5
        case 54u: { let rows = array<u32, 7>(6u, 8u, 16u, 30u, 17u, 17u, 14u); bits = rows[row]; } // 6
        case 55u: { let rows = array<u32, 7>(31u, 1u, 2u, 4u, 8u, 8u, 8u); bits = rows[row]; } // 7
        case 56u: { let rows = array<u32, 7>(14u, 17u, 17u, 14u, 17u, 17u, 14u); bits = rows[row]; } // 8
        case 57u: { let rows = array<u32, 7>(14u, 17u, 17u, 15u, 1u, 2u, 12u); bits = rows[row]; } // 9
        case 65u: { let rows = array<u32, 7>(14u, 17u, 17u, 31u, 17u, 17u, 17u); bits = rows[row]; } // A
        case 66u: { let rows = array<u32, 7>(30u, 17u, 17u, 30u, 17u, 17u, 30u); bits = rows[row]; } // B
        case 67u: { let rows = array<u32, 7>(14u, 17u, 16u, 16u, 16u, 17u, 14u); bits = rows[row]; } // C
        case 68u: { let rows = array<u32, 7>(30u, 17u, 17u, 17u, 17u, 17u, 30u); bits = rows[row]; } // D
        case 69u: { let rows = array<u32, 7>(31u, 16u, 16u, 30u, 16u, 16u, 31u); bits = rows[row]; } // E
        case 70u: { let rows = array<u32, 7>(31u, 16u, 16u, 30u, 16u, 16u, 16u); bits = rows[row]; } // F
        case 71u: { let rows = array<u32, 7>(14u, 17u, 16u, 23u, 17u, 17u, 14u); bits = rows[row]; } // G
        case 72u: { let rows = array<u32, 7>(17u, 17u, 17u, 31u, 17u, 17u, 17u); bits = rows[row]; } // H
        case 73u: { let rows = array<u32, 7>(14u, 4u, 4u, 4u, 4u, 4u, 14u); bits = rows[row]; } // I
        case 74u: { let rows = array<u32, 7>(7u, 2u, 2u, 2u, 18u, 18u, 12u); bits = rows[row]; } // J
        case 75u: { let rows = array<u32, 7>(17u, 18u, 20u, 24u, 20u, 18u, 17u); bits = rows[row]; } // K
        case 76u: { let rows = array<u32, 7>(16u, 16u, 16u, 16u, 16u, 16u, 31u); bits = rows[row]; } // L
        case 77u: { let rows = array<u32, 7>(17u, 27u, 21u, 21u, 17u, 17u, 17u); bits = rows[row]; } // M
        case 78u: { let rows = array<u32, 7>(17u, 25u, 21u, 19u, 17u, 17u, 17u); bits = rows[row]; } // N
        case 79u: { let rows = array<u32, 7>(14u, 17u, 17u, 17u, 17u, 17u, 14u); bits = rows[row]; } // O
        case 80u: { let rows = array<u32, 7>(30u, 17u, 17u, 30u, 16u, 16u, 16u); bits = rows[row]; } // P
        case 81u: { let rows = array<u32, 7>(14u, 17u, 17u, 17u, 21u, 18u, 13u); bits = rows[row]; } // Q
        case 82u: { let rows = array<u32, 7>(30u, 17u, 17u, 30u, 20u, 18u, 17u); bits = rows[row]; } // R
        case 83u: { let rows = array<u32, 7>(15u, 16u, 16u, 14u, 1u, 1u, 30u); bits = rows[row]; } // S
        case 84u: { let rows = array<u32, 7>(31u, 4u, 4u, 4u, 4u, 4u, 4u); bits = rows[row]; } // T
        case 85u: { let rows = array<u32, 7>(17u, 17u, 17u, 17u, 17u, 17u, 14u); bits = rows[row]; } // U
        case 86u: { let rows = array<u32, 7>(17u, 17u, 17u, 17u, 17u, 10u, 4u); bits = rows[row]; } // V
        case 87u: { let rows = array<u32, 7>(17u, 17u, 17u, 21u, 21u, 21u, 10u); bits = rows[row]; } // W
        case 88u: { let rows = array<u32, 7>(17u, 17u, 10u, 4u, 10u, 17u, 17u); bits = rows[row]; } // X
        case 89u: { let rows = array<u32, 7>(17u, 17u, 10u, 4u, 4u, 4u, 4u); bits = rows[row]; } // Y
        case 90u: { let rows = array<u32, 7>(31u, 1u, 2u, 4u, 8u, 16u, 31u); bits = rows[row]; } // Z
        case 45u: { let rows = array<u32, 7>(0u, 0u, 0u, 14u, 0u, 0u, 0u); bits = rows[row]; } // -
        case 46u: { let rows = array<u32, 7>(0u, 0u, 0u, 0u, 0u, 12u, 12u); bits = rows[row]; } // .
        case 58u: { let rows = array<u32, 7>(0u, 12u, 12u, 0u, 12u, 12u, 0u); bits = rows[row]; } // :
        default: { bits = 0u; }
    }
    return bits;
}

fn text_line_mask(p: vec2<f32>, origin: vec2<f32>, scale: f32, row_index: u32) -> f32 {
    let rel = (p - origin) / scale;
    if (rel.x < 0.0 || rel.y < 0.0 || rel.y >= f32(GLYPH_HEIGHT)) {
        return 0.0;
    }
    let char_column = u32(floor(rel.x / 6.0));
    if (char_column >= TEXT_COLUMNS) {
        return 0.0;
    }
    let glyph_x = u32(floor(rel.x)) % 6u;
    let glyph_y = u32(floor(rel.y));
    if (glyph_x >= GLYPH_WIDTH || glyph_y >= GLYPH_HEIGHT) {
        return 0.0;
    }
    let ch = overlay_text[row_index * TEXT_COLUMNS + char_column];
    let row_bits = glyph_row(ch, glyph_y);
    let bit = (row_bits >> (4u - glyph_x)) & 1u;
    return f32(bit);
}

fn text_overlay(p: vec2<f32>) -> vec4<f32> {
    let title = text_line_mask(p, vec2<f32>(0.170, 0.047), 0.0024, 0u);
    let objective = text_line_mask(p, vec2<f32>(0.170, 0.073), 0.00135, 1u);
    let prompts = text_line_mask(p, vec2<f32>(0.285, 0.928), 0.0019, 2u);
    let mask = clamp(title + objective + prompts, 0.0, 1.0);
    let color = vec3<f32>(0.84, 1.0, 0.92) * (title + prompts) + vec3<f32>(0.58, 0.88, 1.0) * objective;
    return vec4<f32>(min(color, vec3<f32>(1.0)), mask);
}

fn controller_overlay(p: vec2<f32>) -> vec4<f32> {
    let top_panel = rect_mask(p, vec2<f32>(0.032, 0.030), vec2<f32>(0.968, 0.112)) * 0.70;
    let top_stroke = rect_stroke(p, vec2<f32>(0.032, 0.030), vec2<f32>(0.968, 0.112), 0.004);
    let progress = clamp(params.progress, 0.0, 1.0);
    let progress_track = rect_mask(p, vec2<f32>(0.120, 0.086), vec2<f32>(0.880, 0.094));
    let progress_fill = rect_mask(p, vec2<f32>(0.120, 0.086), vec2<f32>(0.120 + 0.760 * progress, 0.094));
    let zone0 = objective_pip(p, vec2<f32>(0.070, 0.071), params.objective_zone_count > 0u && zone_active(0u));
    let zone1 = objective_pip(p, vec2<f32>(0.102, 0.071), params.objective_zone_count > 1u && zone_active(1u));
    let zone2 = objective_pip(p, vec2<f32>(0.134, 0.071), params.objective_zone_count > 2u && zone_active(2u));

    let pause_badge = rect_mask(p, vec2<f32>(0.898, 0.052), vec2<f32>(0.940, 0.090)) * select(0.18, 1.0, params.paused == 1u);
    let pause_bar_a = rect_mask(p, vec2<f32>(0.910, 0.060), vec2<f32>(0.916, 0.082));
    let pause_bar_b = rect_mask(p, vec2<f32>(0.922, 0.060), vec2<f32>(0.928, 0.082));

    let bottom_panel = rect_mask(p, vec2<f32>(0.260, 0.900), vec2<f32>(0.740, 0.970)) * 0.62;
    let bottom_stroke = rect_stroke(p, vec2<f32>(0.260, 0.900), vec2<f32>(0.740, 0.970), 0.004);
    let a_button = circle_stroke(p, vec2<f32>(0.318, 0.936), 0.020, 0.005);
    let trigger_button = rect_stroke(p, vec2<f32>(0.455, 0.917), vec2<f32>(0.545, 0.954), 0.005);
    let menu_button = rect_stroke(p, vec2<f32>(0.650, 0.920), vec2<f32>(0.695, 0.952), 0.005);
    let apply_light = rect_mask(p, vec2<f32>(0.466, 0.926), vec2<f32>(0.534, 0.945)) * select(0.12, 0.85, params.applying == 1u);
    let stick_dot = circle_stroke(p, vec2<f32>(0.382, 0.936), 0.013, 0.004);
    let stick_vector = rect_mask(
        p,
        vec2<f32>(0.382 + (params.cursor_x - 0.5) * 0.046 - 0.004, 0.936 + (params.cursor_y - 0.5) * 0.046 - 0.004),
        vec2<f32>(0.382 + (params.cursor_x - 0.5) * 0.046 + 0.004, 0.936 + (params.cursor_y - 0.5) * 0.046 + 0.004),
    );

    let cool = vec3<f32>(0.08, 0.18, 0.22);
    let line = vec3<f32>(0.62, 0.95, 0.90);
    let warm = vec3<f32>(1.00, 0.58, 0.32);
    let violet = vec3<f32>(0.42, 0.54, 1.00);
    var color = cool * (top_panel + bottom_panel);
    color = color + line * (top_stroke + progress_track * 0.22 + progress_fill * 0.75 + zone0 + zone1 + zone2 + bottom_stroke + a_button + trigger_button + menu_button + stick_dot + stick_vector);
    let success = select(0.0, 1.0, params.run_status == 2u);
    let failed = select(0.0, 1.0, params.run_status == 3u);
    color = color + warm * (pause_badge + pause_bar_a + pause_bar_b + apply_light + failed * progress_track * 0.6);
    color = color + violet * (rect_mask(p, vec2<f32>(0.160, 0.056), vec2<f32>(0.880, 0.068)) * 0.42);
    color = color + vec3<f32>(0.42, 1.0, 0.58) * success * (progress_fill + zone0 + zone1 + zone2);
    let text = text_overlay(p);
    color = color + text.rgb;
    let alpha = clamp(top_panel + top_stroke + progress_track + progress_fill + zone0 + zone1 + zone2 + pause_badge + pause_bar_a + pause_bar_b + bottom_panel + bottom_stroke + a_button + trigger_button + menu_button + apply_light + stick_dot + stick_vector + text.a, 0.0, 0.92);
    return vec4<f32>(color, alpha);
}

@compute @workgroup_size(16, 16, 1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    if (gid.x >= params.width || gid.y >= params.height) {
        return;
    }

    let index = gid.y * params.width + gid.x;
    let x = f32(gid.x) / f32(max(params.width - 1u, 1u));
    let y = f32(gid.y) / f32(max(params.height - 1u, 1u));
    let t = f32(params.frame % 240u) / 240.0;
    let trial_bias = f32(params.trial_count) * 0.071;
    let seed_bias = f32(params.rule_seed % 997u) / 997.0;
    let pause_scale = select(1.0, 0.25, params.paused == 1u);
    let flow_angle = params.sensor_angle + seed_bias * 6.2831853;
    let flow_axis = vec2<f32>(cos(flow_angle), sin(flow_angle));
    let cross_axis = vec2<f32>(-flow_axis.y, flow_axis.x);
    let flow_coord = dot(vec2<f32>(x, y), flow_axis);
    let cross_coord = dot(vec2<f32>(x, y), cross_axis);
    let wave = 0.5 + 0.5 * sin(
        (flow_coord * (10.0 + params.sensor_gain * 0.8))
            + (cross_coord * (7.0 + params.sensor_distance * 60.0))
            + (t * 6.2831853 * pause_scale)
            + trial_bias,
    );
    let dish = smoothstep(0.42, 0.38, distance(vec2<f32>(x, y), vec2<f32>(0.5, 0.5)));
    let objective_ring = max(
        zone_ring(x, y, params.zone0_x, params.zone0_y, params.zone0_radius, params.objective_zone_count > 0u),
        max(
            zone_ring(x, y, params.zone1_x, params.zone1_y, params.zone1_radius, params.objective_zone_count > 1u),
            zone_ring(x, y, params.zone2_x, params.zone2_y, params.zone2_radius, params.objective_zone_count > 2u),
        ),
    );
    let cursor_distance = distance(vec2<f32>(x, y), vec2<f32>(params.cursor_x, params.cursor_y));
    let cursor = smoothstep(0.018, 0.012, cursor_distance);
    let applicator = select(0.0, smoothstep(0.085, 0.02, cursor_distance), params.applying == 1u);
    let hazard_width = max(params.hazard_width, 0.0001);
    let rival_radius = max(params.rival_radius, 0.0001);
    let old_trail = trail_source[index];
    let trail_persistence = setting_value(SETTING_TRAIL_PERSISTENCE, vec2<f32>(x, y), params.frame);
    let decayed_trail = u32(f32(old_trail) * trail_persistence);
    atomicStore(&trail_target[index], decayed_trail);
    let trail = min(f32(decayed_trail) / 65535.0, 1.0);
    let trail_signal = pow(trail, 0.55);
    let config_hue = fract(seed_bias + params.hue_sensitivity * 0.37 + f32(params.num_cohorts % 17u) * 0.041);
    let warm = vec3<f32>(0.95, 0.48 + 0.26 * config_hue, 0.22 + 0.30 * params.orientation_mix);
    let cool = vec3<f32>(0.16 + 0.38 * config_hue, 0.54 + 0.20 * wave, 0.86);
    let trail_tint = mix(cool, warm, clamp(params.ink_weight / 4.0, 0.0, 1.0));
    let hazard = select(
        0.0,
        smoothstep(hazard_width * 0.55, hazard_width * 0.5, abs(x - params.hazard_center_x)) * params.hazard_strength,
        params.hazard_enabled == 1u,
    );
    let rival = select(
        0.0,
        smoothstep(rival_radius, rival_radius * 0.68, distance(vec2<f32>(x, y), vec2<f32>(params.rival_x, params.rival_y))),
        params.rival_enabled == 1u,
    );

    var base = (
        vec3<f32>(12.0, 20.0, 26.0)
            + vec3<f32>(wave * 30.0, wave * 42.0, (1.0 - wave) * 34.0)
            + trail_tint * (trail_signal * 235.0)
            + vec3<f32>(objective_ring * 160.0 + applicator * 80.0 + hazard * 220.0 + rival * 90.0, applicator * 150.0 + objective_ring * 80.0 - hazard * 90.0, objective_ring * 80.0 + rival * 210.0)
    ) * dish + vec3<f32>(cursor * 255.0, cursor * 245.0, cursor * 120.0);
    base = clamp(base, vec3<f32>(0.0), vec3<f32>(255.0));
    let overlay = controller_overlay(vec2<f32>(x, y));
    base = mix(base, overlay.rgb * 255.0, overlay.a);
    let r = u32(clamp(base.r, 0.0, 255.0));
    let g = u32(clamp(base.g, 0.0, 255.0));
    let b = u32(clamp(base.b, 0.0, 255.0));
    atomicStore(&pixels[index], pack_rgba8(r, g, b, 255u));
}
