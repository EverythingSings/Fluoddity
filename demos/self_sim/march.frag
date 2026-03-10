#version 330

uniform int frame_count;
uniform vec2 resolution;
uniform float time;

// Camera (vector-based, suitable for arbitrary orientation transforms)
uniform vec3 u_cam;
uniform vec3 u_view_dir;
uniform vec3 u_up_dir;

// Similarity transform (Base ↔ Micro relationship)
uniform vec3  u_offset;              // Micro copy center in Base space
uniform float u_scale;               // Micro scale factor (0 < s < 1)
uniform mat3  u_rotation;            // Micro rotation relative to Base

// Fundamental region
uniform vec3  u_region_half_extents; // AABB half-size of the fundamental region

// Transition / scale
uniform float u_worldScale;          // Current world scale (1.0 when far from micro)
uniform float u_transition_distance; // Shell thickness for transition zone

#define MAX_STEPS 1000
#define HIT_DISTANCE 1e-4
#define MAX_DISTANCE 100.0
#define FOCAL_LENGTH 2.2

#define SUN_DIR normalize(vec3(sin(time*0), 1.5, cos(time*0)))
#define SUN_COL 3.0*vec3(0.9, 0.8, 0.7)
#define FOG_COL vec3(.12)
#define FOG_AMT .1

#define PI 3.14159

in vec2 v_texcoord;

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

MR mapMin(MR a, MR b){
    return a.dts < b.dts ? a : b;
}

// ---------------------------------------------------------------------------
// Signed distance to the Micro copy's bounding box, in Base (unscaled) space.
// Negative = inside the Micro box.
// ---------------------------------------------------------------------------
float sdMicroBox(vec3 p) {
    vec3 q = u_rotation * (p - u_offset);
    vec3 halfExt = u_region_half_extents * u_scale;
    vec3 d = abs(q) - halfExt;
    return length(max(d, 0.0)) + min(max(d.x, max(d.y, d.z)), 0.0);
}

// ---------------------------------------------------------------------------
// Canonical SDF — user-defined scene geometry within the fundamental region.
// Replace this stub with your own scene.
// ---------------------------------------------------------------------------
MR sdf(vec3 p) {
    //float ground = p.y + 20.1;
    //MR result = MR(ground, vec4(0));
    //MR shap = MR(sdBoxFrame(p, vec3(.5),.3), vec4(1));
    //result = mapMin(result, shap);
    return MR(sdBoxFrame(p,vec3(2.5),.1),vec4(0));//result;
}

// ---------------------------------------------------------------------------
// Three-cell map: evaluates sdf() at Base, Micro, and Macro scales.
// No recursion — the illusion of infinite depth comes from camera teleportation.
// ---------------------------------------------------------------------------
MR map(vec3 p) {
    // Base: evaluate at current coordinates
    MR d = sdf(p);

    // Micro: transform into the scaled-down copy's local frame
    vec3 pMicro = u_rotation * (p - u_offset) / u_scale;
    MR mMicro = sdf(pMicro);
    mMicro.dts *= u_scale;  // correct distance from micro-frame to base-frame
    d = mapMin(d, mMicro);

    // Macro: transform as if Base is the Micro copy of a larger parent
    // inverse(u_rotation) = transpose(u_rotation) for orthogonal matrices
    vec3 pMacro = u_scale * (transpose(u_rotation) * p) + u_offset;
    MR mMacro = sdf(pMacro);
    mMacro.dts /= u_scale;  // correct distance from macro-frame to base-frame
    d = mapMin(d, mMacro);

    return d;
}

vec3 calcNorm(in vec3 p)
{
    const float h = 0.0001;
    #define ZERO (min(frame_count,0))
    vec3 n = vec3(0.0);
    for(int i = ZERO; i < 4; i++)
    {
        vec3 e = 0.5773*(2.0*vec3((((i+3)>>1)&1),((i>>1)&1),(i&1))-1.0);
        n += e*map(p+e*h).dts;
    }
    return normalize(n);
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

float occlude_march(Ray r, vec3 light_dir){
    float bump = HIT_DISTANCE * 10.0 * u_worldScale;
    Ray shadow_ray = Ray(r.ori + r.dir * r.extent, light_dir, 0.0, vec3(0));
    for (int i = 0; i < 10; i++)
    {
        shadow_ray.ori += r.norm * bump * pow(2.0, float(i));
        if (map(shadow_ray.ori).dts > HIT_DISTANCE * 2.0 * u_worldScale) break;
    }
    MR shadow_hit = march(shadow_ray);
    return shadow_hit.dts <= HIT_DISTANCE * u_worldScale ? 0.0 : 1.0;
}

Ray getCam(vec2 uv){
    uv.y *= resolution.y / resolution.x;

    vec3 forward = normalize(u_view_dir);
    vec3 right   = normalize(cross(forward, u_up_dir));
    vec3 up      = cross(right, forward);

    vec3 dir = normalize(uv.x * right + uv.y * up + FOCAL_LENGTH * forward);
    return Ray(u_cam, dir, 0.0, vec3(0));
}

#define SKY_COL 3*vec3(.04,.15,.3)
#define SKY_DIR normalize(vec3(-.2,1,0))
out vec4 fragColor;
void main(void)
{
    vec2 uv = -1.0 + 2.0 * v_texcoord;
    Ray cam_ray = getCam(uv);
    MR hit = march(cam_ray);
    //sun
    vec3 albedo = hsv2rgb(vec3(fract(hit.mat.x/8.),.5,.2));
    vec3 light = SUN_COL * albedo * max(0, dot(cam_ray.norm, SUN_DIR));

    light *= occlude_march(cam_ray, SUN_DIR);
    light += occlude_march(cam_ray, SKY_DIR)*(SKY_COL * albedo * max(0, dot(cam_ray.norm, SKY_DIR)));
    vec3 col = light;
    col = mix(FOG_COL, col, exp(-cam_ray.extent * FOG_AMT / u_worldScale));

    col = pow(col, vec3(1.0 / 2.2));
    fragColor = vec4(col, 1.0);
}
