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
uniform bool DISABLE_SYMMETRY;
uniform bool ABSOLUTE_ORIENTATION;
////////////////////////////CONSTANTS
#define COHORTS 64 //each cohort gets it's own rule and starting location.
#define ACTIVE_COUNT 600000 //Supports up to the size of the entity buffer. 
                            //Entities with index > ACTIVE_COUNT aren't rendered or updated




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
    vec2 vel=0.01*.005*(vec2(hash(vec2(cohort_val,index)),hash(vec2(cohort_val,pos.y)))*2-1);

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


//Used to enforce left-right symmetry in the local coordinates vec2(forward, left)
vec2 y_reflect(vec2 p){
    return p*vec2(1,-1);
}
vec2 x_reflect(vec2 p){
    return p*vec2(-1,1);
}
//reflect across the boundary [-1,1] to keep particle positions from leaving the canvas
float edgeflect(float x){
    return sign(x)*(1-abs(1-abs(x)));
}

//Somewhat arbitrary generator of functions with 4 float inputs and 4 float outputs,
//varying rule should smoothly change the behavior of the function
vec4 black_box(vec2 L,vec2 R,Rule rule){
    return (fourier_noise(rule.centers, vec4(L,R)));
}



//This function determines entity output by plugging sensor values into a noise function called black_box()
//The calculation is performed twice, once in mirrored coordinates, and the two values are averaged.
//This keeps entities from displaying clockwise/counterclockwise bias.
//PARAMETERS:
//--L and R: velocity field measurements from left sensor and right sensor.
//--axis: forward vector that defines our orientation.
//--rule: coefficients for the noise function that dictates entity behavior.
//RETURNS:
//--force: A "push" vector that will be added to entity.vel 
//--strafe: A "hop" vector that will be added to entity.pos and have no effect on velocity
//--color: vec2 to be used as parameters in a coloring function
void calculate_entity_behavior( vec2 L,vec2 R, vec2 axis, Rule rule, out vec2 force, out vec2 strafe, out vec2 color){

    //build a local coordinate frame where "axis" is forward.
    vec2 forward=safenorm(axis);
    vec2 left=vec2(forward.y,-forward.x);

    //Convert L and R to local coordinates.
    //Ie. decompose each into an axial component and a lateral component
    L=vec2(dot(L,forward),dot(L,left));
    R=vec2(dot(R,forward),dot(R,left));

    //calculate black box noise values
    vec4 baseterm= black_box(L,R,rule);
    vec4 mirrorterm=black_box(y_reflect(R),y_reflect(L),rule);
    if(DISABLE_SYMMETRY){mirrorterm = vec4(0);}//disable symmetry by zeroing the mirror term

    //Combine base and mirror terms
    force = baseterm.xy+y_reflect(mirrorterm.xy);
    strafe = baseterm.zw + y_reflect(mirrorterm.zw);

    //Convert force and strafe back to world coordinates
    force=forward*force.x*AXIAL_FORCE+left*force.y*LATERAL_FORCE;
    strafe = forward*strafe.x*AXIAL_FORCE + left * strafe.y * LATERAL_FORCE;

    color = baseterm.xy+(mirrorterm.xy); //Just an arbitrary function of blackbox output. Reuses force terms.
    return;
}

void main() {
    uint index = gl_GlobalInvocationID.x;
    if (index >= ENTITY_COUNT) return;

    // Inactive entities get zeroed out. Position offscreen so they don't accidentally get clicked on
    if (index >= ACTIVE_COUNT) {
        entities[index] = Entity(vec2(10000), vec2(0), 0.0, float[3](0,0,0), vec4(0));
        return;
    }

    //frame_count == 0 signals a simulation reset
    if (frame_count==0){reset(index);return;}

    Entity e=entities[index];
    float cohort = get_cohort(index);

    //Calculate position offsets for the two sensors.
    float sample_dist = .005 * SENSOR_DISTANCE;
    vec2 orientation = safenorm(e.vel);//vector facing the same direction as velocity, with length==samplen

    vec2 left_sensor_offset = orientation*sample_dist;
    vec2 right_sensor_offset = orientation*sample_dist;
    pR(left_sensor_offset,SENSOR_ANGLE*PI);//rotate them opposite directions
    pR(right_sensor_offset,-SENSOR_ANGLE*PI);

    //read the trails from canvas
    vec4 ltap = get_can(e.pos+left_sensor_offset);
    vec4 rtap = get_can(e.pos+right_sensor_offset);

    Rule current_rule=target_rule;
    //if a few coefficients are exactly 0, then assume target_rule is all 0s (no target) and generate a random rule instead.
    if(current_rule.centers[0].frequency==vec4(0) && current_rule.centers[5].amplitude==vec4(0)){
        current_rule = Rule(generate_random_centers(floor(cohort)));
    }
    //Each cohort gets a random mutation
    mutate_rule(current_rule,MUTATION_SCALE,floor(cohort));

    //rescale sensor values
    float sensor_scaling = 38.855*SENSOR_GAIN;
    ltap *= sensor_scaling;
    rtap *= sensor_scaling;

    //compute entity action
    vec2 strafe =vec2(0);
    vec2 force = vec2(0);
    vec2 col_params = vec2(0);
    calculate_entity_behavior(ltap.xy,rtap.xy,orientation,current_rule,force,strafe,col_params);

    //rescale output forces
    force *= GLOBAL_FORCE_MULT/400.;
    strafe *= GLOBAL_FORCE_MULT/20.;


    //e.color is interpreted as vec4(hue,saturation,brightness,alpha)
    //We just set brightness to 1 and modulate hue and saturation
    e.color.x = HUE_SENSITIVITY*col_params.x;//hue can be anything
    e.color.y = sin(col_params.y)/2.+.5;//saturation must be 0..1

    if(COLOR_BY_COHORT) {e.color.x = hash(vec2(floor(cohort)));} //just assign a random hue to each cohort
    e.color.z=1;//brightness 1.
    e.color.w=0.045; //low alpha

    //Accelerate: Apply drag and add force to e.vel,
    e.vel = e.vel*DRAG + force;
    //Move: add e.vel and strafe to e.pos
    e.pos += e.vel;
    e.pos += strafe*STRAFE_POWER;

    //reflect particles off canvas boundaries
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

    //Commit new entity state to buffers
    entities[index]=e;
    rules[index] = current_rule;
}
