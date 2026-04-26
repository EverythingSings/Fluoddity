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
#define MAX_DISTANCE 300.0
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
float hash(vec2 p) {
    return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);
}
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
// first object gets a capenter-style tongue attached
float fOpTongue(float a, float b, float ra, float rb) {
    return min(a, max(a - ra, abs(b) - rb));
}
// first object gets a capenter-style groove cut out
float fOpGroove(float a, float b, float ra, float rb) {
    return max(a, min(a + ra, rb - abs(b)));
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
float sdBox( vec3 p, vec3 b )
{
  vec3 q = abs(p) - b;
  return length(max(q,0.0)) + min(max(q.x,max(q.y,q.z)),0.0);
}
float sdTorus( vec3 p, vec2 t )
{
  vec2 q = vec2(length(p.xz)-t.x,p.y);
  return length(q)-t.y;
}
float sdSegment(vec2 p, vec2 a, vec2 b) {
    vec2 pa = p - a, ba = b - a;
    float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
    return length(pa - ba * h);
}
float sdRoundCone( vec3 p, vec3 a, vec3 b, float r1, float r2 )
{
  vec3  ba = b - a;
  float l2 = dot(ba,ba);
  float rr = r1 - r2;
  float a2 = l2 - rr*rr;
  float il2 = 1.0/l2;
    
  vec3 pa = p - a;
  float y = dot(pa,ba);
  float z = y - l2;
  float x2 = dot( pa*l2 - ba*y, pa*l2 - ba*y );
  float y2 = y*y*l2;
  float z2 = z*z*l2;

  // single square root!
  float k = sign(rr)*rr*rr*x2;
  if( sign(z)*a2*z2>k ) return  sqrt(x2 + z2)        *il2 - r2;
  if( sign(y)*a2*y2<k ) return  sqrt(x2 + y2)        *il2 - r1;
                        return (sqrt(x2*a2*il2)+y*rr)*il2 - r1;
}

// quadratic polynomial
float smin( float a, float b, float k )
{
    k *= 4.0;
    float h = max( k-abs(a-b), 0.0 )/k;
    return min(a,b) - h*h*k*(1.0/4.0);
}
float smax( float a, float b, float k){
    return -smin(-a,-b,k);
}
//#define ROBUST
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
    float stair = sdZigzag(p.xy-(mod(steps,2))*(3./steps),q0,q1);
    result = max(result,stair);
return result;
}

#define GROUND_MAT vec4(0)
#define BASE_MAT vec4(1)
#define TRIM_MAT vec4(2)
MR smapMin(MR a, MR b, float k){
// quadratic polynomial
    float h = 1.0 - min( abs(a.dts-b.dts)/(4.0*k), 1.0 );
    float w = h*h;
    float m = w*0.5;
    float s = w*k;
    vec2 smin_result =  (a.dts<b.dts) ? vec2(a.dts-s,m) : vec2(b.dts-s,1.0-m);
    
    return MR( smin_result.x, mix(a.mat,b.mat,smin_result.y));
}


float sdCone( vec3 p, vec2 c, float h )
{
  // c is the sin/cos of the angle, h is height
  // Alternatively pass q instead of (c,h),
  // which is the point at the base in 2D
  vec2 q = h*vec2(c.x/c.y,-1.0);
    
  vec2 w = vec2( length(p.xz), p.y );
  vec2 a = w - q*clamp( dot(w,q)/dot(q,q), 0.0, 1.0 );
  vec2 b = w - q*vec2( clamp( w.x/q.x, 0.0, 1.0 ), 1.0 );
  float k = sign( q.y );
  float d = min(dot( a, a ),dot(b, b));
  float s = max( k*(w.x*q.y-w.y*q.x),k*(w.y-q.y)  );
  return sqrt(d)*sign(s);
}
float sdCyl( vec3 p, float r, float h )
{
  vec2 d = abs(vec2(length(p.xz),p.y)) - vec2(r,h);
  return min(max(d.x,d.y),0.0) + length(max(d,0.0));
}

