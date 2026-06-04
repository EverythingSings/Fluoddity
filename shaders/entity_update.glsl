#version 450
layout(local_size_x = 64) in;

//SAME STRUCT USED IN CAM_BRUSH.VERT AND POINTS_3D.VERT
struct Entity {
    float px, py, pz;    // position (3D)
    float vx, vy, vz;    // velocity (3D)
    float hue;
    float size;
};  // Total: 32 bytes (8 floats)

// Entity accessors — keep physics code readable despite explicit-float layout
vec3 get_pos(Entity e) { return vec3(e.px, e.py, e.pz); }
vec3 get_vel(Entity e) { return vec3(e.vx, e.vy, e.vz); }
void set_pos(inout Entity e, vec3 p) { e.px = p.x; e.py = p.y; e.pz = p.z; }
void set_vel(inout Entity e, vec3 v) { e.vx = v.x; e.vy = v.y; e.vz = v.z; }
struct Rule {
    FourierCenter centers[10];
};
layout(std430, binding = 0) buffer EntityBuffer {
    Entity entities[];
};
layout(std430, binding = 2) buffer RuleBuffer {
    Rule rules[];
};
// SYNCHRONIZED: This struct must match canvas_update_3d.glsl
// Locations to synchronize: shaders/entity_update.glsl, shaders/canvas_update_3d.glsl
struct PhysicsSetting {
    float slider_value;
    float min_value;
    float max_value;
    float x_sweep;      // 0.0 = off, 1.0 = normal sweep, -1.0 = inverse sweep
    float y_sweep;      // 0.0 = off, 1.0 = normal sweep, -1.0 = inverse sweep
    float cohort_sweep; // 0.0 = off, 1.0 = normal sweep, -1.0 = inverse sweep
    float jitter;       // 0.0 = off, higher = more randomness (proportional to result)
};
uniform float WORLD_SIZE;
uniform int frame_count;
uniform Rule target_rule;
uniform sampler3D canvas_3d_x; //trails canvas X channel (R32F, 3D)
uniform sampler3D canvas_3d_y; //trails canvas Y channel (R32F, 3D)
uniform sampler3D canvas_3d_z; //trails canvas Z channel (R32F, 3D)
uniform sampler2D field_texture; // Force/Strafe field (.xy=force, .zw=strafe)
uniform ivec3 canvas_3d_size;  // (W, H, D) for non-cube support
uniform bool advanced_drawing_resources_initialized; // True when field_texture has valid data
uniform float force_field_strength; // Multiplier for force field effects
uniform float strafe_field_strength; // Multiplier for strafe field effects
uniform vec2 canvas_resolution;
uniform PhysicsSetting DRAG_SETTING; 
uniform PhysicsSetting STRAFE_POWER_SETTING;
uniform PhysicsSetting SENSOR_ANGLE_SETTING;
uniform PhysicsSetting GLOBAL_FORCE_MULT_SETTING;
uniform PhysicsSetting SENSOR_DISTANCE_SETTING;
uniform PhysicsSetting AXIAL_FORCE_SETTING;
uniform PhysicsSetting LATERAL_FORCE_SETTING;
uniform PhysicsSetting SENSOR_GAIN_SETTING;
uniform PhysicsSetting MUTATION_SCALE_SETTING;
uniform PhysicsSetting HAZARD_RATE_SETTING;
uniform PhysicsSetting TRAIL_PERSISTENCE_SETTING;
layout(r32f, binding = 0) uniform image3D can_img_x;
layout(r32f, binding = 1) uniform image3D can_img_y;
layout(r32f, binding = 2) uniform image3D can_img_z;
uniform float HUE_SENSITIVITY;
uniform bool COLOR_BY_COHORT;
uniform bool DISABLE_SYMMETRY;
uniform int PLANE_SAMPLES;   // Number of random plane samples per entity per frame (default 1)
uniform bool TESTING_MODE;   // Lock z=0, XY plane only — must reproduce 2D behavior exactly
uniform int ABSOLUTE_ORIENTATION; // 0=Off, 1=Y axis, 2=Radial
uniform float ORIENTATION_MIX; // Blend factor for orientation calculations
uniform int BOUNDARY_CONDITIONS_MODE; //0-1-2 == BOUNCE-RESET-WRAP
uniform int RESET_MODE; //0-1-2 == GRID-RANDOM-RING
uniform int COHORTS; //each cohort gets its own rule and starting location
uniform float RULE_SEED;
uniform bool WRITE_RULES; // Set true for one frame when rule buffer readback is needed
uniform vec4 generic03;
uniform vec4 generic47;

