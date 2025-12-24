#version 450
#define EDGE_BOUNCE true
layout(local_size_x = 64) in;

//SAME STRUCT USED IN BRUSH.VERT AND CAM_BRUSH.VERT
struct Entity {
    vec2 pos;
    vec2 vel;
    float size;
    float padding[3];  // Align to 16-byte boundary for vec4
    vec4 color;
};  // Total: 48 bytes (12 floats)
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
uniform float STRAFE_POWER;
uniform float SENSOR_ANGLE;
uniform float GLOBAL_FORCE_MULT;
uniform float SENSOR_DISTANCE;
uniform float AXIAL_FORCE;
uniform float LATERAL_FORCE;
uniform float SENSOR_GAIN;
uniform float MUTATION_SCALE;
uniform float HUE_SENSITIVITY;
uniform bool COLOR_BY_COHORT;
////////////////////////////////////
//FOURIER NOISE IS IMPORTED INTO THIS SHADER
//FROM fourier4_4.glsl
////////////////////////////////////

//rotate p around origin by angle a
void pR(inout vec2 p, float a) {
	p = cos(a)*p + sin(a)*vec2(p.y, -p.x);
}

#define PI 3.1415926
//convert p to texture coords and retrieve canvas
vec4 get_can(vec2 p){
    vec2 res=textureSize(canvas,0);
    vec2 aspect=vec2(1,res.x/res.y);
    return texture(canvas,(p/2*aspect+.5));
}

vec2 safenorm(vec2 p){
    return length(p)==0?vec2(0):normalize(p);
}

#define COHORTS 64 //each cohort gets it's own rule and starting location.
#define ACTIVE_COUNT 600000 //Supports up to the size of the entity buffer. 
                            //Entities with index > ACTIVE_COUNT aren't rendered or updated

float get_cohort(uint index) {
    return float(COHORTS) * float(index) / float(ACTIVE_COUNT);
}

//Return all entities to their initialization state
void reset(uint index){

    float size=index<ACTIVE_COUNT?.0015: 0;
    float cohort_val = get_cohort(index);
    
    vec4 color=vec4(0,0,1,.045);
    //set pos and vel to small random values
    vec2 pos=.019*vec2(hash(vec2(cohort_val)),hash(vec2(cohort_val+index+2.142)));
    vec2 vel=.005*(vec2(hash(vec2(cohort_val,index)),hash(vec2(cohort_val,pos.y)))*2-1);

    //position different cohorts at different places
    float spots=COHORTS;
    float spot_rows=ceil(sqrt(spots));
    vec2 gridcell=vec2(int(cohort_val)%int(spot_rows),(int(cohort_val))/int(spot_rows));
    pR(pos,floor(cohort_val)*3.1415*2*spots);
    pos+=1.8*((gridcell)/spot_rows-.45);

    //store to persistent entity buffer
    entities[index]=Entity(pos,vel,size,float[3](0,0,0),color);
}

//randomly change noise function parameters, scaled by parameter amount. 
//Each cohort gets a unique mutation for any given rule
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

//Somewhat arbitrary generator of functions with 4 float inputs and 4 float outputs,
//varying rule should smoothly change the behavior of the function
vec4 black_box(vec2 L,vec2 R,Rule rule){
    return (fourier_noise(rule.centers, vec4(L,R)));
}

//reflect across the y axis (bilateral symmetry in the local coordinates vec2(forward, left) )
vec2 flect(vec2 p){
    return p*vec2(1,-1);
}

//reflect across the boundary [-1,1] to keep things inside a square
float edgeflect(float x){
    return sign(x)*(1-abs(1-abs(x)));
}

vec4 sym(out vec2 strafe,vec2 L,vec2 R,vec2 axis,Rule rule){
    vec2 n=safenorm(axis);
    vec2 on=n;
    pR(on,3.14159/2);
    L=vec2(dot(L,n),dot(L,on));
    R=vec2(dot(R,n),dot(R,on));
    vec4 baseterm= black_box(L,R,rule);
    vec4 mirrorterm=black_box(flect(R),flect(L),rule);
    vec2 cols = baseterm.xy+(mirrorterm.xy); //basically just direct output of black_box
    strafe = baseterm.zx + flect(mirrorterm.zx);
    vec2 force = baseterm.xy+flect(mirrorterm.xy);
    force=n*force.x*AXIAL_FORCE+on*force.y*LATERAL_FORCE;
    force=force*.051*2.;
    strafe = n*strafe.x*AXIAL_FORCE + on * strafe.y * LATERAL_FORCE;
    force/=20;
    strafe/=20;
    return vec4(force,cols)/2;
}

void main() {
    uint index = gl_GlobalInvocationID.x;
    if (index >= ENTITY_COUNT) return;

    // Inactive entities get zeroed out. Position offscreen so they don't accidentally get clicked on
    if (index >= ACTIVE_COUNT) {
        entities[index] = Entity(vec2(10000), vec2(0), 0.0, float[3](0,0,0), vec4(0));
        return;
    }

    if (frame_count==0){reset(index);return;}

    Entity e=entities[index];
    float cohort = get_cohort(index);

    float samplen = .005 * SENSOR_DISTANCE;
    vec2 vds = safenorm(e.vel)*samplen;
    vec2 left_sensor_offset = vds;
    vec2 right_sensor_offset = vds;
    pR(left_sensor_offset,SENSOR_ANGLE*PI);
    pR(right_sensor_offset,-SENSOR_ANGLE*PI);

    vec4 ltap = get_can(e.pos+left_sensor_offset);
    vec4 rtap = get_can(e.pos+right_sensor_offset);

    Rule current_rule=target_rule;
    if(current_rule.centers[0].frequency==vec4(0) && current_rule.centers[5].amplitude==vec4(0)){
        current_rule = Rule(generate_random_centers(floor(cohort)));
    }
    mutate_rule(current_rule,MUTATION_SCALE,floor(cohort));

    float tap_scaling = 38.855*SENSOR_GAIN;
    ltap *= tap_scaling;
    rtap *= tap_scaling;

    vec2 strafe =vec2(0);
    vec4 noiseval=sym(strafe,ltap.xy,rtap.xy,e.vel,current_rule);

    noiseval.xy *= GLOBAL_FORCE_MULT;
    strafe *= GLOBAL_FORCE_MULT;

    vec2 force=(noiseval.xy);

    //e.color is interpreted as vec4(hue,saturation,brightness,alpha)
    //We just set brightness to 1 and modulate hue and saturation
    e.color.y = .75;
    
    e.color.x = HUE_SENSITIVITY*noiseval.z;//hue can be anything
    e.color.y = sin(noiseval.w)/2.+.5;//saturation must be 0..1
    if(COLOR_BY_COHORT) {e.color.x = hash(vec2(floor(cohort)));} //just assign a color to each cohort
    e.color.z=1;//brightness 1.
    e.color.w=0.045; //low alpha

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
    e.pos += strafe*STRAFE_POWER;

    entities[index]=e;
    rules[index] = current_rule;
}
