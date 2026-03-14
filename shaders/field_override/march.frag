#version 150

uniform int frame_count;
uniform vec2 canvas_resolution;

// Camera (vector-based, arbitrary orientation)
uniform vec3 u_cam;
uniform vec3 u_view_dir;
uniform vec3 u_up_dir;

// Contraction map (fixed point at origin)
uniform float u_scale;               // Contraction ratio (0 < s < 1)
uniform mat3  u_rotation;            // Rotation per recursion level
uniform float u_cell_radius;         // Radius of the fundamental spherical cell

// Transition / scale
uniform float u_worldScale;          // Current world scale (1.0 at cell edge, u_scale at inner edge)

// Accumulated orientation: maps Base-local directions back to the original
// world frame.  Keeps sun, sky, etc. consistent across cell transitions.
uniform mat3  u_world_orientation;

uniform vec3 sim_offset;

// Generic scratch uniforms (for live-coding)
uniform vec4 generic03;
uniform vec4 generic47;

// Legacy uniforms (kept for compatibility with other override shaders)
uniform vec3 camera_pos;
uniform vec3 camera_dir;

#define MAX_STEPS 2000
#define HIT_DISTANCE 2e-3
#define MAX_DISTANCE 100.0
#define FOCAL_LENGTH 2.2
#define AO_STEPS 10
#define AO_DIST (.1*(length(r.ori+r.dir*r.extent))/u_worldScale)
#define AO_POW .60
#define SHADOW_STEPS 256
#define SHADOW_SMOOTH 38.0

#define SUN_DIR spiral_axis()
#define SUN_COL 3.0*vec3(0.9, 0.8, 0.7)
#define SKY_COL 5.0*vec3(.04,.15,.3)
#define FOG_COL vec3(.0)
#define FOG_AMT .051

#define PI 3.14159

in vec2 texcoord;

struct Ray
{
    vec3 ori;
    vec3 dir;
    float extent;
    vec3 norm;
};

struct MR
{
    float dts;
    vec4 mat;
};

MR mapMin(MR a, MR b){
    return a.dts < b.dts ? a : b;
}

vec3 hsv2rgb(vec3 c)
{
    vec4 K = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);
    vec3 p = abs(fract(c.xxx + K.xyz) * 6.0 - K.www);
    return c.z * mix(K.xxx, clamp(p - K.xxx, 0.0, 1.0), c.y);
}

void pR(inout vec2 p, float a) {
    p = cos(a)*p + sin(a)*vec2(p.y, -p.x);
}

float sdBox(vec3 p, vec3 b)
{
    vec3 q = abs(p) - b;
    return length(max(q, 0.0)) + min(max(q.x, max(q.y, q.z)), 0.0);
}

float sdBoxFrame( vec3 p, vec3 b, float e )
{
       p = abs(p  )-b;
  vec3 q = abs(p+e)-e;
  return min(min(
      length(max(vec3(p.x,q.y,q.z),0.0))+min(max(p.x,max(q.y,q.z)),0.0),
      length(max(vec3(q.x,p.y,q.z),0.0))+min(max(q.x,max(p.y,q.z)),0.0)),
      length(max(vec3(q.x,q.y,p.z),0.0))+min(max(q.x,max(q.y,p.z)),0.0));
}

// ---------------------------------------------------------------------------
// Canonical SDF -- user-defined scene geometry within the fundamental region.
// Replace this stub with your own scene.
// ---------------------------------------------------------------------------
MR sdf(vec3 p) {
    return MR(sdBoxFrame(p, vec3(1), .1), vec4(0));
}

// ---------------------------------------------------------------------------
// Three-cell map: evaluates sdf() at Base, Micro, and Macro scales.
// No recursion -- the illusion of infinite depth comes from camera teleportation.
//
// The contraction map is simply: p -> R * p / scale  (fixed point at origin).
//
// Extra cells: #define EXTRA_MICRO_CELLS N and/or EXTRA_MACRO_CELLS N
// to render N additional cells beyond the default one at each end.
// ---------------------------------------------------------------------------
#define EXTRA_MICRO_CELLS 1

MR map(vec3 p) {
    // Base: evaluate at current coordinates
    MR d = sdf(p);

    #ifndef NO_RECURSION
    // --- Micro chain (zoom in) -----------------------------------------------
    vec3  pMicro = u_rotation * p / u_scale;
    float microCorr = u_scale;
    MR mMicro = sdf(pMicro);
    mMicro.dts *= microCorr;
    d = mapMin(d, mMicro);

    #ifdef EXTRA_MICRO_CELLS
        for (int i = 0; i < EXTRA_MICRO_CELLS; i++) {
            pMicro    = u_rotation * pMicro / u_scale;
            microCorr *= u_scale;
            mMicro     = sdf(pMicro);
            mMicro.dts *= microCorr;
            d = mapMin(d, mMicro);
        }
    #endif

    // --- Macro chain (zoom out) ----------------------------------------------
    mat3  rot_inv  = transpose(u_rotation);
    vec3  pMacro   = u_scale * (rot_inv * p);
    float macroCorr = u_scale;
    MR mMacro = sdf(pMacro);
    mMacro.dts /= macroCorr;
    d = mapMin(d, mMacro);

    #ifdef EXTRA_MACRO_CELLS
        for (int i = 0; i < EXTRA_MACRO_CELLS; i++) {
            pMacro    = u_scale * (rot_inv * pMacro);
            macroCorr *= u_scale;
            mMacro     = sdf(pMacro);
            mMacro.dts /= macroCorr;
            d = mapMin(d, mMacro);
        }
    #endif

    #ifdef CELL_OVERLAY
        d = mapMin(d, MR(length(p) - u_cell_radius, vec4(0)));
    #endif
    #endif // NO_RECURSION

    return d;
}