// Multi-load control uniforms (small, stay as uniforms)
uniform int MULTILOAD_COUNT; // Number of loaded configs (0 = normal mode)
uniform float MULTI_LOAD_CURRENT_PROGRESS; // Current position in config ring (0-1)
uniform float MULTI_LOAD_SIMULTANEOUS_CONFIGS; // How many configs to span
uniform int MULTI_LOAD_ASSIGNMENT_MODE; // 0 = Cohorts, 1 = Random
uniform bool MULTI_LOAD_PER_CONFIG_INITIAL_CONDITIONS; // If true, use per-config reset modes
uniform bool MULTI_LOAD_PER_CONFIG_COHORTS; // If true, use per-config cohort counts
uniform bool MULTI_LOAD_PER_CONFIG_HAZARD_RATE; // If true, use per-config hazard rates

// Multi-load config data (large arrays, packed into SSBO)
struct MultiLoadConfig {
    // Physics parameters as PhysicsSetting structs (10 params * 6 floats = 60 floats)
    PhysicsSetting axial_force;
    PhysicsSetting lateral_force;
    PhysicsSetting sensor_gain;
    PhysicsSetting mutation_scale;
    PhysicsSetting drag;
    PhysicsSetting strafe_power;
    PhysicsSetting sensor_angle;
    PhysicsSetting global_force_mult;
    PhysicsSetting sensor_distance;
    PhysicsSetting hazard_rate;

    // Simulation settings (6 ints)
    int disable_symmetry;      // bool as int for alignment
    int absolute_orientation;  // 0=Off, 1=Y axis, 2=Radial
    int boundary_conditions;
    int reset_mode;
    int cohorts;
    int color_by_cohort;       // bool as int for alignment

    // Appearance and orientation mix (3 floats)
    float hue_sensitivity;
    float orientation_mix;
    float rule_seed;
};

layout(std430, binding = 3) buffer MultiLoadConfigBuffer {
    MultiLoadConfig configs[64];
};

// Multi-load target rules (separate buffer for cleaner organization)
layout(std430, binding = 4) buffer MultiLoadRuleBuffer {
    Rule target_rules[64];
};

// Histogram reporting SSBO
layout(std430, binding = 5) buffer ReportsBuffer {
    uvec4 reports[];
};
uniform vec4 hist_min;
uniform vec4 hist_max;
uniform uint bucket_count;
uniform uvec4 plot_mode;

void report(float val, uint plot_num) {
    uint ch = plot_num % 4u;
    if (plot_mode[ch] == 0u) return;
    float lo = hist_min[ch];
    float hi = hist_max[ch];
    float t = clamp((val - lo) / (hi - lo), 0.0, 1.0);
    uint bucket_idx = min(uint(t * float(bucket_count)), bucket_count - 1u);
    atomicAdd(reports[bucket_idx][ch], 1u);
}

////////////////////////////CONSTANTS
#define PI 3.1415926
#define ACTIVE_COUNT 4000000//(600000*WORLD_SIZE) //Supports up to the size of the entity buffer.
#define SQRT_WORLD_SIZE (sqrt(WORLD_SIZE))
// Multi-load helper: Calculate which config index this particle should use
int get_particle_config_index() {
    if (MULTILOAD_COUNT == 0) return -1; // Not in multi-load mode

    // Calculate normalized index (0 to 1) for this particle
    float normalized_index = float(gl_GlobalInvocationID.x) / float(ACTIVE_COUNT);

    // For "Random" assignment mode, hash the normalized_index for stable pseudo-random assignment
    if (MULTI_LOAD_ASSIGNMENT_MODE == 1) {
        normalized_index = hash(vec2(normalized_index, 0.0));
    }

    // Calculate config index using circular ring formula
    // If SIMULTANEOUS_CONFIGS == 2, span across 2 full indices as normalized_index sweeps 0 to 1
    float offset = MULTI_LOAD_SIMULTANEOUS_CONFIGS / float(MULTILOAD_COUNT) * normalized_index;
    float ring_position = fract(MULTI_LOAD_CURRENT_PROGRESS + offset);
    int config_index = int(floor(float(MULTILOAD_COUNT) * ring_position));

    // Clamp to valid range
    return clamp(config_index, 0, MULTILOAD_COUNT - 1);
}
                            //Entities with index > ACTIVE_COUNT aren't rendered or updated