float sdVesicaSegment( in vec3 p, in vec3 a, in vec3 b, in float w )
{
    vec3  c = (a+b)*0.5;
    float l = length(b-a);
    vec3  v = (b-a)/l;
    float y = dot(p-c,v);
    vec2  q = vec2(length(p-c-y*v),abs(y));
    
    float r = 0.5*l;
    float d = 0.5*(r*r-w*w)/w;
    vec3  h = (r*q.x<d*(q.y-r)) ? vec3(0.0,r,0.0) : vec3(-d,0.0,d+w);
 
    return length(q-h.xy) - h.z;
}
float sdParabola( in vec2 pos, in float wi, in float he )
{
    pos.x = abs(pos.x);
    float ik = wi*wi/he;
    float p = ik*(he-pos.y-0.5*ik)/3.0;
    float q = pos.x*ik*ik/4.0;
    float h = q*q - p*p*p;
    float x;
    if( h>0.0 )
    {
        float r = pow(q+sqrt(h),1.0/3.0);
        x = r + p/r;
    }
    else
    {
        float r = sqrt(p);
        x = 2.0*r*cos(acos(q/(p*r))/3.0);
    }
    x = min(x,wi);
    return length(pos-vec2(x,he-x*x/ik)) * 
           sign(ik*(pos.y-he)+pos.x*pos.x);
}
MR sdbeak(vec3 p){
    p*=1.1;
    p.z*=1.25;
    pR(p.xy,-.107);
    //p.xy+=vec2(3.2,-.3);
    //pR(p.xy,2.-p.x);
   // p.xy-=vec2(2.7,-1.);
    p.xy+=vec2(0.035-.031,.6+min(.5,.4*pow(max(0,-2.495-p.x),1.59)));
    MR result = MR(sdVesicaSegment(p,vec3(2,.61,0),vec3(-2.8,.3,0),.56)-.041,vec4(2));//MR(sdCone(-p.zxy-vec3(0,2.5,-.30),vec2(sin(.32),cos(.32)),2.)-.04,vec4(2));
    float cutout = -(sdVesicaSegment(p-vec3(0,-.1,0),vec3(2,.61,0),vec3(-2.8,.3,0),.56)-.061);
    cutout=smin(cutout,-p.x-0.7,.2);
    result.dts = max(result.dts,cutout);
    
    p.xy-=vec2(0.35,-.015+min(.5,.4*pow(max(0,-2.495-p.x),1.59)));
    result.dts = min(result.dts, sdVesicaSegment(p-vec3(-0.2,-.1,0),vec3(2,.61,0),vec3(-2.8,.3,0),.5)-.031);
    //result.dts = max(result.dts,-p.y+.29);
    
    result.dts = max(result.dts,p.x);
    
    //result.dts = min(result.dts,length(p)-.3);
    //p.x-=
    //result.dts = min(result.dts,(length(p)-1));
    result.dts/=1.25*1.1;
    return result;
}

