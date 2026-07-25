// networked.art/everything artifact: canonical particle update.
//
// Buffer layouts are deliberately identical to the desktop GLSL:
//   Entity        = 48 bytes
//   FourierCenter = 32 bytes
//   Rule          = 320 bytes (10 centers)
//
// PhysicsSetting is padded to 32 bytes for a simple JavaScript upload contract:
//   first  = (slider_value, min_value, max_value, x_sweep)
//   second = (y_sweep, cohort_sweep, jitter, unused)
//
// Settings order:
//   0 axial force, 1 lateral force, 2 sensor gain, 3 mutation scale,
//   4 drag, 5 strafe power, 6 sensor angle, 7 global force multiplier,
//   8 sensor distance, 9 hazard rate, 10 trail persistence,
//   11 trail diffusion.

const PI: f32 = 3.1415926;

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

struct FourierCenter {
    frequency: vec4<f32>,
    amplitude: vec4<f32>,
};

struct Rule {
    centers: array<FourierCenter, 10>,
};

struct RuleBuffer {
    rule: Rule,
};

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

@group(0) @binding(0) var<storage, read_write> entity_buffer: EntityBuffer;
@group(0) @binding(1) var<uniform> globals: Globals;
@group(0) @binding(2) var trail_texture: texture_2d<f32>;
@group(0) @binding(3) var trail_sampler: sampler;
@group(0) @binding(4) var<storage, read> rule_buffer: RuleBuffer;
@group(0) @binding(5) var<storage, read> settings_buffer: SettingsBuffer;

fn pcg_hash(seed: u32) -> u32 {
    let state = seed * 747796405u + 2891336453u;
    let word = ((state >> ((state >> 28u) + 4u)) ^ state) * 277803737u;
    return (word >> 22u) ^ word;
}

fn hash2(coordinates: vec2<f32>) -> f32 {
    let bits = bitcast<vec2<u32>>(coordinates);
    let value = pcg_hash(bits.x ^ pcg_hash(bits.y));
    return f32(value) / 4294967295.0;
}

fn hash4(coordinates: vec2<f32>) -> vec4<f32> {
    return vec4<f32>(
        hash2(coordinates),
        hash2(-coordinates + vec2<f32>(5.0)),
        hash2(coordinates.yx - vec2<f32>(100.0)),
        hash2(-coordinates.yx + vec2<f32>(25.0)),
    );
}

fn fourier_noise(rule: Rule, position: vec4<f32>) -> vec4<f32> {
    var result = vec4<f32>(0.0);
    for (var index = 0u; index < 10u; index++) {
        let center = rule.centers[index];
        let phase = dot(position, center.frequency);
        let phase_offset = 2.0 * f32(index) * 0.6283
            + center.amplitude.w * 3.14159;
        let basis = vec4<f32>(
            sin(phase + phase_offset),
            cos(phase + phase_offset * 0.7),
            sin(phase * 2.0 + phase_offset * 1.3),
            cos(phase * 2.0 + phase_offset * 0.5),
        );
        result += center.amplitude * basis;
    }
    return result;
}

fn generate_random_rule(seed: f32) -> Rule {
    var result: Rule;
    for (var index = 0u; index < 10u; index++) {
        let base = index * 8u;
        let frequency_scale =
            1.0 + 2.0 * pow(hash2(vec2<f32>(seed, f32(base))), 2.0);
        result.centers[index].frequency = vec4<f32>(
            (hash2(vec2<f32>(seed, f32(base + 0u))) * 2.0 - 1.0)
                * frequency_scale,
            (hash2(vec2<f32>(seed, f32(base + 1u))) * 2.0 - 1.0)
                * frequency_scale,
            (hash2(vec2<f32>(seed, f32(base + 2u))) * 2.0 - 1.0)
                * frequency_scale,
            (hash2(vec2<f32>(seed, f32(base + 3u))) * 2.0 - 1.0)
                * frequency_scale,
        );
        result.centers[index].amplitude = vec4<f32>(
            hash2(vec2<f32>(seed, f32(base + 4u))) * 2.0 - 1.0,
            hash2(vec2<f32>(seed, f32(base + 5u))) * 2.0 - 1.0,
            hash2(vec2<f32>(seed, f32(base + 6u))) * 2.0 - 1.0,
            hash2(vec2<f32>(seed, f32(base + 7u))) * 2.0 - 1.0,
        );
    }
    return result;
}