int get_particle_cohorts() {
    int idx = get_particle_config_index();
    // Use per-config value only if multi-load is active AND per-config checkbox is enabled
    if (idx >= 0 && MULTI_LOAD_PER_CONFIG_COHORTS) {
        return configs[idx].cohorts;
    }
    return COHORTS;
}
//Calculate the actual setting value for this particle. When sweeps are
//active, physics settings can depend on entity position and cohort
// SYNCHRONIZED: This function must match canvas_update_3d.glsl and sim.py::calculate_setting
// Locations to synchronize: shaders/entity_update.glsl, shaders/canvas_update_3d.glsl, sim.py
float calculate_setting(PhysicsSetting setting, vec2 pos, float cohort){
    //if no sweep modes are active and no jitter, just return slider value
    if(setting.y_sweep == 0.0 && setting.cohort_sweep == 0.0 && setting.x_sweep == 0.0 && setting.jitter == 0.0)
        {return setting.slider_value;}
    //otherwise calculate parameter sweeps
    pos = (pos+1)/2.;//convert to 0..1 for use as a mix coefficient
    cohort = floor(cohort) / float(get_particle_cohorts()); //convert to 0..1 for mixing

    // Count active sweeps and accumulate results
    float result = 0;
    int active_sweeps = 0;
    if(setting.x_sweep != 0.0) {
        // For inverse sweep (x_sweep < 0), swap min and max
        if(setting.x_sweep > 0.0) {
            result += mix(setting.min_value, setting.max_value, pos.x);
        } else {
            result += mix(setting.max_value, setting.min_value, pos.x);
        }
        active_sweeps++;
    }
    if(setting.y_sweep != 0.0) {
        // For inverse sweep (y_sweep < 0), swap min and max
        if(setting.y_sweep > 0.0) {
            result += mix(setting.min_value, setting.max_value, pos.y);
        } else {
            result += mix(setting.max_value, setting.min_value, pos.y);
        }
        active_sweeps++;
    }
    if(setting.cohort_sweep != 0.0) {
        // For inverse sweep (cohort_sweep < 0), swap min and max
        if(setting.cohort_sweep > 0.0) {
            result += mix(setting.min_value, setting.max_value, cohort);
        } else {
            result += mix(setting.max_value, setting.min_value, cohort);
        }
        active_sweeps++;
    }

    // Average the results or use slider_value if no sweeps
    result = active_sweeps > 0 ? result / float(active_sweeps) : setting.slider_value;

    // Apply jitter: random variation proportional to the result value
    // hash() returns 0..1, so (hash(...)*2.-1.) returns -1..1
    if(setting.jitter != 0.0) {
        float random = hash(vec2(float(frame_count)+result, pos.x + pos.y * 1000.0)) * 2.0 - 1.0;
        result += setting.jitter * result * random;
    }

    return result;
}



// Helper functions to get config values (return array value if multi-load, else single uniform)

PhysicsSetting get_particle_axial_force() {
    int idx = get_particle_config_index();
    return idx >= 0 ? configs[idx].axial_force : AXIAL_FORCE_SETTING;
}

PhysicsSetting get_particle_lateral_force() {
    int idx = get_particle_config_index();
    return idx >= 0 ? configs[idx].lateral_force : LATERAL_FORCE_SETTING;
}

PhysicsSetting get_particle_sensor_gain() {
    int idx = get_particle_config_index();
    return idx >= 0 ? configs[idx].sensor_gain : SENSOR_GAIN_SETTING;
}

PhysicsSetting get_particle_mutation_scale() {
    int idx = get_particle_config_index();
    return idx >= 0 ? configs[idx].mutation_scale : MUTATION_SCALE_SETTING;
}

PhysicsSetting get_particle_drag() {
    int idx = get_particle_config_index();
    return idx >= 0 ? configs[idx].drag : DRAG_SETTING;
}

PhysicsSetting get_particle_strafe_power() {
    int idx = get_particle_config_index();
    return idx >= 0 ? configs[idx].strafe_power : STRAFE_POWER_SETTING;
}

PhysicsSetting get_particle_sensor_angle() {
    int idx = get_particle_config_index();
    return idx >= 0 ? configs[idx].sensor_angle : SENSOR_ANGLE_SETTING;
}

PhysicsSetting get_particle_global_force_mult() {
    int idx = get_particle_config_index();
    return idx >= 0 ? configs[idx].global_force_mult : GLOBAL_FORCE_MULT_SETTING;
}

PhysicsSetting get_particle_sensor_distance() {
    int idx = get_particle_config_index();
    return idx >= 0 ? configs[idx].sensor_distance : SENSOR_DISTANCE_SETTING;
}

bool get_particle_disable_symmetry() {
    int idx = get_particle_config_index();
    return idx >= 0 ? bool(configs[idx].disable_symmetry) : DISABLE_SYMMETRY;
}

int get_particle_absolute_orientation() {
    int idx = get_particle_config_index();
    return idx >= 0 ? int(configs[idx].absolute_orientation) : ABSOLUTE_ORIENTATION;
}
PhysicsSetting get_particle_hazard_rate() {
    int idx = get_particle_config_index();
    return idx >= 0 &&MULTI_LOAD_PER_CONFIG_HAZARD_RATE? (configs[idx].hazard_rate) : HAZARD_RATE_SETTING;
}

//HARDCODED TO BE GLOBAL FOR NOW
int get_particle_boundary_conditions() {
    //int idx = get_particle_config_index();
    //return idx >= 0 ? configs[idx].boundary_conditions : BOUNDARY_CONDITIONS_MODE;
    return BOUNDARY_CONDITIONS_MODE;
}

