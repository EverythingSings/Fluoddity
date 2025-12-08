#version 430

uniform vec2 resolution;
uniform float time;
uniform sampler2D prevPass;

in vec2 texcoord;
out vec4 fragColor;

//SCENE INTERSECTION CONSTANTS------------------
#define MAX_MARCH_STEPS 960
#define MAX_MARCH_DIST 20
#define MARCH_HIT_DIST 1e-4
#define HOP_ACROSS_SCALE 3
#define SHADOW_EPSILON MARCH_HIT_DIST//1e-3


struct Ray{
    vec3 ori; //Ray origin
    vec3 dir; //Ray direction, always normalized
    vec3 pos; //Current ray position
};
struct MatId{
    int id;
    vec2 uv;
};
struct MR{ //Map Result
    float dts; //distance to scene (preferably signed distance for stability of normals and such, but the marcher will just use abs(dts) when transmitting
    MatId medium; ////medium of mapped location
};
struct Hit{
    Ray ray_in; //Incoming ray that triggered the hit
    vec3 normal; //surface normal at hit location, always normalized and in the arriving hemisphere. So dot(ray_in.pos,normal)<0
    MatId old_medium; //MatId of the material through which the ray arrived
    MatId new_medium; //MatId of the material the ray struck
    bool hitQ; //did we hit something?
};
///////////////////RANDOM
uint rngState;
uint PCGHash(inout uint state) {
    state = state * 747796405u + 2891336453u;
    uint word = ((state >> ((state >> 28u) + 4u)) ^ state) * 277803737u;
    return (word >> 22u) ^ word;
}
float hash2(vec2 co){
return fract(sin(dot(co, vec2(12.9898, 78.233))) * 43758.5453);
}
float RandomFloat() {
    return PCGHash(rngState) / 4294967295.0;
}

vec2 RandomVec2() {
    return vec2(RandomFloat(), RandomFloat());
}

vec3 RandomVec3() {
    return vec3(RandomFloat(), RandomFloat(), RandomFloat());
}
void init_rng(vec2 uv, float time){
    rngState = floatBitsToUint(hash2(uv+vec2(fract(time),fract(time*2.037)))); 
}

////////////COMMON
void pR(inout vec2 p, float a) {
    p = cos(a)*p + sin(a)*vec2(p.y, -p.x);
}
// All components are in the range [0…1], including hue.
vec3 rgb2hsv(vec3 c)
{
    vec4 K = vec4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0);
    vec4 p = mix(vec4(c.bg, K.wz), vec4(c.gb, K.xy), step(c.b, c.g));
    vec4 q = mix(vec4(p.xyw, c.r), vec4(c.r, p.yzx), step(p.x, c.r));

    float d = q.x - min(q.w, q.y);
    float e = 1.0e-10;
    return vec3(abs(q.z + (q.w - q.y) / (6.0 * d + e)), d / (q.x + e), q.x);
}
// All components are in the range [0…1], including hue.
vec3 hsv2rgb(vec3 c)
{
    vec4 K = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);
    vec3 p = abs(fract(c.xxx + K.xyz) * 6.0 - K.www);
    return c.z * mix(K.xxx, clamp(p - K.xxx, 0.0, 1.0), c.y);
}
// Simplified PBR BRDF for realtime SDF marching
// Based on Cook-Torrance microfacet model with simplifications for performance

// GGX/Trowbridge-Reitz normal distribution function
float distributionGGX(vec3 N, vec3 H, float roughness) {
    float a = roughness * roughness;
    float a2 = a * a;
    float NdotH = max(dot(N, H), 0.0);
    float NdotH2 = NdotH * NdotH;
    
    float num = a2;
    float denom = (NdotH2 * (a2 - 1.0) + 1.0);
    denom = 3.14159265 * denom * denom;
    
    return num / denom;
}

// Schlick's approximation for Fresnel
vec3 fresnelSchlick(float cosTheta, vec3 F0) {
    return F0 + (1.0 - F0) * pow(clamp(1.0 - cosTheta, 0.0, 1.0), 5.0);
}

// Simplified geometry function (faster than full Smith model)
float geometrySchlickGGX(float NdotV, float roughness) {
    float r = (roughness + 1.0);
    float k = (r * r) / 8.0;
    
    float num = NdotV;
    float denom = NdotV * (1.0 - k) + k;
    
    return num / denom;
}

float geometrySmith(vec3 N, vec3 V, vec3 L, float roughness) {
    float NdotV = max(dot(N, V), 0.0);
    float NdotL = max(dot(N, L), 0.0);
    float ggx2 = geometrySchlickGGX(NdotV, roughness);
    float ggx1 = geometrySchlickGGX(NdotL, roughness);
    
    return ggx1 * ggx2;
}

