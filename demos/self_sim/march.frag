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

// Accumulated orientation: maps Base-local directions back to the original
// world frame.  Keeps sun, sky, etc. consistent across cell transitions.
uniform mat3  u_world_orientation;

#define MAX_STEPS 2000
#define HIT_DISTANCE 4e-4
#define MAX_DISTANCE 300.0
#define FOCAL_LENGTH 2.2

#define SUN_DIR (vec3(sin(time*0), 1.5, cos(time*0)))
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
////////////////////////////////////////////////////////////////////////////SCENE------------------------SCENE//////////////////////
////////////////////////////////////////////////////////////////////////////SCENE------------------------SCENE//////////////////////

float pMod1(inout float p, float size) {
    float halfsize = size*0.5;
    float c = floor((p + halfsize)/size);
    p = mod(p + halfsize, size) - halfsize;
    return c;
}
// Repeat in two dimensions
vec2 pMod2(inout vec2 p, vec2 size) {
    vec2 c = floor((p + size*0.5)/size);
    p = mod(p + size*0.5,size) - size*0.5;
    return c;
}
// Repeat in three dimensions
vec3 pMod3(inout vec3 p, vec3 size) {
    vec3 c = floor((p + size*0.5)/size);
    p = mod(p + size*0.5, size) - size*0.5;
    return c;
}


// integer hash copied from Hugo Elias
float hash(int n)
{
    n = (n << 13) ^ n;
    n = n * (n * n * 15731 + 789221) + 1376312589;
    return -1.0 + 2.0 * float(n & 0x0fffffff) / float(0x0fffffff);
}

// 2D gradient noise
float gnoise(in vec2 p)
{
    ivec2 i = ivec2(floor(p));
    vec2  f = fract(p);
    vec2  u = f * f * (3.0 - 2.0 * f);

    // hash each corner using a combined integer key
    float a = hash(i.x + i.y * 57);
    float b = hash(i.x + 1 + i.y * 57);
    float c = hash(i.x + (i.y + 1) * 57);
    float d = hash(i.x + 1 + (i.y + 1) * 57);

    return mix(mix(a, b, u.x),
               mix(c, d, u.x), u.y);
}

// 2D fbm
float fbm(in vec2 p, in float G)
{
    p += vec2(26.06, 17.43);
    float n = 0.0;
    float s = 1.0;
    float a = 0.0;
    float f = 1.0;
    for (int i = 0; i < 8; i++)
    {
        n += s * gnoise(p * f);
        a += s;
        s *= G;
        f *= 2.0;
        p += vec2(0.31, 0.73);
    }
    return n;
}
float sdCyl( vec3 p, float ra, float rb, float h )
{
  vec2 d = vec2( length(p.xz)-ra+rb, abs(p.y) - h + rb );
  return min(max(d.x,d.y),0.0) + length(max(d,0.0)) - rb;
}

// first object gets a capenter-style tongue attached
float fOpTongue(float a, float b, float ra, float rb) {
    return min(a, max(a - ra, abs(b) - rb));
}
// first object gets a v-shaped engraving where it intersect the second
float fOpEngrave(float a, float b, float r) {
    return max(a, (a + r - abs(b))*sqrt(0.5));
}
// produces a cylindical pipe that runs along the intersection.
// No objects remain, only the pipe. This is not a boolean operator.
float fOpPipe(float a, float b, float r) {
    return length(vec2(a, b)) - r;
}
// The "Chamfer" flavour makes a 45-degree chamfered edge (the diagonal of a square of size <r>):
float fOpUnionChamfer(float a, float b, float r) {
    return min(min(a, b), (a - r + b)*sqrt(0.5));
}
// The "Round" variant uses a quarter-circle to join the two objects smoothly:
float fOpUnionRound(float a, float b, float r) {
    vec2 u = max(vec2(r - a,r - b), vec2(0));
    return max(r, min (a, b)) - length(u);
}
float fOpIntersectionRound(float a, float b, float r) {
    vec2 u = max(vec2(r + a,r + b), vec2(0));
    return min(-r, max (a, b)) + length(u);
}