int get_particle_reset_mode() {
    int idx = get_particle_config_index();
    // Use per-config value only if multi-load is active AND per-config checkbox is enabled
    if (idx >= 0 && MULTI_LOAD_PER_CONFIG_INITIAL_CONDITIONS) {
        return configs[idx].reset_mode;
    }
    return RESET_MODE;
}


//HARDCODED TO BE GLOBAL FOR NOW
float get_particle_hue_sensitivity() {
    //int idx = get_particle_config_index();
    //return idx >= 0 ? configs[idx].hue_sensitivity : HUE_SENSITIVITY;
    return HUE_SENSITIVITY;
}

//HARDCODED TO BE GLOBAL FOR NOW
bool get_particle_color_by_cohort() {
    //int idx = get_particle_config_index();
    //return idx >= 0 ? bool(configs[idx].color_by_cohort) : COLOR_BY_COHORT;
    return COLOR_BY_COHORT;
}

float get_particle_rule_seed() {
    int idx = get_particle_config_index();
    return idx >= 0 ? configs[idx].rule_seed : RULE_SEED;
}

Rule get_particle_target_rule() {
    int idx = get_particle_config_index();
    return idx >= 0 ? target_rules[idx] : target_rule;
}


////////////////////////////////////
//FOURIER NOISE IS IMPORTED INTO THIS SHADER
//FROM fourier4_4.glsl
////////////////////////////////////

//rotate p around origin by angle a
void pR(inout vec2 p, float a) {
	p = cos(a)*p + sin(a)*vec2(p.y, -p.x);
}


//convert p (entity space, 3D) to texture coords and retrieve 3-component canvas
vec3 get_can_3d(vec3 p){
    float ca = float(canvas_3d_size.x) / float(canvas_3d_size.y);
    vec2 half_extent = vec2(sqrt(ca), 1.0 / sqrt(ca));
    vec2 uv_xy = p.xy / (2.0 * half_extent) + 0.5;
    // Z maps from [-1,1] to [0,1] (or [-z_edge,z_edge] once we have proper 3D bounds)
    float uv_z = p.z * 0.5 + 0.5;
    if(get_particle_boundary_conditions() == 2) {
        uv_xy = fract(uv_xy);
        uv_z = fract(uv_z);
    }
    // When canvas_3d_size.z == 1, uv_z is clamped to center of single slice
    if(canvas_3d_size.z <= 1) uv_z = 0.5;
    vec3 uvw = vec3(uv_xy, uv_z);
    return vec3(texture(canvas_3d_x, uvw).r, texture(canvas_3d_y, uvw).r, texture(canvas_3d_z, uvw).r);
}
vec4 get_field(vec2 p){
    if(!advanced_drawing_resources_initialized)return vec4(0);
    vec2 res=textureSize(field_texture,0);
    float ca = res.x / res.y;
    vec2 half_extent = vec2(sqrt(ca), 1.0 / sqrt(ca));
    vec2 uv = p / (2.0 * half_extent) + 0.5;
    if(get_particle_boundary_conditions() == 2) uv = fract(uv);
    return texture(field_texture, uv);
}

vec2 safenorm(vec2 p){
    return length(p)==0?vec2(0):normalize(p);
}
vec3 safenorm3(vec3 p){
    return length(p)==0?vec3(0):normalize(p);
}

void build_tangent_plane(
    vec3 vel,
    float theta,
    out vec3 u,
    out vec3 v
) {
    // Forward direction
    u = normalize(vel);

    // Pick something not parallel to u
    vec3 arbitrary =
        abs(u.x) < 0.9
        ? vec3(1,0,0)
        : vec3(0,1,0);

    // First perpendicular direction
    vec3 t1 = normalize(cross(u, arbitrary));

    // Second perpendicular direction
    vec3 t2 = cross(u, t1);

    // Random perpendicular vector around u
    v = cos(theta) * t1 + sin(theta) * t2;
}


float get_cohort(uint index) {
    return float(get_particle_cohorts()) * float(index) / float(ACTIVE_COUNT);
}