MR wings(vec3 p){
    p/=1.3;
    p.z=abs(p.z);
    p.xyz+=vec3(1.2,0.2-.142,.5-.63);
    pR(p.xy,.756);
    pR(p.zx,-.89);
    MR result = MR(sdVesicaSegment(p,vec3(0),vec3(0,-7.3,0),1.)-.32
    ,vec4(4)
    );
    result.dts =1.3*( -smin(-result.dts, (sdVesicaSegment(p,vec3(-.6, 4., -0.),vec3(-2.6, -12, -0. ),1.5)-1),.05));

    return result;
}
MR shoulders(vec3 p){
    MR result = MR(999,vec4(2));
    p=vec3(p.x-.5,p.y+2.3,abs(p.z)-.0);
    result.dts = length(p)-1.65;
    return result;
}
MR tail(vec3 p){
    vec3 op = p;
    vec3 h = vec3(0,0,0.8);
    p.z = abs(p.z);
    //pR(p.yz,min(p.z*.05,.05));
    pR(p.yz,-.1);
    pR(p.xz,.35);
    p.z+=2;
    vec3 q = p - clamp( p, -h, h );
    
    MR result = MR(sdRoundCone(q,vec3(2.5,-4,0),vec3(5,-9,0),.6,.1)//sdVesicaSegment(p,vec3(2,-2,1.5),vec3(6,-8,3),1)
    ,vec4(4));
    result.dts = smin(result.dts,sdVesicaSegment(op,vec3(4.15,-7.,0),vec3(-.5,-3.,0),.8),.15);
    return result;
}
MR legs(vec3 p){
    p.z = abs(p.z);
    MR result = MR(sdRoundCone(p,vec3(2.5,-5,.8),vec3(0.35,-6,1.2),.27,.2),vec4(4));
    
    p-=vec3(-.0,-6.6,1.25);
    vec3 op = p;
    pR(p.xy,-.7);
    p.x=abs(p.x);
    p.z=abs(p.z);
    pR(p.yz,1.025);
    pR(p.xy,.419);
    p*=2.68;
    
    float feet = sdTorus(p,vec2(1,.3));
    feet = -smin(-feet,(length(op+vec3(0,1.55,0))-1.46),.061)/2.68;
    result.dts = smin(result.dts,feet,.186);
    return result;
}
MR sdLine(vec3 p){
    MR result = MR(999,vec4(3));
    result.dts = abs(sdParabola(vec2(0,-1.54)-p.zy,45,5));
    result.dts = fOpPipe(result.dts,p.x,.16);//max(result.dts,p.x);
    return result;
}

MR bird(vec3 p){
    const vec2 offs = vec2(0.12,8);
    p.yz-=offs;
    vec3 op = p;
    p.z*=1.1;
    MR result = MR(length(p+vec3(.12,.25,0))-1.,vec4(1));
    MR beak = sdbeak(p);
    beak.dts/=1.1;
    
    p.xy+=vec2(1.,.0);
    pR(p.xy,.7);
    float body = length(p+vec3(.5,5.25,0))-1.4;
    p.xy+=vec2(.51,3.2);
    body = smin(body,length(p)-1.65,.51);
    result = smapMin(result,MR(body,vec4(2)),.48);
    result.dts/=1.1;
    //result = mapMin(result, sdLine(op+vec3(0,offs)));
    result = smapMin(result,tail(op),.1);
    result = smapMin(result,legs(op),.1);
    result = smapMin(result,wings(op),.0221);
    result = smapMin(result,shoulders(op),.1);
    //eyes
    p=op;
    p.xyz=vec3(p.x+.69,p.y-.1,abs(p.z)-.71);
    result.dts = -smin(-result.dts,(length(p)-.21),.1);
    result = mapMin(result,MR(length(p+vec3(-0.4,0.08,.46))-.465,vec4(5)));
    result = smapMin(result,beak,.025);
    return result;
}
MR bulbCheap(vec3 p){
 MR result = MR(999,vec4(6));
    
    vec3 rp = p;
    pR(rp.xy,.25);
    result.dts = sdRoundCone(p,vec3(0),vec3(0,3,0),1,1.65);
    p.y+=.8;
    float base = sdCyl(p,1.3,1);
    result = mapMin(result, MR(base,vec4(7)));
    p.y+=2.;
    result.dts = smin(result.dts,sdCyl(p,.7,1)-.1,.35);
    result.dts = fOpTongue(result.dts,abs(p.y-1)-1.25,.051,.1);
    return result;
}
MR bulb(vec3 p){
    MR result = MR(999,vec4(6));
    
    vec3 rp = p;
    pR(rp.xy,.25);
    float broke = sdZigzag(rp.yz-1.6,vec2(.3,-.5),vec2(.2,.2));
    result.dts = max(broke,abs(sdRoundCone(p,vec3(0),vec3(0,3,0),1,1.65))-.02);
    p.y+=.8;
    float base = sdCyl(p,1.3,1);
    base = max(base,-sdRoundCone(p,vec3(0),vec3(0,3,0),1,1.65));
    result = mapMin(result, MR(base,vec4(7)));
    p.y+=2.;
    result.dts = smin(result.dts,sdCyl(p,.7,1)-.1,.35);
    result.dts = fOpTongue(result.dts,abs(p.y-1)-1.25,.051,.1);
    p.y-=3;
    p.z=abs(p.z)-.37;
    pR(p.yz,.2);
    float filament = sdCyl(p,.031,3)-.02;
    result = mapMin(result,MR(filament,vec4(3)));

    return result;
}
MR scene(vec3 p){
MR result = bird(p);
result = mapMin(result,sdLine(p));
float sz = .02;
MR bul = bulb((p)*sz+vec3(0,3.153,0));
bul.dts/=sz;
p.y+=9;
float hangScale = .75;
p.y-=p.z*p.z/390;
float cell  = pModInterval1(p.z,20,-2,2);
MR hangers = bulbCheap(-p/hangScale);
if(cell == -1){hangers.dts+=2;}
hangers.dts*=hangScale;
result = mapMin(result,hangers);
result = mapMin(result,bul);
return result;
}
////////////////////////////////////////////////////////////////////////////SCENE------------------------SCENE//////////////////////
////////////////////////////////////////////////////////////////////////////SCENE------------------------SCENE//////////////////////
MR sdf(vec3 p) {
    p-=+sim_offset;
    vec3 op = p;
    //float ground = p.y + 20.1;
    //MR result = MR(ground, vec4(0));
    //MR shap = MR(sdBoxFrame(p, vec3(.5),.3), vec4(1));
    //result = mapMin(result, shap);
    float sz = .021;
    p/=sz;
    //MR tow = MR(sdBox(p,vec3(9,14,9)),vec4(1));
    //if(tow.dts<1.2){tow = pyramid(p);}
    //MR result =  MR(sz*tow.dts,tow.mat);
    //float bb = length(p-vec3(0,-100,0))-300;
    //if(bb*sz>2){return MR(bb*sz,vec4(0));}
    MR result = scene(p);
    result.dts*=sz;
    return result; 
}



