fn mutate_rule(input_rule: Rule, amount: f32, cohort: f32) -> Rule {
    var result = input_rule;
    let seed = hash2(
        result.centers[4].frequency.xy
        + result.centers[7].amplitude.yx
        + result.centers[1].frequency.zw,
    ) + cohort;

    for (var index = 0u; index < 10u; index++) {
        let signed_index = f32(index);
        let amplitude_mutation = amount * (
            -vec4<f32>(1.0)
            + 2.0 * hash4(
                vec2<f32>(-0.5 - signed_index + seed, signed_index),
            )
        );
        result.centers[index].amplitude += amplitude_mutation;
        result.centers[index].frequency *=
            1.0 + amount * 0.5
            * (hash2(vec2<f32>(seed, signed_index)) - 0.5);
    }
    return result;
}

fn safe_normalize(value: vec2<f32>) -> vec2<f32> {
    let magnitude = length(value);
    if (magnitude == 0.0) {
        return vec2<f32>(0.0);
    }
    return value / magnitude;
}

fn rotate_clockwise(value: vec2<f32>, angle: f32) -> vec2<f32> {
    return cos(angle) * value + sin(angle) * vec2<f32>(value.y, -value.x);
}

fn y_reflect(value: vec2<f32>) -> vec2<f32> {
    return value * vec2<f32>(1.0, -1.0);
}

fn edgeflect(value: f32) -> f32 {
    return sign(value) * (1.0 - abs(1.0 - abs(value)));
}

fn cohort_for_index(index: u32) -> f32 {
    return f32(globals.sim.z) * f32(index) / max(f32(globals.sim.y), 1.0);
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
    let sweep_cohort =
        floor(cohort) / max(f32(globals.sim.z), 1.0);
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
        let random_value = hash2(vec2<f32>(
            f32(globals.sim.x) + result,
            sweep_position.x + sweep_position.y * 1000.0,
        )) * 2.0 - 1.0;
        result += jitter * result * random_value;
    }
    return result;
}

fn trail_at(entity_position: vec2<f32>) -> vec4<f32> {
    let canvas_aspect = globals.canvas.x / max(globals.canvas.y, 1.0);
    let half_extent = vec2<f32>(sqrt(canvas_aspect), inverseSqrt(canvas_aspect));
    var uv = vec2<f32>(
        entity_position.x / (2.0 * half_extent.x) + 0.5,
        0.5 - entity_position.y / (2.0 * half_extent.y),
    );
    if (globals.sim.w == 2u) {
        uv = fract(uv);
    }
    return textureSampleLevel(trail_texture, trail_sampler, uv, 0.0);
}