//Return all entities to their initialization state
void reset(uint index){

    float size=index<ACTIVE_COUNT?.0015/SQRT_WORLD_SIZE: 0;
    float cohort_val = get_cohort(index);
    float aspect = sqrt(canvas_resolution.x/canvas_resolution.y);

    //set pos and vel to random values on a small ball (3D)
    float cohort_scale = 0.019;//Size of each cluster
    vec3 pos=cohort_scale*vec3(hash(vec2(cohort_val)),hash(vec2(cohort_val+index+2.142)),hash(vec2(cohort_val+index+7.531)));
    vec3 vel=.00005*(vec3(hash(vec2(cohort_val,index)),hash(vec2(cohort_val,pos.y)),hash(vec2(index,pos.z+3.77)))*2-1);

    //RESET_MODE: 0=Grid, 1=Random, 2=Ring/Sphere
    int reset_mode = get_particle_reset_mode();
    int cohorts = get_particle_cohorts();
    if(reset_mode == 0) {
        //GRID: position cohorts in a centered 3D grid (next-largest cube with gaps)
        int grid_side = int(ceil(pow(float(cohorts), 1.0/3.0)));
        int total_slots = grid_side * grid_side * grid_side;
        // Center the filled slots within the cube: skip (total_slots - cohorts)/2 at the start
        int offset = (total_slots - cohorts) / 2;
        int slot = int(cohort_val) + offset;
        int gx = slot % grid_side;
        int gy = (slot / grid_side) % grid_side;
        int gz = slot / (grid_side * grid_side);
        // Map grid cell to [-0.9, 0.9] centered (equal spacing in all axes)
        pos += 1.8 * ((vec3(gx, gy, gz) + 0.5) / float(grid_side) - 0.5);
    }
    else if(reset_mode == 1) {
        //RANDOM: rejection-sample from the sphere inscribing the unit cube
        vec3 candidate;
        float seed_offset = 0.0;
        for (int attempt = 0; attempt < 16; attempt++) {
            candidate = vec3(
                hash(vec2(cohort_val, 1.0 + seed_offset)),
                hash(vec2(cohort_val, 2.0 + seed_offset)),
                hash(vec2(cohort_val, 3.0 + seed_offset))
            ) * 2.0 - 1.0;
            if (dot(candidate, candidate) <= 1.0) break;
            seed_offset += 3.0;
        }
        pos = candidate;
    }
    else if(reset_mode == 2) {
        //SPHERE: arrange cohorts on a spherical shell
        float phi = hash(vec2(cohort_val, 4.0)) * 2.0 * PI;
        float cos_theta = hash(vec2(cohort_val, 5.0)) * 2.0 - 1.0;
        float sin_theta = sqrt(1.0 - cos_theta * cos_theta);
        float radius = 0.5;
        pos = .5*vec3(sin_theta * cos(phi), sin_theta * sin(phi), cos_theta) * radius;
    }


    //store to persistent entity buffer
    entities[index]=Entity(pos.x, pos.y, pos.z, vel.x, vel.y, vel.z, 0.0, size);
}

//randomly change noise function parameters, scaled by parameter amount. 
//Each cohort gets a unique mutation for any given rule
void mutate_rule(inout Rule current_rule,float amount,float cohort){
    float seed = hash(current_rule.centers[4].frequency.xy+current_rule.centers[7].amplitude.yx+current_rule.centers[1].frequency.zw)+cohort;

    for(int i = 0; i < 10; i++) {
        vec4 amp_mutation = amount * (-1.0 + 2.0 * hash4(-.5+vec2(-i+seed,i)));
        current_rule.centers[i].amplitude += amp_mutation;
        current_rule.centers[i].frequency *= 1 + amount * 0.5 * (hash(vec2(seed,i))-.5);
    }
}


//Used to enforce left-right symmetry in the local coordinates vec2(forward, left)
vec2 y_reflect(vec2 p){
    return p*vec2(1,-1);
}
vec2 x_reflect(vec2 p){
    return p*vec2(-1,1);
}
//reflect across the boundary [-1,1] to keep particle positions from leaving the canvas
float edgeflect(float x){
    return sign(x)*(1-abs(1-abs(x)));
}

//Somewhat arbitrary generator of functions with 4 float inputs and 4 float outputs,
//varying rule should smoothly change the behavior of the function
vec4 black_box(vec2 L,vec2 R,Rule rule){
    return (fourier_noise(rule.centers, vec4(L,R)));
}