// Main BRDF function
// N: surface normal
// V: view direction (towards camera)
// L: light direction (towards light)
// albedo: base color
// metallic: metallic factor (0.0 = dielectric, 1.0 = metallic)
// roughness: surface roughness (0.0 = mirror, 1.0 = completely rough)
vec3 brdf(vec3 N, vec3 V, vec3 L, vec3 albedo, float metallic, float roughness) {
    vec3 H = normalize(V + L);
    
    // Calculate F0 (surface reflection at zero incidence)
    vec3 F0 = vec3(0.04); // Default dielectric value
    F0 = mix(F0, albedo, metallic);
    
    // Calculate angles
    float NdotL = max(dot(N, L), 0.0);
    float NdotV = max(dot(N, V), 0.0);
    float HdotV = max(dot(H, V), 0.0);
    
    // Cook-Torrance BRDF terms
    float D = distributionGGX(N, H, roughness);
    float G = geometrySmith(N, V, L, roughness);
    vec3 F = fresnelSchlick(HdotV, F0);
    
    // Calculate specular
    vec3 numerator = D * G * F;
    float denominator = 4.0 * NdotV * NdotL + 0.0001; // Add small value to prevent divide by zero
    vec3 specular = numerator / denominator;
    
    // Calculate diffuse
    vec3 kS = F; // Specular contribution
    vec3 kD = vec3(1.0) - kS; // Diffuse contribution
    kD *= 1.0 - metallic; // Metallic surfaces don't have diffuse
    
    vec3 diffuse = kD * albedo / 3.14159265; // Lambertian diffuse
    
    // Combine diffuse and specular
    return (diffuse + specular) * NdotL;
}