// ---------------------------------------------------------------------------
// Canonical SDF -- user-defined scene geometry within the fundamental region.
// Replace this stub with your own scene.
// ---------------------------------------------------------------------------
//MR sdf(vec3 p) {
//    return MR(sdBoxFrame(p, vec3(1), .1), vec4(0));
//}

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
    float light=0;
    if(hit.dts<HIT_DISTANCE){
    vec3 albedo = hsv2rgb(vec3(fract(hit.mat.x/12.),.75,.2));
    vec3 light_vector =  normalize(SUN_DIR);

    // Direct sun with soft shadows
    light = max(0.0, dot(cam_ray.norm, light_vector));
    light *= occlude_march(cam_ray, light_vector);
 
    
    // Ambient fill modulated by AO
    float ao = calcAO(cam_ray);
    light += .1 * ao;
}else{hit.mat.x = 0;}
    vec3 up = u_up_dir;
    vec3 right = normalize(cross(u_view_dir,u_up_dir));
    vec3 N = cam_ray.norm;
    vec3 D = -spiral_axis();//u_world_orientation*normalize(vec3(-1,.1,0));//down vector in worldspace
    vec3 S = (cross(cross(N,D),N));//unit vector perpendicular to N in the same plane as N,D
    S= length(S)>.001?normalize(S):vec3(0);
    S *= dot(D,S); //Proportional to its alignment with down
    vec2 field0 = vec2(dot(right,S),dot(-up,S));
    float fogMix = exp(-cam_ray.extent * generic03.z / u_worldScale);
    light*=fogMix;
    if(isnan(field0.x+field0.y)||!(length(field0)<2.)){field0=vec2(0);}
    fragColor = vec4(-field0,light, floor(hit.mat.x+hash(uv+vec2(light,u_worldScale))));
}