//This function determines entity output by plugging sensor values into a noise function called black_box()
//The calculation is performed twice, once in mirrored coordinates, and the two values are averaged.
//This keeps entities from displaying clockwise/counterclockwise bias.
//PARAMETERS:
//--L and R: velocity field measurements from left sensor and right sensor.
//--axis: forward vector that defines our orientation.
//--rule: coefficients for the noise function that dictates entity behavior.
//--pos: entity position (for parameter sweeps)
//--cohort: entity cohort (for parameter sweeps)
//RETURNS:
//--force: A "push" vector that will be added to entity.vel
//--strafe: A "hop" vector that will be added to entity.pos and have no effect on velocity
//--color: vec2 to be used as parameters in a coloring function
void calculate_entity_behavior( vec2 L,vec2 R, vec2 axis, Rule rule, vec2 pos, float cohort, out vec2 force, out vec2 strafe, out vec2 color){

    //build a local coordinate frame where "axis" is forward.
    vec2 forward=safenorm(axis);
    vec2 left=vec2(forward.y,-forward.x);

    //Convert L and R to local coordinates.
    //Ie. decompose each into an axial component and a lateral component
    L=vec2(dot(L,forward),dot(L,left));
    R=vec2(dot(R,forward),dot(R,left));

    //calculate black box noise values
    vec4 baseterm= black_box(L,R,rule);
    vec4 mirrorterm=black_box(y_reflect(R),y_reflect(L),rule);
    if(DISABLE_SYMMETRY){mirrorterm = vec4(0);}//disable symmetry by zeroing the mirror term

    //Combine base and mirror terms
    force = baseterm.xy+y_reflect(mirrorterm.xy);
    strafe = baseterm.zw + y_reflect(mirrorterm.zw);

    //Convert force and strafe back to world coordinates
    force=forward*force.x*calculate_setting(get_particle_axial_force(),pos,cohort)+left*force.y*calculate_setting(get_particle_lateral_force(),pos,cohort);
    strafe = forward*strafe.x*calculate_setting(get_particle_axial_force(),pos,cohort) + left * strafe.y * calculate_setting(get_particle_lateral_force(),pos,cohort);

    color = baseterm.xy+(mirrorterm.xy); //Just an arbitrary function of blackbox output. Reuses force terms.
    return;
}
// Run one sample of the 2D physics projected onto a random tangent plane.
// Returns force and strafe in 3D world coordinates.
void sample_plane_physics(
    inout vec3 force_accum, inout vec3 strafe_accum, inout vec2 col_accum,
    vec3 pos, vec3 vel, Rule current_rule, float cohort,
    int sample_index, vec2 epos2
) {
    vec3 vel_dir;
    if (length(vel) > 1e-10) {
        vel_dir = normalize(vel);
    } else {
        // Deterministic random direction per-particle to avoid axis bias
        float idx_f = float(gl_GlobalInvocationID.x);
        float phi = hash(vec2(idx_f, 1.0)) * 2.0 * PI;
        float cos_theta = hash(vec2(idx_f, 2.0)) * 2.0 - 1.0;
        float sin_theta = sqrt(1.0 - cos_theta * cos_theta);
        vel_dir = vec3(sin_theta * cos(phi), sin_theta * sin(phi), cos_theta);
    }

    vec3 u, v; // Tangent plane basis vectors

    if (TESTING_MODE) {
        // Always use XY plane: u = (1,0,0), v = (0,1,0)
        u = vec3(1,0,0);
        v = vec3(0,1,0);
    } else {
        // Random angle for this sample
        float theta = hash(vec2(
            float(frame_count) + float(gl_GlobalInvocationID.x) / float(ACTIVE_COUNT),
            float(sample_index)
        )) * 2.0 * PI;
        build_tangent_plane(vel_dir, theta, u, v);
    }

    // Calculate sensor distance
    float sample_dist = 1./SQRT_WORLD_SIZE*.005 * calculate_setting(get_particle_sensor_distance(), epos2, cohort);

    // In 3D, the tangent plane is perpendicular to vel_dir, so projecting
    // velocity onto it yields zero. Instead, use u as forward direction —
    // theta already randomizes which direction u points within the plane.
    vec2 orientation;
    if (TESTING_MODE) {
        // 2D mode: velocity lies in the XY plane, project normally
        orientation = safenorm(vec2(dot(vel, u), dot(vel, v)));
    } else {
        // 3D mode: use tangent plane basis directly (randomized by theta)
        orientation = vec2(1, 0);
    }

    // Absolute orientation modes (project reference directions onto plane)
    int ORIENTATION_MODE = get_particle_absolute_orientation();
    float mix_amt = min(1, ORIENTATION_MODE) * ORIENTATION_MIX;
    if (ORIENTATION_MODE == 1) {
        // Y-axis orientation: project (0,1,0) onto the plane
        vec2 y_axis_on_plane = vec2(dot(vec3(0,1,0), u), dot(vec3(0,1,0), v));
        orientation = mix(orientation, safenorm(y_axis_on_plane), mix_amt);
    } else if (ORIENTATION_MODE == 2) {
        // Radial orientation: project -normalize(pos) onto the plane
        vec3 radial = -safenorm3(pos);
        vec2 radial_on_plane = vec2(dot(radial, u), dot(radial, v));
        orientation = mix(orientation, safenorm(radial_on_plane), mix_amt);
    }

    // Sensor offsets in 2D plane coordinates, then lifted to 3D
    vec2 left_offset_2d = orientation * sample_dist;
    vec2 right_offset_2d = orientation * sample_dist;
    float sensor_angle = calculate_setting(get_particle_sensor_angle(), epos2, cohort) * PI;
    pR(left_offset_2d, sensor_angle);
    pR(right_offset_2d, -sensor_angle);

    // Convert 2D plane offsets to 3D world offsets
    vec3 left_offset_3d = left_offset_2d.x * u + left_offset_2d.y * v;
    vec3 right_offset_3d = right_offset_2d.x * u + right_offset_2d.y * v;

    // Read 3D canvas at sensor positions
    vec3 ltap_3d = get_can_3d(pos + left_offset_3d);
    vec3 rtap_3d = get_can_3d(pos + right_offset_3d);

    // Project 3D trail vectors onto the 2D plane
    vec2 ltap = vec2(dot(ltap_3d, u), dot(ltap_3d, v));
    vec2 rtap = vec2(dot(rtap_3d, u), dot(rtap_3d, v));

    // Rescale sensor values
    float sensor_scaling = SQRT_WORLD_SIZE * 38.855 * calculate_setting(get_particle_sensor_gain(), epos2, cohort);
    ltap *= sensor_scaling;
    rtap *= sensor_scaling;

    // Run the existing 2D physics on the plane
    vec2 force_2d = vec2(0);
    vec2 strafe_2d = vec2(0);
    vec2 col_params = vec2(0);
    calculate_entity_behavior(ltap, rtap, orientation, current_rule, epos2, cohort, force_2d, strafe_2d, col_params);

    // Rescale output forces (same as current 2D code)
    float gfm = 1./SQRT_WORLD_SIZE * calculate_setting(get_particle_global_force_mult(), epos2, cohort);
    force_2d *= gfm / 400.;
    strafe_2d *= gfm / 20.;

    // Convert 2D force/strafe back to 3D world coordinates
    vec3 force_3d = force_2d.x * u + force_2d.y * v;
    vec3 strafe_3d = strafe_2d.x * u + strafe_2d.y * v;

    force_accum += force_3d;
    strafe_accum += strafe_3d;
    col_accum += col_params;
}
void main() {
    uint index = gl_GlobalInvocationID.x;
    if (index >= ENTITY_COUNT) return;

    // Inactive entities get zeroed out. Position offscreen so they don't accidentally get clicked on
    if (index >= ACTIVE_COUNT) {
        entities[index] = Entity(10000.0, 10000.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0);
        return;
    }
    Entity e=entities[index];
    float cohort = get_cohort(index);

    Rule current_rule=get_particle_target_rule();
    //if a few arbitrary coefficients are exactly 0, then assume target_rule is all 0s (no target) and generate a random rule instead.
    if(current_rule.centers[0].frequency==vec4(0) && current_rule.centers[5].amplitude==vec4(0)){
        current_rule = Rule(generate_random_centers(get_particle_rule_seed()+floor(cohort)));
    }
    //Each cohort gets a random mutation
    mutate_rule(current_rule,calculate_setting(get_particle_mutation_scale(),vec2(e.px,e.py),cohort),get_particle_rule_seed()+floor(cohort));
    // Only write rules when explicitly requested (expensive - 320 bytes per particle)
    if(WRITE_RULES) {
        rules[index] = current_rule;
    }
    
    //frame_count == 0 signals a simulation reset
    vec2 epos2 = vec2(e.px, e.py); // 2D position for parameter sweeps
    if (frame_count==0||calculate_setting(get_particle_hazard_rate(),epos2,cohort)>hash(vec2(float(index)/float(ACTIVE_COUNT),frame_count))){reset(index);return;}



    //Monte Carlo plane sampling: sample PLANE_SAMPLES random tangent planes,
    //run 2D physics on each, and average the resulting 3D forces.
    vec3 pos3 = get_pos(e);
    vec3 vel3 = get_vel(e);
    vec3 force_accum = vec3(0);
    vec3 strafe_accum = vec3(0);
    vec2 col_accum = vec2(0);
    int num_samples = max(1, PLANE_SAMPLES);
    for (int s = 0; s < num_samples; s++) {
        sample_plane_physics(force_accum, strafe_accum, col_accum,
                             pos3, vel3, current_rule, cohort, s, epos2);
    }
    vec3 force3 = force_accum / float(num_samples);
    vec3 strafe3 = strafe_accum / float(num_samples);
    vec2 col_params = col_accum / float(num_samples);

    if(index%500==0){report(length(col_params),0);}//small sample

    //Set entity hue (saturation/brightness/alpha are computed in vertex shaders)
    e.hue = get_particle_hue_sensitivity()*col_params.x;
    e.size = 0.00015;
    if(!(abs(col_params.x-generic03.x*15)<generic03.y*5)){e.size=.0;}
    if(get_particle_color_by_cohort()) {e.hue = hash(vec2(floor(cohort)));}

    //Accelerate: Apply drag and add force to e.vel (now 3D)
    float drag = calculate_setting(get_particle_drag(),epos2,cohort);
    e.vx = e.vx*drag + force3.x;
    e.vy = e.vy*drag + force3.y;
    e.vz = e.vz*drag + force3.z;

    //Move: add e.vel and strafe to e.pos (now 3D)
    float strafe_power = calculate_setting(get_particle_strafe_power(),epos2,cohort);
    e.px += e.vx + strafe3.x*strafe_power;
    e.py += e.vy + strafe3.y*strafe_power;
    e.pz += e.vz + strafe3.z*strafe_power;

    //TESTING_MODE: clamp z to 0
    if (TESTING_MODE) {
        e.pz = 0.0;
        e.vz = 0.0;
    }

    //ADVANCED DRAWING force / strafe (still 2D, applied to XY only)
    vec4 draw_sample =get_field(vec2(e.px, e.py));
    e.vx += .01*force_field_strength*draw_sample.x;
    e.vy += .01*force_field_strength*draw_sample.y;
    e.px += .01*strafe_field_strength*draw_sample.z;
    e.py += .01*strafe_field_strength*draw_sample.w;
    vec3 sp = vec3(e.px,e.py,e.pz);
    vec3 n = scene(sp).x*-.01*sdf_normal(sp);
    //e.px+=n.x;
    //e.py+=n.y;
    //e.pz+=n.z;
    //BOUNDARY_CONDITIONS_MODE:  0-1-2 == BOUNCE-RESET-WRAP
    float ca = canvas_resolution.x / canvas_resolution.y;
    float x_edge = sqrt(ca);
    float y_edge = 1.0 / sqrt(ca);
    float z_edge = 1.0; // Z always spans [-1, 1] for now
    int boundary_mode = get_particle_boundary_conditions();
    if(boundary_mode==0){
        //reflect particles off canvas boundaries
        if (e.px < -x_edge || e.px > x_edge){
            e.vx=-e.vx;
            e.px=edgeflect(e.px/x_edge)*x_edge;
        }
        if (e.py < -y_edge || e.py > y_edge){
            e.vy=-e.vy;
            e.py=edgeflect(e.py/y_edge)*y_edge;
        }
        if (!TESTING_MODE && canvas_3d_size.z > 1) {
            if (e.pz < -z_edge || e.pz > z_edge){
                e.vz=-e.vz;
                e.pz=edgeflect(e.pz/z_edge)*z_edge;
            }
        }
    }
    else if(boundary_mode==1){
        //reset to initial conditions
        bool out_xy = e.px<-x_edge||e.px>x_edge||e.py<-y_edge||e.py>y_edge;
        bool out_z = !TESTING_MODE && canvas_3d_size.z > 1 && (e.pz < -z_edge || e.pz > z_edge);
        if(out_xy || out_z){
            reset(index);
            return;//reset expects to be the last thing we do. It handles entity buffer storage
        }
    }
    else if(boundary_mode==2){
        //wrap: X wraps [-x_edge,x_edge], Y wraps [-y_edge, y_edge]
        e.px = x_edge * 2.0 * (fract(e.px / (x_edge * 2.0) - 0.5) - 0.5);
        e.py = y_edge * 2.0 * (fract(e.py / (y_edge * 2.0) - 0.5) - 0.5);
        if (!TESTING_MODE && canvas_3d_size.z > 1) {
            e.pz = z_edge * 2.0 * (fract(e.pz / (z_edge * 2.0) - 0.5) - 0.5);
        }
    }

    //Atomic splat to canvas: scale by (1-p)/p so canvas_update's *p gives net (1-p)*splat
    float trail_p = calculate_setting(TRAIL_PERSISTENCE_SETTING, vec2(e.px, e.py), cohort);
    trail_p = clamp(trail_p, 0.001, 0.999);
    float splat_scale = (1.0 - trail_p) / trail_p;

    ivec3 img_res_3d = imageSize(can_img_x);
    vec2 half_ext = vec2(sqrt(ca), 1.0 / sqrt(ca));
    vec2 uv_xy = vec2(e.px, e.py) / (2.0 * half_ext) + 0.5;
    float uv_z = e.pz * 0.5 + 0.5;
    // When depth is 1, always splat to z=0
    int voxel_z = (img_res_3d.z <= 1) ? 0 : int(uv_z * float(img_res_3d.z));
    ivec3 voxel = ivec3(ivec2(uv_xy * vec2(img_res_3d.xy)), voxel_z);

    if (voxel.x >= 0 && voxel.x < img_res_3d.x &&
        voxel.y >= 0 && voxel.y < img_res_3d.y &&
        voxel.z >= 0 && voxel.z < img_res_3d.z) {
        imageAtomicAdd(can_img_x, voxel, splat_scale * e.vx);
        imageAtomicAdd(can_img_y, voxel, splat_scale * e.vy);
        imageAtomicAdd(can_img_z, voxel, splat_scale * e.vz);
    }

    //Commit new entity state to buffers
    entities[index]=e;


}
