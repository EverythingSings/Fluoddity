#version 330

uniform int frame_count;
uniform vec2 resolution;
uniform float time;

// Camera (vector-based, suitable for arbitrary orientation transforms)
uniform vec3 u_cam;
uniform vec3 u_view_dir;
uniform vec3 u_up_dir;

#define MAX_STEPS 1000
#define HIT_DISTANCE 1e-4
#define MAX_DISTANCE 100
#define FOCAL_LENGTH 2.2

#define SUN_DIR normalize(vec3(sin(time), 1.5, cos(time)))
#define SMALL_BUMP (HIT_DISTANCE*10.0)
#define SUN_COL 3.0*vec3(0.9, 0.8, 0.7)
#define FOG_COL vec3(.12)
#define FOG_AMT .01

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

float sdBox( vec3 p, vec3 b )
{
  vec3 q = abs(p) - b;
  return length(max(q,0.0)) + min(max(q.x,max(q.y,q.z)),0.0);
}

MR mapMin(MR a, MR b){
    return a.dts < b.dts ? a : b;
}

MR map(vec3 p){
    float ground = p.y+1.1;
    MR result = MR(ground, vec4(0));
    MR shap = MR(sdBox(p,vec3(2)),vec4(1));
    result = mapMin(result,shap);
    return result;
}

vec3 calcNorm( in vec3 p )
{
    const float h = 0.0001;
    #define ZERO (min(frame_count,0))
    vec3 n = vec3(0.0);
    for( int i=ZERO; i<4; i++ )
    {
        vec3 e = 0.5773*(2.0*vec3((((i+3)>>1)&1),((i>>1)&1),(i&1))-1.0);
        n += e*map(p+e*h).dts;
    }
    return normalize(n);
}

MR march(inout Ray r){
    MR result = MR(MAX_DISTANCE,vec4(-1));
    for(int i = 0; i< MAX_STEPS && r.extent<MAX_DISTANCE; i++){
        vec3 pos = r.ori + r.dir * r.extent;
        result = map(pos);
        if(result.dts < HIT_DISTANCE){
            r.norm = calcNorm(pos);
            return result;
        }
        r.extent += result.dts;
    }
    r.extent = min(r.extent,MAX_DISTANCE);
    return result;
}

float occlude_march(Ray r, vec3 light_dir){
    Ray shadow_ray = Ray(r.ori + r.dir * r.extent, light_dir, 0.0, vec3(0));
    for (int i = 0;i < 10;i++)
    {
        shadow_ray.ori += r.norm * SMALL_BUMP * pow(2.0, float(i));
        if (map(shadow_ray.ori).dts > HIT_DISTANCE*2)break;
    }
    MR shadow_hit = march(shadow_ray);
    return shadow_hit.dts <= HIT_DISTANCE ? 0.0 : 1.0;
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
    vec3 light = SUN_COL * albedo * max(0,dot(cam_ray.norm, SUN_DIR));

    light *= occlude_march(cam_ray,SUN_DIR);
    light += occlude_march(cam_ray,SKY_DIR)*(SKY_COL * albedo * max(0,dot(cam_ray.norm,SKY_DIR)));
   vec3 col = light;
   col = mix(FOG_COL,col,exp(-cam_ray.extent*FOG_AMT));

    col = pow(col, vec3(1.0 / 2.2));
    fragColor = vec4(col, 1.0);
}
