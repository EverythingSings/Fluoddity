#version 450
#define EDGE_BOUNCE true
layout(local_size_x = 64) in;

//SYNC WITH BRUSH.VERT AND CAM_BRUSH.VERT
struct Entity {
    vec2 pos;
    vec2 vel;
    float size;
    float padding;
    vec4 color;
};
struct Rule {
    FourierCenter centers[10];
};
layout(std430, binding = 0) buffer EntityBuffer {
    Entity entities[];
};
layout(std430, binding = 2) buffer RuleBuffer {
    Rule rules[];
};
uniform int frame_count;
uniform Rule target_rule;
uniform vec2 canvas_resolution;
uniform sampler2D canvas;
uniform float DRAG;
uniform float STRAFE_SCALE;
uniform float TAP_STRETCH;
uniform float RULE_OUTPUT_GAIN;
uniform vec4 sliders;

vec3 rgb2hsv(vec3 c)
{
    vec4 K = vec4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0);
    vec4 p = mix(vec4(c.bg, K.wz), vec4(c.gb, K.xy), step(c.b, c.g));
    vec4 q = mix(vec4(p.xyw, c.r), vec4(c.r, p.yzx), step(p.x, c.r));

    float d = q.x - min(q.w, q.y);
    float e = 1.0e-10;
    return vec3(abs(q.z + (q.w - q.y) / (6.0 * d + e)), d / (q.x + e), q.x);
}

void pR(inout vec2 p, float a) {
	p = cos(a)*p + sin(a)*vec2(p.y, -p.x);
}

#define PI 3.1415926

vec4 get_can(vec2 p){
    vec2 res=textureSize(canvas,0);
    vec2 aspect=vec2(1,res.x/res.y);
    return texture(canvas,(p/2*aspect+.5));
}

vec2 safenorm(vec2 p){
    return length(p)==0?vec2(0):normalize(p);
}

#define COHORTS 64
#define ACTIVE_COUNT 600000

float get_cohort(uint index) {
    return float(COHORTS) * float(index) / float(ACTIVE_COUNT);
}

void reset(uint index){
    vec2 pos=vec2(0);
    vec2 vel=-vec2(.0091,0);
    float size=0;
    float cohort_val = get_cohort(index);
    pR(vel,index/float(ACTIVE_COUNT)*2*3.1415);
    if(index<ACTIVE_COUNT){size=.0015;}
    vec4 color=vec4(cohort_val*6,.95*0,0,.012*3*1.25);
    pos=.019*vec2(hash(vec2(cohort_val)),hash(vec2(cohort_val+index+2.142)));
    vel=.005*(vec2(hash(vec2(cohort_val,index)),hash(vec2(cohort_val,pos.y)))*2-1);
    float spots=COHORTS;
    float spot_rows=sqrt(spots);
    vec2 gridcell=vec2(int(cohort_val)%int(spot_rows),(int(cohort_val))/int(spot_rows));
    pR(pos,floor(cohort_val)*3.1415*2*spots);
    pos+=1.8*((gridcell)/spot_rows-.45);

    entities[index]=Entity(pos,vel,size,0.0,color);
}

void mutate_rule(inout Rule current_rule,float amount,float cohort){
    float seed = hash(current_rule.centers[4].frequency.xy+current_rule.centers[7].amplitude.ys+current_rule.centers[1].frequency.zw)+cohort;

    for(int i = 0; i < 10; i++) {
        vec4 freq_mutation = amount * 0.5 * (-1.0 + 2.0 * hash4(vec2(i+seed,-i)));
        current_rule.centers[i].frequency += freq_mutation;

        vec4 amp_mutation = amount * (-1.0 + 2.0 * hash4(-.5+vec2(-i+seed,i)));
        current_rule.centers[i].amplitude += amp_mutation;

        current_rule.centers[i].frequency *= 1 + amount * 0.5 * (hash(vec2(seed,i))-.5);
    }
}

vec4 exnoise(vec2 L,vec2 R,Rule rule){
    return (fourier_noise(rule.centers, vec4(L,R)));
}

vec2 flect(vec2 p){
    return p*vec2(1,-1);
}

float edgeflect(float x){
    return sign(x)*(1-abs(1-abs(x)));
}

vec4 sym(out vec2 strafe,vec2 L,vec2 R,vec2 axis,Rule rule){
    vec2 n=safenorm(axis);
    vec2 on=n;
    pR(on,3.14159/2);
    L=vec2(dot(L,n),dot(L,on));
    R=vec2(dot(R,n),dot(R,on));

    vec4 baseterm= exnoise(L,R,rule);
    vec4 mirrorterm=exnoise(flect(R),flect(L),rule);
    vec2 cols = baseterm.zw+(mirrorterm.zw);
    strafe = baseterm.zx + flect(mirrorterm.zx);
    vec2 force = baseterm.xy+flect(mirrorterm.xy);
    force=n*force.x*sliders.x+on*force.y*sliders.y;
    force=force*.051*2.;
    strafe = n*strafe.x*sliders.x + on * strafe.y * sliders.y;
    force/=20;
    strafe/=20;
    return vec4(force,cols)/2;
}

void main() {
    uint index = gl_GlobalInvocationID.x;
    if (index >= ENTITY_COUNT) return;

    // Inactive entities get zeroed out
    if (index >= ACTIVE_COUNT) {
        entities[index] = Entity(vec2(0), vec2(0), 0.0, 0.0, vec4(0));
        return;
    }

    if (frame_count==0){reset(index);return;}

    Entity e=entities[index];
    float cohort = get_cohort(index);

    float samplen = 3*.0016;
    vec2 vds = safenorm(e.vel)*samplen;
    vec2 vds_prime = vds;
    pR(vds_prime,3.14159*.5);

    vec4 ltap = get_can(e.pos+vds_prime*1+TAP_STRETCH*vds);
    vec4 rtap = get_can(e.pos-vds_prime*1+TAP_STRETCH*vds);

    Rule current_rule=target_rule;
    if(current_rule.centers[0].frequency==vec4(0) && current_rule.centers[5].amplitude==vec4(0)){
        current_rule = Rule(generate_random_centers(floor(cohort)));
    }
    mutate_rule(current_rule,sliders.w,floor(cohort));

    float tap_scaling = 15.542*.5*sliders.z*5;
    ltap *= tap_scaling;
    rtap *= tap_scaling;

    pR(ltap.xy,-PI/3);
    pR(rtap.xy,PI/3);
    vec2 strafe =vec2(0);
    vec4 noiseval=sym(strafe,ltap.xy,rtap.xy,e.vel,current_rule);

    noiseval *= RULE_OUTPUT_GAIN;
    strafe *= RULE_OUTPUT_GAIN;

    vec2 force=(noiseval.xy);

    e.color.xy=vec2(cohort/float(COHORTS),0.75);
    e.color.z=1;

    e.vel = e.vel*DRAG + force;

    if(EDGE_BOUNCE){
        if (e.pos.x < -1.0 || e.pos.x > 1.0){
            e.vel.x=-e.vel.x;
            e.pos.x=edgeflect(e.pos.x);
        }
        float y_edge = canvas_resolution.y/canvas_resolution.x;
        if (e.pos.y < -y_edge || e.pos.y > y_edge){
            e.vel.y=-e.vel.y;
            e.pos.y=edgeflect(e.pos.y/y_edge)*y_edge;
        }
    }
    e.pos += e.vel;
    e.pos += strafe*STRAFE_SCALE;

    entities[index]=e;
    rules[index] = current_rule;
}