fn reset_entity(index: u32) -> Entity {
    let world_size = max(globals.canvas.z, 0.000001);
    let sqrt_world_size = sqrt(world_size);
    let cohorts = max(globals.sim.z, 1u);
    let cohort_value = cohort_for_index(index);
    let aspect = sqrt(globals.canvas.x / max(globals.canvas.y, 1.0));
    let cohort_scale = 0.019;

    var position = cohort_scale * vec2<f32>(
        hash2(vec2<f32>(cohort_value)),
        hash2(vec2<f32>(cohort_value + f32(index) + 2.142)),
    );
    let velocity = 0.00005 * (
        vec2<f32>(
            hash2(vec2<f32>(cohort_value, f32(index))),
            hash2(vec2<f32>(cohort_value, position.y)),
        ) * 2.0 - vec2<f32>(1.0)
    );

    if (globals.modes.x == 0u) {
        let spots = f32(cohorts);
        let spot_rows = ceil(aspect * sqrt(spots));
        let cohort_index = u32(floor(cohort_value));
        let row_count = max(u32(spot_rows), 1u);
        let grid_cell = vec2<f32>(
            f32(cohort_index % row_count),
            f32(cohort_index / row_count),
        );
        position += 1.8 * (grid_cell / spot_rows) * vec2<f32>(aspect);
        position += 1.8 * (
            0.5 * (
                vec2<f32>(1.0)
                / vec2<f32>(spot_rows, spots / spot_rows)
                - vec2<f32>(1.0)
            )
        ) * vec2<f32>(aspect, 1.0 / aspect);
    } else if (globals.modes.x == 1u) {
        position = vec2<f32>(
            hash2(vec2<f32>(cohort_value, 1.0)),
            hash2(vec2<f32>(cohort_value, 2.0)),
        ) * 2.0 - vec2<f32>(1.0);
        position.x *= aspect;
        position.y /= aspect;
    } else {
        let angle = cohort_value / f32(cohorts) * 2.0 * PI;
        position += vec2<f32>(cos(angle), sin(angle)) * 0.5;
    }

    var result: Entity;
    result.pos = position;
    result.vel = velocity;
    result.size = 0.0015 / sqrt_world_size;
    result.cohort = cohort_value / f32(cohorts);
    result.padding = vec2<f32>(0.0);
    result.color = vec4<f32>(0.0, 0.0, 1.0, 0.045);
    return result;
}

struct Behavior {
    force: vec2<f32>,
    strafe: vec2<f32>,
    color: vec2<f32>,
};

fn calculate_behavior(
    left_sample_world: vec2<f32>,
    right_sample_world: vec2<f32>,
    axis: vec2<f32>,
    rule: Rule,
    entity_position: vec2<f32>,
    cohort: f32,
) -> Behavior {
    let forward = safe_normalize(axis);
    let left = vec2<f32>(forward.y, -forward.x);
    let left_sample = vec2<f32>(
        dot(left_sample_world, forward),
        dot(left_sample_world, left),
    );
    let right_sample = vec2<f32>(
        dot(right_sample_world, forward),
        dot(right_sample_world, left),
    );

    let base_term = fourier_noise(
        rule,
        vec4<f32>(left_sample, right_sample),
    );
    var mirror_term = fourier_noise(
        rule,
        vec4<f32>(y_reflect(right_sample), y_reflect(left_sample)),
    );
    if (globals.modes.z != 0u) {
        mirror_term = vec4<f32>(0.0);
    }

    var local_force = base_term.xy + y_reflect(mirror_term.xy);
    var local_strafe = base_term.zw + y_reflect(mirror_term.zw);
    let axial = calculate_setting(0u, entity_position, cohort);
    let lateral = calculate_setting(1u, entity_position, cohort);

    var result: Behavior;
    result.force =
        forward * local_force.x * axial + left * local_force.y * lateral;
    result.strafe =
        forward * local_strafe.x * axial + left * local_strafe.y * lateral;
    result.color = base_term.xy + mirror_term.xy;
    return result;
}

