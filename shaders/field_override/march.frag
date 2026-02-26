#version 150

uniform int frame_count;
uniform vec2 canvas_resolution;

uniform vec3 camera_pos;
uniform vec3 camera_dir;
#define MAX_STEPS 10000
#define HIT_DISTANCE 1e-3
#define MAX_DISTANCE 100

#define FOCAL_LENGTH 2.

#define PI 3.1415926
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
void pR(inout vec2 p, float a) {
    p = cos(a)*p + sin(a)*vec2(p.y, -p.x);
}
// Repeat in two dimensions
vec2 pMod2(inout vec2 p, vec2 size) {
    vec2 c = floor((p + size*0.5)/size);
    p = mod(p + size*0.5,size) - size*0.5;
    return c;
}
float sdBox( vec3 p, vec3 b )
{
  vec3 q = abs(p) - b;
  return length(max(q,0.0)) + min(max(q.x,max(q.y,q.z)),0.0);
}
MR map(vec3 p){pR(p.xz,frame_count/10500.);
    vec3 op = p;
    float dts = MAX_DISTANCE;
    /*
pMod2(p.xz,vec2(3.));
float phase = -frame_count/5000.+length(op/10.);
float amt = (sin(phase));
if(amt>0){
dts= length(p+vec3(0,4,0))-.51*1*amt*2;
p=op;
dts = min(dts,p.y+4);
}

else{
    dts = length(p+vec3(0,4,0))+.51*amt*2;
    p=op;
    dts = max(-dts,p.y+4);
}
*/
//dts = p.y+sin(length(p+.7*dot(sin(1.5*p),cos(1.5*p))));
p = op;
pR(p.xz,frame_count/3500.);
p-= vec3(0,0,0);


pR(p.yx,0.61547957);
pR(p.yz,PI/4.);
float box = sdBox(p,vec3(1.5));

p=op;
//dts = min(dts,p.y+4);
dts =  max(-box+5,dts);
dts = min(dts,box);
vec4 mat = vec4(1);
return MR(dts,mat);
}
vec3 safenorm(vec3 p){
    float lp = length(p);
    return lp>.00001? normalize(p):vec3(0);
}
vec3 calcNorm( in vec3 p ) // for function f(p)
{
    const float h = 0.0001;      // replace by an appropriate value
    #define ZERO (min(frame_count,0)) // non-constant zero
    vec3 n = vec3(0.0);
    for( int i=ZERO; i<4; i++ )
    {
        vec3 e = 0.5773*(2.0*vec3((((i+3)>>1)&1),((i>>1)&1),(i&1))-1.0);
        n += e*map(p+e*h).dts;
    }
    return safenorm(n);
}
int steps;
MR march(inout Ray r){
    MR result = MR(MAX_DISTANCE,vec4(-1));
    for(int i = 0; i< MAX_STEPS && r.extent<MAX_DISTANCE; i++){
        vec3 pos = r.ori + r.dir * r.extent;
        result = map(pos);
        float dts = result.dts;
        vec4 mat = result.mat;
        if(dts < HIT_DISTANCE){
            r.norm = calcNorm(pos);
            return result;
        }
        r.extent += result.dts;
        steps = i+1;
    }
    //r.norm = vec3(0,0,1);
    return result;
}
vec3 forward;
vec3 right;
vec3 up;
Ray getCam(vec2 uv){
    uv.y*=canvas_resolution.y/canvas_resolution.x;
    vec3 dir = normalize(vec3(uv,FOCAL_LENGTH));
    
    forward = camera_dir;
    up = vec3(0,1,0);
    right = normalize(cross(forward,up));
    up = normalize(cross(right,forward));
    dir= mat3(-right,up,forward)*dir;
    return Ray (camera_pos,dir,0,vec3(0));
}
out vec4 fragColor;
void main(void)
{
    vec2 uv = -1. + 2. * texcoord;
    Ray cam_ray = getCam(uv);
    MR hit = march(cam_ray);
    //vec2 field0 = vec2(cam_ray.extent/30.);
    vec3 N = cam_ray.norm;
    vec3 D = vec3(0,1,0);//down
    vec3 S = safenorm(cross(cross(N,D),N));//unit vector perpendicular to N in the same plane as N,D
    S *= dot(D,S); //Proportional to its alignment with down
    vec2 field0 = vec2(dot(right,S),dot(-up,S));

    //vec2 field0 = vec2(dot(right,cam_ray.norm*vec3(1,1,1)),dot(up,cam_ray.norm*vec3(1,1,1)));//vec3(cam_ray.extent/10);
    if(isnan(field0.x+field0.y)||!(length(field0)<2.)){field0=vec2(0);}
    fragColor = vec4(field0,-field0);
}