float fOpDifferenceRound (float a, float b, float r) {
    return fOpIntersectionRound(a, -b, r);
}
float fOpIntersectionChamfer(float a, float b, float r) {
    return max(max(a, b), (a + r + b)*sqrt(0.5));
}
// Difference can be built from Intersection or Union:
float fOpDifferenceChamfer (float a, float b, float r) {
    return fOpIntersectionChamfer(a, -b, r);
}
float soften( float x, float m, float e )
{
    float flip = 1;
    if( x>.5){flip = -1; x = 1-x;}
    if( x>m ) return x;
    float a = 2.0*e - m;
    float b = 2.0*m - 3.0*e;
    float t = x/m;
    return (abs(flip)-flip)/2.+flip*((a*t+b)*t*t + e);
}
// Repeat only a few times: from indices <start> to <stop> (similar to above, but more flexible)
float pModInterval1(inout float p, float size, float start, float stop) {
    float halfsize = size*0.5;
    float c = floor((p + halfsize)/size);
    p = mod(p+halfsize, size) - halfsize;
    if (c > stop) { //yes, this might not be the best thing numerically.
        p += size*(c - stop);
        c = stop;
    }
    if (c <start) {
        p += size*(c - start);
        c = start;
    }
    return c;
}
// Repeat around the origin by a fixed angle.
// For easier use, num of repetitions is use to specify the angle.
float pModPolar(inout vec2 p, float repetitions,float softness) {
    float angle = 2*PI/repetitions;
    float a = atan(p.y, p.x) + angle/2.;
    
    
    float r = length(p);
    float c = floor(a/angle);
    a = mod(a,angle) - angle/2.;
    a=soften((a+angle/2.)/angle,softness/2.,softness/(4-2*softness))*angle-angle/2.;
    p = vec2(cos(a), sin(a))*r;
    // For an odd number of repetitions, fix cell index of the cell in -x direction
    // (cell index would be e.g. -5 and 5 in the two halves of the cell):
    if (abs(c) >= (repetitions/2)) c = abs(c);
    return c;
}

float sdSegment(vec2 p, vec2 a, vec2 b) {
    vec2 pa = p - a, ba = b - a;
    float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
    return length(pa - ba * h);
}
float sdRoundCone( vec3 p, float r1, float r2, float h )
{
  float b = (r1-r2)/h;
  float a = sqrt(1.0-b*b);

  vec2 q = vec2( length(p.xz), p.y );
  float k = dot(q,vec2(-b,a));
  if( k<0.0 ) return length(q) - r1;
  if( k>a*h ) return length(q-vec2(0.0,h)) - r2;
  return dot(q, vec2(a,b) ) - r1;
}
float sdSpiral(vec2 p,float scal,int steps){
    float result = 999;
    for(int i=0;i<steps;i++){
    float l= pow(scal,float(i));
    result = min(result,sdSegment(p,vec2(0),vec2(l,0.)));
    p.x-=l;
    p=vec2(-p.y,p.x);
    }
    return result;
}
#define ROBUST
float sdZigzag(vec2 p, vec2 q0, vec2 q1) {
    vec2  s  = q0 + q1;
    float ss = dot(s, s);
    float k  = floor(dot(p, s) / ss);
    vec2  pr = p - k * s;

    // unsigned distance to the 4 candidate segments in the local cell
    float d = sdSegment(pr, -q1, vec2(0));
    d = min(d, sdSegment(pr, vec2(0), q0));
    d = min(d, sdSegment(pr, q0, s));
    d = min(d, sdSegment(pr, s, s + q0));
    #ifdef ROBUST
    // if the zag involves doubling back, check 2 extra segments from each neighbor
    bool edge = dot(s, q0) * dot(s, q1) < 0.0;
    if (edge) {
        // previous cell (pr - s)
        vec2 pp = pr - s;
        d = min(d, sdSegment(pp, q0, s));
        d = min(d, sdSegment(pp, s, s + q0));
        // next cell (pr + s)
        vec2 pn = pr + s;
        d = min(d, sdSegment(pn, -q1, vec2(0)));
        d = min(d, sdSegment(pn, vec2(0), q0));
    }
    #endif
    // sign: point height vs. triangle-wave height
    float f   = dot(pr, s) / ss;
    float f0  = dot(q0, s) / ss;
    float sgn = (s.x * pr.y - s.y * pr.x)
              + (q0.x * q1.y - q0.y * q1.x)
              * min(f / f0, (1.0 - f) / (1.0 - f0));
    #ifdef ROBUST
    sgn = edge?1:sgn;
    #endif
    return sign(sgn) * d;
}
float sdStairs(vec3 p, vec3 frame, float steps, vec2 lean){
    float result = sdBox(p,frame);
    vec2 rr = frame.xy*2/steps;
    vec2 q0 = vec2(0,rr.y)-lean*vec2(-1,1);
    vec2 q1 = rr-q0;
    float stair = sdZigzag(p.xy,q0,q1);
    result = max(result,stair);
return result;
}