@compute @workgroup_size(64)
fn cs_main(@builtin(global_invocation_id) global_id: vec3<u32>) {
    let index = global_id.x;
    let active_count = globals.sim.y;
    if (index >= active_count) {
        return;
    }

    var entity = entity_buffer.entities[index];
    let cohort = cohort_for_index(index);
    var current_rule = rule_buffer.rule;
    let rule_is_empty =
        all(current_rule.centers[0].frequency == vec4<f32>(0.0))
        && all(current_rule.centers[5].amplitude == vec4<f32>(0.0));
    if (rule_is_empty) {
        current_rule = generate_random_rule(
            globals.rule_params.x + floor(cohort),
        );
    }
    current_rule = mutate_rule(
        current_rule,
        calculate_setting(3u, entity.pos, cohort),
        globals.rule_params.x + floor(cohort),
    );

    let hazard_rate = calculate_setting(9u, entity.pos, cohort);
    let hazard_sample = hash2(vec2<f32>(
        f32(index) / max(f32(active_count), 1.0),
        f32(globals.sim.x),
    ));
    if (globals.sim.x == 0u || hazard_rate > hazard_sample) {
        entity_buffer.entities[index] = reset_entity(index);
        return;
    }

    let sqrt_world_size = sqrt(max(globals.canvas.z, 0.000001));
    let sample_distance =
        0.005 / sqrt_world_size
        * calculate_setting(8u, entity.pos, cohort);

    let orientation_mode = globals.modes.y;
    let orientation_mix =
        min(1.0, f32(orientation_mode)) * globals.appearance.y;
    var orientation = safe_normalize(entity.vel);
    if (orientation_mode == 1u) {
        orientation = mix(
            orientation,
            vec2<f32>(0.0, 1.0),
            orientation_mix,
        );
    } else if (orientation_mode == 2u) {
        orientation = mix(
            orientation,
            -safe_normalize(entity.pos),
            orientation_mix,
        );
    }

    let sensor_angle =
        calculate_setting(6u, entity.pos, cohort) * PI;
    let left_offset =
        rotate_clockwise(orientation * sample_distance, sensor_angle);
    let right_offset =
        rotate_clockwise(orientation * sample_distance, -sensor_angle);
    let sensor_scaling =
        sqrt_world_size * 38.855
        * calculate_setting(2u, entity.pos, cohort);
    let left_tap =
        trail_at(entity.pos + left_offset) * sensor_scaling;
    let right_tap =
        trail_at(entity.pos + right_offset) * sensor_scaling;

    let behavior = calculate_behavior(
        left_tap.xy,
        right_tap.xy,
        orientation,
        current_rule,
        entity.pos,
        cohort,
    );
    let global_force = calculate_setting(7u, entity.pos, cohort);
    let force =
        behavior.force * global_force / (400.0 * sqrt_world_size);
    let strafe =
        behavior.strafe * global_force / (20.0 * sqrt_world_size);

    entity.color.x = globals.appearance.x * behavior.color.x;
    entity.color.y = 0.8;
    if (globals.modes.w != 0u) {
        entity.color.x = hash2(vec2<f32>(floor(cohort)));
    }
    entity.color.z = 1.0;
    entity.color.w = 0.045;

    entity.vel =
        entity.vel * calculate_setting(4u, entity.pos, cohort) + force;
    entity.pos += entity.vel;
    entity.pos +=
        strafe * calculate_setting(5u, entity.pos, cohort);

    let canvas_aspect = globals.canvas.x / max(globals.canvas.y, 1.0);
    let x_edge = sqrt(canvas_aspect);
    let y_edge = inverseSqrt(canvas_aspect);
    let boundary_mode = globals.sim.w;
    if (boundary_mode == 0u) {
        if (entity.pos.x < -x_edge || entity.pos.x > x_edge) {
            entity.vel.x = -entity.vel.x;
            entity.pos.x = edgeflect(entity.pos.x / x_edge) * x_edge;
        }
        if (entity.pos.y < -y_edge || entity.pos.y > y_edge) {
            entity.vel.y = -entity.vel.y;
            entity.pos.y = edgeflect(entity.pos.y / y_edge) * y_edge;
        }
    } else if (boundary_mode == 1u) {
        if (
            entity.pos.x < -x_edge
            || entity.pos.x > x_edge
            || entity.pos.y < -y_edge
            || entity.pos.y > y_edge
        ) {
            entity_buffer.entities[index] = reset_entity(index);
            return;
        }
    } else {
        entity.pos.x =
            x_edge * 2.0
            * (fract(entity.pos.x / (x_edge * 2.0) - 0.5) - 0.5);
        entity.pos.y =
            y_edge * 2.0
            * (fract(entity.pos.y / (y_edge * 2.0) - 0.5) - 0.5);
    }

    entity_buffer.entities[index] = entity;
}
