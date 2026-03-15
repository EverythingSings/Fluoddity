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
float sdPyramid( vec3 p, float h )
{
  float m2 = h*h + 0.25;
    
  p.xz = abs(p.xz);
  p.xz = (p.z>p.x) ? p.zx : p.xz;
  p.xz -= 0.5;

  vec3 q = vec3( p.z, h*p.y - 0.5*p.x, h*p.x + 0.5*p.y);
  float s = max(-q.x,0.0);
  float t = clamp( (q.y-0.5*p.z)/(m2+0.25), 0.0, 1.0 );
  float a = m2*(q.x+s)*(q.x+s) + q.y*q.y;
  float b = m2*(q.x+0.5*t)*(q.x+0.5*t) + (q.y-m2*t)*(q.y-m2*t);
    
  float d2 = min(q.y,-q.x*m2-q.y*0.5) > 0.0 ? 0.0 : min(a,b);
  return sqrt( (d2+q.z*q.z)/m2 ) * sign(max(q.z,-p.y));
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


MR pyramid(vec3 p){
    vec3 op = p;
    MR result = MR(999,BASE_MAT);
    vec3 sz = vec3(3,3,100);
    float steps = 20;
    vec2 attack = vec2(.350,0.0);
    p-=vec3(0,3,0);
    pModPolar(p.xz,4,0);
    vec3 mp = p;
    p.x-=sz.x;
    p.x*=-1;
    result.dts = sdStairs(p,sz,steps, 6./steps*sz.xy/3.*attack);
    p=mp;
    
    p.x-=sz.x;
    pR(p.xy,atan(sz.x,sz.y));
    p.z=mod(p.z+1,2.)-1;//abs(p.z);
    //p.z-=sz.z;
    MR rail = MR(sdBox(p,vec3(.15,sqrt(dot(sz.xy,sz.xy)),.15)),TRIM_MAT);
    result.dts = fOpEngrave(result.dts,rail.dts,0.2);
    result = mapMin(result,rail);
    return result;
}
float sdCone( vec3 p, vec2 c )
{
    // c is the sin/cos of the angle
    vec2 q = vec2( length(p.xz), -p.y );
    float d = length(q-c*max(dot(q,c), 0.0));
    return d * ((q.x*c.y-q.y*c.x<0.0)?-1.0:1.0);
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
float sdVesica( in vec3 p, in vec3 a, in vec3 b, in float w )
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
float moon2(vec2 p, float d, float ra, float rb )
{
    p.y = abs(p.y);
    float a = (ra*ra - rb*rb + d*d)/(2.0*d);
    float b = sqrt(max(ra*ra-a*a,0.0));
    if( d*(p.x*b-p.y*a) > d*d*max(b-p.y,0.0) )
          return length(p-vec2(a,b));
    return max( (length(p          )-ra),
               -(length(p-vec2(d,0))-rb));
}
float sdMoon( in vec3 p,vec3 dab ,float h )
{
    float d = moon2(p.xy,dab.x,dab.y,dab.z);
    vec2 w = vec2( d, abs(p.z) - h );
    return min(max(w.x,w.y),0.0) + length(max(w,0.0));
}

float sdUnevenCapsule( vec2 p, float r1, float r2, float h )
{
    p.x = abs(p.x);
    float b = (r1-r2)/h;
    float a = sqrt(1.0-b*b);
    float k = dot(p,vec2(-b,a));
    if( k < 0.0 ) return length(p) - r1;
    if( k > a*h ) return length(p-vec2(0.0,h)) - r2;
    return dot(p, vec2(a,b) ) - r1;
}
float sdScale( in vec3 p, in vec3 rrh, in float h )
{
    float d = sdUnevenCapsule(p.xy,rrh.x,rrh.y,rrh.z);
    vec2 w = vec2( d, abs(p.z) - h );
    return min(max(w.x,w.y),0.0) + length(max(w,0.0));
}
MR sdFeather(vec3 p,float sz, float base_h,float nick_seed){
    base_h*=5;
    float thickness = .02*base_h/7.;
    vec2 rads = vec2(.6,.4);
    p/=sz;
    float bb = sdBox(p,vec3(rads.x/2.*1.57,base_h/1.9,thickness*2));
    //if(bb>.52){return MR(bb,vec4(7));}
    
    
    p.y-=base_h/2;
    vec3 op = p;
    p.y+=base_h;
    pR(p.xz,min(1,abs(p.x)/rads.x*p.x/rads.x)/5);
    p.y-=base_h;
    
    
    MR result = MR(sdCone(p,vec2(sin(.015),cos(.015)),base_h)-thickness,vec4(5));
    
    p.y+=rads.x-thickness*2;
    p.x=abs(p.x);
    result.dts = min(result.dts,sdScale(-p-vec3(.15*(rads.x+rads.y),0,0),vec3(rads,base_h*.9-rads.y-rads.x),0)-thickness);
    //#define NICKS 1
    #ifdef NICKS
            float seed = (nick_seed);
                float place = base_h*.85*(hash(vec2(seed,1.8)));
                op.x*=hash(vec2(-nick_seed/15.+1.245))>0.5?-1:1;
                if(op.x>0){
                p.y+=(place);
                pR(p.xy,.6);
                result.dts = max(result.dts, min(min(length(p.xy-vec2(0,1.6))-01.6,-op.y-place),p.y));
                }
    #endif
    result.dts*=sz/1.2;
    return result;
}
float sdbeak(vec3 p,float size,float openness){
    p/=size;
    float skinny = 1.4;
    p.z*=skinny;
    float base_len = 7.9;
    //p-=vec3(-2,1,0);
    vec3 op = p;
    p.x+=base_len/2.;
    pR(p.xy,min(.3,-p.x*.6/base_len*.5));
    p.x+=base_len/2;
    pR(p.xy,.7/(.8+.6*base_len/6.*abs(p.x)));
    p.x-=base_len;
    float result = .9*sdVesica(p,vec3(0),vec3(-base_len,0,0),1.0);
    result = smax(abs(result)-.05,-.051-sdZigzag(p.xy,.5*vec2(1.,.1),.5*vec2(0,-0.1)),.01);
    pR(p.xy,openness);
    float bottom = sdVesica(p,vec3(0),vec3(-base_len,0,0),.9);
    bottom = max(abs(bottom)-.05,p.y);
    
    //bottom = max(bottom,-sdCone(-p.yxz,vec2(sin(.35),cos(.35))));
    result = min(result, bottom);
    p=op;
    result = smax(result,length(p-vec3(-6,0,0))-4.9,.2);
    return result/skinny*size;
}
MR sdTail(vec3 p){
    p.x+=1;
    p.y-=11.5;
    MR result = sdFeather(p.zyx,4,.6,.7);
    //result = smax(result,(length(p)-base_len*1),.1);
    return result;
}
MR sdWings(vec3 p){
    p.z = abs(p.z);
    p-=vec3(-.8,5.5,1.515);
    pR(p.xz,.42);
    pR(p.yz,.1875);
    p.z=-p.z;
    MR result = sdFeather(p,4.,.46,0);
    pR(p.xz,-.251);
    pR(p.yz,-.01);
    p-=vec3(-1.14,-2.9,-.4314);
    pR(p.xy,-.2);
    result = mapMin(result,sdFeather(p,2.5,.68,0));
    result.dts*=.85;
    return result;
}
MR legs(vec3 p){
    p.z = abs(p.z);
    p=p.yxz;

    p-=vec3(3.,1,.86);
        pR(p.yz,.48);
    
    pR(p.xy,-.82);
    MR result = MR(sdRoundCone(p,1.5,1.,2.),vec4(6));
    p.y-=2.;
    pR(p.xy,1.4);
    result = smapMin(result, MR(sdRoundCone(p,.4,.2,3.4),vec4(7)),.1);
    
    p.y-=3.5;
    pR(p.xy,-.2);
    pR(p.yz,-.2);
    p.xz=-abs(p.xz);
    pR(p.xy,.85);
    pR(p.yz,-.425);
    result = smapMin(result, MR(sdRoundCone(p,.39,.2,2.),vec4(8)),.1);
    p-=vec3(0.4,2.,0.2);
    pR(p.xy,-.69);
    pR(p.yz,.24);
    result = smapMin(result,MR(sdMoon(p,vec3(.91,.76,1.),.01)-.031,vec4(9)),0.1);//result.dts = smin(result.dts, sdRoundCone(p,.18,.08,1.5),.031);
    return result;
}
float simple_noise(vec3 p){
pR(p.yz,p.x/6);
float n = sin(p.y*5)/20+sin(p.z*2.5)/20;
pR(p.xy,1.6);
pR(p.yz,.8);
p+=1;
n+=sin(p.y*4)/15+sin(p.z*2.4)/15;
return n;
}
MR branch2(vec3 p){
    p+=vec3(4,13,1.);
    float weird = simple_noise(p);
    MR result = MR(sdRoundCone(p.yxz,1,1.8,15),vec4(12));
    p-=vec3(12,1,0);
    pR(p.xy,.6);
    result.dts = .8*(weird+smin(result.dts,sdRoundCone(p.yxz,.8,1.,4),.1));
    return result;
}
MR branch(vec3 p){
    p+=vec3(16,9.,-.8);
    float weird = .75*simple_noise(p*vec3(.61,1,1));
    pR(p.xz,-.1);
    pR(p.xy,p.x/100-.4);
    MR result = MR(sdRoundCone(p.yxz,.6,1.8,30),vec4(10));
    p-=vec3(24,1,0);
    pR(p.xy,.16);
    result.dts = weird+smin(result.dts,sdRoundCone(p.yxz,.8,1.,6),.31);
    result.dts *=.85;
    p.xy+=vec2(28,-3);
    pR(p.xy,-1.68);
    MR berry = MR(length(p)-8,vec4(11));
    p.y-=1.95;
    
    berry.dts =.9*smin(smax(berry.dts,-length(p)+6.9,.4),sdTorus(p,vec2(3.9)),.4);
    result= mapMin(result,berry);
    return result;
}


MR bird(vec3 p){
    p.y-=6;
    vec3 op = p;
    MR result = MR(999,vec4(2));
    result.dts = length(p)-1.35;
    vec3 ep = p+vec3(.3,-.7,-0.071);
    ep.z=abs(ep.z)-1.1;
    MR eye = MR(sdTorus(ep.yzx,vec2(.4,.09)),vec4(3));
    MR pupil = MR(length(ep-vec3(0,0,-.2))-.5,vec4(4));
    p+=vec3(-0,2,0)+vec3(-.385,.88,-.3382)*5;//-.623,.823,-.011
    pR(p.xz,1.5);
    pR(p.xy,-2);
    MR body = MR(sdRoundCone(p,2.95,1.,6.5),vec4(5));
    result = smapMin(result,body,1.5);
    result= smapMin(result,eye,.15);
    result = mapMin(result,pupil);
    result = smapMin(result, sdTail(p), .1);
    result = smapMin(result, legs(p),.1);
    p.z = mix(abs(p.z),body.dts,.5);
    result = smapMin(result, sdWings(p),.1);
    p=op;
    p.x-=3.1;
    p.y+=.8;
    result = smapMin(result,MR(sdbeak(p,1.453,.1),vec4(1)),.1);
    result = mapMin(result,branch(op-vec3(-.385,.88,-.3382)*-5+5*vec3(.623,-.823,.011)));

    //result.mat.x=0;
    return result;
}

////////////////////////////////////////////////////////////////////////////SCENE------------------------SCENE//////////////////////
////////////////////////////////////////////////////////////////////////////SCENE------------------------SCENE//////////////////////
MR sdf(vec3 p) {
    p-=vec3(0.17,-5.52,0)+vec3(.830,2.38,.05)*2+sim_offset*2.;
    vec3 op = p;
    //float ground = p.y + 20.1;
    //MR result = MR(ground, vec4(0));
    //MR shap = MR(sdBoxFrame(p, vec3(.5),.3), vec4(1));
    //result = mapMin(result, shap);
    float sz = .21;
    p/=sz;
    //MR tow = MR(sdBox(p,vec3(9,14,9)),vec4(1));
    //if(tow.dts<1.2){tow = pyramid(p);}
    //MR result =  MR(sz*tow.dts,tow.mat);
    float bb = length(p)-25;
    if(bb*sz>2){return MR(bb*sz,vec4(0));}
    MR result = bird(p);
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