vec3 spiral_axis() {
    // Extract rotation axis from u_rotation (eigenvector with eigenvalue 1).
    vec3 a = vec3(
        u_rotation[1][2] - u_rotation[2][1],
        u_rotation[2][0] - u_rotation[0][2],
        u_rotation[0][1] - u_rotation[1][0]
    );
    float len = length(a);
    if (len < 1e-6) return vec3(0, 1, 0);
    return a / len;
}

vec3 calcNorm(in vec3 p)
{
    const float h = 0.001;
    #define ZERO (min(frame_count,0))
    vec3 n = vec3(0.0);
    for(int i = ZERO; i < 4; i++)
    {
        vec3 e = 0.5773*(2.0*vec3((((i+3)>>1)&1),((i>>1)&1),(i&1))-1.0);
        n += e*map(p+e*h).dts;
    }
    return normalize(n);
}

float calcAO(Ray r) {
    float aoDist = AO_DIST * u_worldScale;
    float occ = 0.0;
    float itC = 0.0;
    vec3 pos = r.ori + r.dir * r.extent;
    for (int i = 1; i < AO_STEPS; i++) {
        itC++;
        float term = itC * aoDist - map(pos + r.norm * aoDist * itC).dts;
        occ += 1.0 / pow(2.0, itC) * term;
    }
    return 1.0 - clamp(AO_POW * occ / aoDist, 0.0, 1.0);
}

MR march(inout Ray r){
    float hitEps = HIT_DISTANCE * u_worldScale;
    float maxDist = MAX_DISTANCE * u_worldScale;
    MR result = MR(maxDist, vec4(-1));
    for(int i = 0; i < MAX_STEPS && r.extent < maxDist; i++){
        vec3 pos = r.ori + r.dir * r.extent;
        result = map(pos);
        if(result.dts < hitEps){
            r.norm = calcNorm(pos);
            return result;
        }
        r.extent += result.dts;
    }
    r.extent = min(r.extent, maxDist);
    return result;
}

float occlude_march(Ray r, vec3 light_dir) {
    float hitEps = HIT_DISTANCE * u_worldScale;
    float maxDist = MAX_DISTANCE * u_worldScale;
    vec3 pos = r.ori + r.dir * r.extent + r.norm * hitEps * 10.0;
    float rayExtent = 0.0;
    float umbra = 1.0;
    for (int i = 0; i < SHADOW_STEPS; i++) {
        float d = map(pos + light_dir * rayExtent).dts;
        rayExtent += d;
        if (d < hitEps) return 0.0;
        umbra = min(umbra, SHADOW_SMOOTH * d / rayExtent);
        if (rayExtent >= maxDist) break;
    }
    return umbra;
}

Ray getCam(vec2 uv){
    uv.y *= canvas_resolution.y / canvas_resolution.x;

    vec3 forward = normalize(u_view_dir);
    vec3 right   = normalize(cross(forward, u_up_dir));
    vec3 up      = cross(right, forward);

    vec3 dir = normalize(uv.x * right + uv.y * up + FOCAL_LENGTH * forward);
    return Ray(u_cam, dir, 0.0, vec3(0));
}

out vec4 fragColor;
void main(void)
{
    vec2 uv = -1.0 + 2.0 * texcoord;
    Ray cam_ray = getCam(uv);
    MR hit = march(cam_ray);
    vec3 light;

    if(hit.dts < HIT_DISTANCE){
        vec3 albedo = hsv2rgb(vec3(fract(hit.mat.x/12.),.75,.2));
        vec3 light_vector = normalize(SUN_DIR);

        // Direct sun with soft shadows
        light = SUN_COL * albedo * max(0.0, dot(cam_ray.norm, light_vector));
        light *= occlude_march(cam_ray, light_vector);

        // Ambient fill modulated by AO
        float ao = calcAO(cam_ray);
        light += SKY_COL * albedo * ao;
    }
    else{
        light = SUN_COL * max(0.0, dot(cam_ray.dir, SUN_DIR));
    }

    vec3 col = light;
    col = mix(FOG_COL, col, exp(-cam_ray.extent * FOG_AMT / u_worldScale));

    col = pow(col, vec3(1.0 / 2.2));
    fragColor = vec4(col, 1.0);
}