float platform(vec3 p){
float result = sdBox(p,vec3(10,1,10));
result = min(result, sdStairs(p+vec3(11,0,0), vec3(1,1,5),4,vec2(0)));
return result;
}
float ornament(vec3 p){
float bb = sdBox(p,vec3(1.4));
if(bb>.5)return bb;
vec3 op = p;
float result = sdBox(p-vec3(0,.16,0),vec3(.5,1.1,1.38)-.05)-.05;
result = fOpDifferenceRound(result,sdBox(p-vec3(0,-.36,0),vec3(10,.25,.152)),.031);//mouth
p.z=abs(p.z);
result = fOpDifferenceChamfer(result,-.04+sdBox(p-vec3(0,.4,0.5),vec3(10,.06,.06)+.06),.1);//eyes
result = max(result,-sdBox(p-vec3(-1.46,0,1.15),vec3(1,1.5,.325)));//cheeks
float sz = .6;
p=op;
p.z=-abs(p.z);
p.z+=.299;
p.y*=-1;
p.z+=log(p.y*.1+.6)+.5;
float grave = sdSpiral(p.yz/sz,.72,4)*sz;
grave = min(grave,sdSegment(p.yz,vec2(0),vec2(0,1)));
result = fOpUnionRound(result,fOpPipe(result,grave,.051),.02);//swirls
p=op;
p.y-=.12;
float nose = sdRoundCone(p-vec3(-.35,0,0),.25,.15,.55);//nose
p.z=abs(p.z)-.12;
p.y+=.01;
nose = fOpUnionRound(nose,length(p-vec3(-.38,0,0))-.2,.025);
result = fOpUnionRound(result,nose,.01);//nose


p=op;
p.z=abs(p.z);
p.z-=1.2;
vec3 fp = p;//cache for later
p.y=abs(p.y-.3)+.15;
sz= .45;
grave = sdSpiral(p.yz/sz,.7,5)*sz;//ears
result = fOpUnionRound(result,fOpPipe(result,grave,.04),.02);//ears

result -= .0;//puff
p=fp-vec3(0,.8,-.4);
sz=.5;
p.yz = vec2(p.z,-p.y);
grave = sdSpiral(p.yz/sz,.7,5)*sz;
result = fOpEngrave(result, grave, .04);//wings
p=op;
float hat = sdBox(op-vec3(0,1,0),vec3(.5485,.2,.85)-.01)-.07;
p-=vec3(-.65,1,0);
fp=p;//cache for later
p.z=abs(p.z);
p.z-=.25;
hat = fOpDifferenceRound(hat,sdStairs(-p.yzx,vec3(.2,.2,.1),6,vec2(0)),.03);
p.y = abs(.07-abs(p.y))-.07;
p.z-=.3;
grave = sdSegment(p.yz,vec2(0),vec2(0,1));
hat = fOpEngrave(hat,grave,.04);
p=fp+vec3(0,.125,0);
grave = sdRoundCone(p,.01,.12,.25);//sdSegment(p.yz,vec2(0),vec2(1));
hat = fOpEngrave(hat,grave,.02);
result = fOpUnionRound(result,hat,0.05);//hat
p=op;
p.z = abs(p.z)-.95;
p.y = abs(.12-abs(p.y+.48))-.12;
grave = sdSegment(p.yz,vec2(0),vec2(0,1));
result = fOpEngrave(result,grave-.03,.07);
p=op;
p+=vec3(0,.91,0);
float chin = sdBox(p,vec3(.561,.15,.8));
p.z=abs(.4*.68-abs(p.z))-.4*.68;

chin = fOpEngrave(chin,sdSegment(p.yz,vec2(0,-.1),vec2(0,.1)),.1);
result =fOpUnionRound(result,chin,.04);
return result;
}
float tower(vec3 p){
    
    vec3 h = vec3(1,0,3);
    p-=clamp(p,-h,h);
    pModPolar(p.xz,4,.5);
    float core = sdBox(p,vec3(2.,13.25,5.));
    float result = sdStairs(p*vec3(-1,1,1)+vec3(3,-6.,0),vec3(1,7,10),12,vec2(0))-.2;
    return min(result,core);
}
MR tower_facade(vec3 p){
    vec3 op = p;
    p -= vec3(-5.35,6,0);
    vec2 rr = vec2(2.,7);
    float stairang = atan(rr.y,rr.x);
    float wid = 3;
    float result = sdStairs(p,vec3(rr,wid),60,vec2(0));
    vec4 mat = vec4(1);
    p.z=abs(p.z);
    pR(p.xy,stairang);
    p.z-=wid;
    result = min(result,sdBox(p,vec3(7.35,.25,.35)));
    p=op;
    p.xy+=vec2(6,-4);
    pR(p.xy,stairang-PI/2);
    p.y-=2.7;
    pModInterval1(p.y,5,-2,1);
    
    pR(p.xy,PI/2-stairang);
    p.x-=0.2;
    float orn = ornament(p);
    result = min(result,orn);
    if(result == orn){mat.x = 2;}
    result=max(result,op.y-13);
    return MR(result,mat);
}