void cubeflect(inout vec3 p){
    float ax=abs(p.x);
            float ay=abs(p.y);
            float az=abs(p.z);
            float big=max(ax,max(ay,az));
            float mid;
            float low;
            if(big==ax){
                mid=max(ay,az);
                low=min(ay,az);
            }
            else if(big==ay){
                mid=max(ax,az);
                low=min(ax,az);
            }
            else{
                mid=max(ax,ay);
                low=min(ax,ay); 
            }
            p.yxz=vec3(big,mid,low);
            return;
}
float sdBox( vec3 p, vec3 b )
{
  vec3 q = abs(p) - b;
  return length(max(q,0.0)) + min(max(q.x,max(q.y,q.z)),0.0);
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
float sdTorus( vec3 p, vec2 t )
{
  vec2 q = vec2(length(p.xz)-t.x,p.y);
  return length(q)-t.y;
}
//#define KAL 1
#ifdef KAL
//space fold on the position
void kalTransform(inout vec2 pos,inout vec2 vel){
    float wedge = 3.1415926*2/3.;
    float old_angle = atan(pos.y,pos.x);
    float new_angle = mod(old_angle+wedge/2.,wedge)-wedge/2.;//new angle is restricted to -wedge/2, wedge/2
    pR(pos,old_angle-new_angle);
    pR(vel,old_angle-new_angle);
    if(pos.y<0){
        pos = reflect(pos,vec2(0,1));
        vel = reflect(vel,vec2(0,1));
    }
}
#endif

float map_hmap(sampler2D sam,vec3 p){
            #ifdef KAL
            vec2 dum=vec2(0);
            kalTransform(p.xz,dum);
            #endif
    float hval = .05125*length(texture(sam,p.xz/2.+.5).xyz);//getBicubic(sam,p.xz/2+.5);
    //hval = .151*pow(max(hval,0),.5);//-.18+log(1+hval);
    float result = p.y-.42*hval;
    return .25*result;
}
MR mapMin(MR a,MR b){
return a.dts<b.dts?a:b;
}

MR map(vec3 pos){
    vec3 opos=pos;
    MR result;
    MR ground = MR(0,MatId(2,vec2(0)));
    //pos.y=abs(pos.y)+.003;
    pos/=2;
    vec3 ppos = pos;
    ground.dts=map_hmap(prevPass,ppos);
    ground.dts*=2;
    ground.dts=max(ground.dts,sdBox(pos,vec3(1)));
    ground.medium.uv = pos.xz/2.+.5;

    MR base = MR(opos.y-.0031,MatId(1,vec2(0)));
    result = mapMin(ground,base);////
    return result;
}


////////////SCENE TRAVERSAL
vec3 calcNormal( in vec3 p ) // for function f(p)
{
    const float h = 0.00031;      // replace by an appropriate value
    #define ZERO int(min(resolution.x,0)) // non-constant zero to prevent inlining
    vec3 n = vec3(0.0);
    for( int i=ZERO; i<4; i++ )
    {
        vec3 e = 0.5773*(2.0*vec3((((i+3)>>1)&1),((i>>1)&1),(i&1))-1.0);
        n += e*map(p+e*h).dts;
    }
    return normalize(n);
}

float march(inout Ray r, out Hit hit_data,float max_extent){
    float extent = 0;
    MR mapping;
    for(int i = 0; i< MAX_MARCH_STEPS && extent < max_extent; i++){
        r.pos = r.ori+r.dir*extent;
        mapping = map(r.pos);
        float absDts=abs(mapping.dts);
        if(absDts < MARCH_HIT_DIST){ //handle hit
            MatId old_medium = mapping.medium;
            vec3 hit_norm = calcNormal(r.pos);
            MR hit_map = map(r.pos-hit_norm*absDts*HOP_ACROSS_SCALE);
            hit_data = Hit(r,hit_norm,old_medium,hit_map.medium,true);
            return extent;
        }
        else{
            extent += absDts;
        }
    }
    hit_data = Hit(r,vec3(0),mapping.medium,mapping.medium,false);
    return min(extent,max_extent);
}

uniform vec3 cam_pos;
uniform vec2 cam_ori;
vec3 getCamPos(){
    return cam_pos;
    //return texture(orienter,vec2(.75)).xyz;
}
vec2 getCamAngles(){
    return cam_ori;//vec2(-1);
//return texture(orienter,vec2(.25)).xy;
}
void rotateCam(inout vec3 dir,vec2 angles){
pR(dir.yz,angles.y);
pR(dir.xz,angles.x);

}
Ray get_cam_ray(vec2 uv){
    vec3 ori=getCamPos();
    vec3 dir = normalize(vec3(uv,1.));
    rotateCam(dir,getCamAngles());
    return Ray(ori,dir,ori);
}
vec3 get_color(MatId id,vec3 norm){
    if(id.id == 1){
    return vec3(.4);
    //return vec3(.6,.5,.2)*min(vec3(.21),texture(prevPass,id.uv/2+.5).xyz);//vec3(abs(sin(id.uv*3.14))*.1,.1);
    }
    if(id.id == 2){
        //return hsv2rgb(vec3(0,1,1-norm.y));
    vec3 cancol =texture(prevPass,id.uv).xyz;
    cancol= rgb2hsv(cancol);
    float sat = 0.3;
    return hsv2rgb(vec3(cancol.x,sat,.2));//vec3(.1,.1,.1)+cancol;
    }
    return vec3(.2,.2,.1);
}
vec3 directLight(vec3 light_source,vec3 light_col,Hit hit_data,bool point_light){
    vec3 shaded_pt = hit_data.ray_in.pos+hit_data.normal*SHADOW_EPSILON;
    vec3 offset = shaded_pt-light_source;
    
    float shadow_extent = length(offset);
    vec3 dir = offset/shadow_extent;
    Ray r;
    r.ori = light_source;
    r.dir = dir;
    r.pos = light_source;
    Hit dummy;
    float line_of_sight_extent = march(r,dummy,shadow_extent);
    if(abs(line_of_sight_extent-shadow_extent)>SHADOW_EPSILON){return vec3(0);}
    vec3 albedo = get_color(hit_data.new_medium,hit_data.normal);
    if(point_light){light_col *= 1./dot(offset,offset);}
    //vec3 result = albedo*light_col*max(-dot(dir,hit_data.normal),0);
    float metal= .0725;
    float rough = .135;
    if(hit_data.new_medium.id==1){metal = 0.5; rough = .85;}
    vec3 result = light_col*brdf(hit_data.normal,-hit_data.ray_in.dir,-dir,albedo,metal,rough);
    return result;
}
void main(void)
{   init_rng(texcoord,time);
    vec2 uv = -1. + 2. * texcoord;
    uv*=resolution/(max(resolution.x,resolution.y));
    //uv is now a rectangle inscribed in the unit square such that (0,1) and (1,0) have the same screenspace length
    
    Ray cam_ray = get_cam_ray(uv);
    Hit hit_data;
    float ray_extent = march(cam_ray,hit_data,MAX_MARCH_DIST);
    
    //SHADING
    vec3 color = vec3(0);
    if(hit_data.hitQ)
    color += directLight(vec3(4,4,1),vec3(200),hit_data,true);
    else{
        color = vec3(0);//miss/sky color
    }
    //color += directLight(cam_ray.ori,vec3(20),hit_data,true);
    //SHADING
    
    
    
    //vec2 tx = vec2(0);
    //tx.x = dot(hit_data.normal,normalize(vec3(1,0.8,0)));
    fragColor =vec4(color,1); //vec4(float(hitQ)*0.09,tx,1);
    
}