////////////////////////////////////////////////////////////////////////////SCENE------------------------SCENE//////////////////////
////////////////////////////////////////////////////////////////////////////SCENE------------------------SCENE//////////////////////



// ---------------------------------------------------------------------------
// Canonical SDF — user-defined scene geometry within the fundamental region.
// Replace this stub with your own scene.
// ---------------------------------------------------------------------------
MR sdf(vec3 p) {
    vec3 op = p;
    //float ground = p.y + 20.1;
    //MR result = MR(ground, vec4(0));
    //MR shap = MR(sdBoxFrame(p, vec3(.5),.3), vec4(1));
    //result = mapMin(result, shap);
    float sz = .1;
    p/=sz;
    float tow = sdBox(p,vec3(7,14,5));
    if(tow<1.2){tow = min(tower_facade(p).dts,tower(p));}
    MR result =  MR(sz*tow,vec4(1));
    result = mapMin(result, MR(sdBoxFrame(op,u_region_half_extents ,.1),vec4(0)));//result;
    return result; 
}

// ---------------------------------------------------------------------------
// Three-cell map: evaluates sdf() at Base, Micro, and Macro scales.
// No recursion — the illusion of infinite depth comes from camera teleportation.
//
// Extra cells: #define EXTRA_MICRO_CELLS N and/or EXTRA_MACRO_CELLS N
// to render N additional cells beyond the default one at each end.
// Default 0 (off).  Compiler eliminates the loop when N == 0.
// ---------------------------------------------------------------------------
//#define EXTRA_MICRO_CELLS 1


MR map(vec3 p) {
    // Base: evaluate at current coordinates
    MR d = sdf(p);

    // --- Micro chain ---------------------------------------------------------
    vec3  pMicro = u_rotation * (p - u_offset) / u_scale;
    float microCorr = u_scale;
    MR mMicro = sdf(pMicro);
    mMicro.dts *= microCorr;
    d = mapMin(d, mMicro);

    #ifdef EXTRA_MICRO_CELLS
        for (int i = 0; i < EXTRA_MICRO_CELLS; i++) {
            pMicro    = u_rotation * (pMicro - u_offset) / u_scale;
            microCorr *= u_scale;
            mMicro     = sdf(pMicro);
            mMicro.dts *= microCorr;
            d = mapMin(d, mMicro);
        }
    #endif
    // --- Macro chain ---------------------------------------------------------
    mat3  rot_inv  = transpose(u_rotation);
    vec3  pMacro   = u_scale * (rot_inv * p) + u_offset;
    float macroCorr = u_scale;
    MR mMacro = sdf(pMacro);
    mMacro.dts /= macroCorr;
    d = mapMin(d, mMacro);
    #ifdef EXTRA_MACRO_CELLS
        for (int i = 0; i < EXTRA_MACRO_CELLS; i++) {
            pMacro    = u_scale * (rot_inv * pMacro) + u_offset;
            macroCorr *= u_scale;
            mMacro     = sdf(pMacro);
            mMacro.dts /= macroCorr;
            d = mapMin(d, mMacro);
        }
    #endif
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

    vec3 light_vector = u_world_orientation * normalize(SUN_DIR);
    vec3 sky_dir      = u_world_orientation * normalize(SKY_DIR);
    vec3 light = SUN_COL * albedo * max(0, dot(cam_ray.norm, light_vector));

    light *= occlude_march(cam_ray, light_vector);
    light += occlude_march(cam_ray, sky_dir)*(SKY_COL * albedo * max(0, dot(cam_ray.norm, sky_dir)));
    vec3 col = light;
    col = mix(FOG_COL, col, exp(-cam_ray.extent * FOG_AMT / u_worldScale));

    col = pow(col, vec3(1.0 / 2.2));
    fragColor = vec4(col, 1.0);
}
