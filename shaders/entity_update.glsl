#version 450
#define POS_SCALE 1.
#define EDGE_BOUNCE true
#define EDGE_KILL false//(e.depth==1)
layout(local_size_x = 64) in;

//SYNC WITH BRUSH.VERT
struct Entity {
    vec2 pos;
    vec2 vel;
    int status_code; //0 means kill me, -1 means dead and on the free_list
    float size;
    float depth;
    float cohort;
    vec4 color;
    uint lock;
    float padding0;
    float padding1;
    float padding2;
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
uniform float dt;
uniform Rule target_rule;
uniform vec2 canvas_resolution;
uniform sampler2D canvas;
uniform float DRAG;
uniform float STRAFE_SCALE;
uniform float TAP_STRETCH;
uniform float RULE_OUTPUT_GAIN;
uniform sampler2D reference_image;
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
//#define KAL 1 //SYNC WITH camera.frag (march.frag)
#ifdef KAL

//space fold on the position
void kalTransform(inout vec2 pos,inout vec2 vel){
    float wedge = PI*2/3.;
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

#define LOCKVAL 1u
bool get_lock(uint index){
    uint old_val=atomicExchange(entities[index].lock,LOCKVAL);
    if(old_val==LOCKVAL){return false;}
    return true;
}
void release_lock(uint index){
    atomicExchange(entities[index].lock,0);
}

vec4 get_can(vec2 p){
    vec2 res=textureSize(canvas,0);
    vec2 aspect=vec2(1,res.x/res.y);
    #ifdef KAL
    vec2 dum=vec2(0);
    kalTransform(p,dum);
    #endif
    return texture(canvas,(p/2*aspect+.5));
}
float rand(vec2 co){
    return fract(sin(dot(co.xy ,vec2(12.9898,78.233))) * 43758.5453);
}

float pulse(float x,float tight){
    return pow(max(sin(x*2),0),tight);
}
float sawtooth(float x){
    return 2*abs(fract(x/2)-.5);
}
vec2 safenorm(vec2 p){
    return length(p)==0?vec2(0):normalize(p);
}
#define COHORTS 64
#define START_COUNT 600000
void reset(uint index){
    int rowlen=int(sqrt(ENTITY_COUNT));
    vec2 pos=vec2(0);
    vec2 vel=-vec2(.0091,0);
    int status= 0;
    float size=0;
    float depth=0;
    float cohort=0;
    pR(vel,index/float(START_COUNT)*2*3.1415);
    if(index<START_COUNT){status=600;size=.0015;cohort=float(index)/float(START_COUNT);}
    vec4 color=vec4(cohort*6,.95*0,0,.012*3*1.25);
    pos=.019*vec2(hash(vec2(cohort)),hash(vec2(cohort+index+2.142)));
    vel=.005*(vec2(hash(vec2(cohort,index)),hash(vec2(cohort,pos.y)))*2-1);
    float spots=COHORTS;
    float spot_rows=sqrt(spots);
    cohort*= spots;
    vec2 gridcell=vec2(int(cohort)%int(spot_rows),(int(cohort))/int(spot_rows));
    pR(pos,floor(cohort)*3.1415*2*spots);
    pos+=1.8*((gridcell)/spot_rows-.45);

    //pos*=0;
    ////////////////////////////////////////////LOCk
    entities[index]=Entity(pos,vel,status,size,depth,cohort,color,0,0,0,0);
    release_lock(index);
}
void mutate_rule(inout Rule current_rule,float amount,float cohort){
    float seed = hash(current_rule.centers[4].frequency.xy+current_rule.centers[7].amplitude.ys+current_rule.centers[1].frequency.zw)+cohort;

    for(int i = 0; i < 10; i++) {
        // Mutate frequencies (controls where in input space we sample)
        // Smaller mutations for frequencies since they have large effect on behavior
        vec4 freq_mutation = amount * 0.5 * (-1.0 + 2.0 * hash4(vec2(i+seed,-i)));
        current_rule.centers[i].frequency += freq_mutation;

        // Mutate amplitudes (controls output strength)
        vec4 amp_mutation = amount * (-1.0 + 2.0 * hash4(-.5+vec2(-i+seed,i)));
        current_rule.centers[i].amplitude += amp_mutation;

        //mutate frequency
        current_rule.centers[i].frequency *= 1 + amount * 0.5 * (hash(vec2(seed,i))-.5);
        // Occasional octave jump for exploration (5% chance)
        //if(hash(vec2(seed, float(i))) < 0.05 * amount) {
        //    current_rule.centers[i].frequency *= (hash(vec2(seed, float(i+100))) > 0.5 ? 2.0 : 0.5);
        //}
    }
    }

int spawn(Entity e){
    uint pop_result=free_list_pop();
    if (pop_result==INVALID_ID){return -1;}
    
    if(get_lock(pop_result)){
    entities[pop_result]=e;
    release_lock(pop_result);
    }
    else{return -2;}
    return int(pop_result);
}
vec4 exnoise(vec2 L,vec2 R,Rule rule){
    return (rbf_noise(rule.centers, vec4(L,R))); 
}
vec2 flect(vec2 p){
    return p*vec2(1,-1);
}
float  edgeflect(float x){ //Reflects x across -1 and 1.
    return sign(x)*(1-abs(1-abs(x)));
}
vec4 sym(out vec2 strafe,vec2 L,vec2 R,vec2 axis,Rule rule){
    vec2 n=safenorm(axis);
    vec2 on=n;
    pR(on,3.14159/2);
    //n and on are our basis. 
    //convert L and R to axis-space
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
    //if(frame_count%120==119&&index==0){hose();}
    if (index >= ENTITY_COUNT) return;
    if (frame_count==0){reset(index);return;}
    if(entities[index].status_code<0){return;}
    
////////////////////////////////////////////BEGIN LOCK
if(get_lock(index)){
    
    Entity e=entities[index];
    #ifdef KAL
    kalTransform(e.pos,e.vel);
    #endif
    //override_traits(index);
    //DEAD CELLS DO NOTHING
    if(e.status_code==0){
        if(frame_count%2==1){release_lock(index);return;}//ONLY KILL ON EVEN FRAMES
        free_list_push(index);
        e.status_code=-1; //If we succeeded, cell dies.
        
        e.color.w=0;
        e.size=0;
    }
    if(e.status_code>0){
        ///AGING OUT
        //e.status_code=e.status_code-1;
        //fade to red
        //e.color.x=mix(e.color.x,0.,.03);
        //e.color.y=mix(e.color.y,1.,.03);
        //oscilate
        //e.color.x+=cos(float(frame_count)*dt/10.)/40*dt;
    }
    


    //BUSINESS (ONLY SPAWN ON ODD FRAMES)
    int status_index=e.status_code/2;
    float samplen = 3*.0016;//*pow(hash(vec2(frame_count,index)/vec2(10000,ENTITY_COUNT)),2.); //.006;//
    //e.vel*=-1;
    vec2 vds = safenorm(e.vel)*samplen;
    vec2 vds_prime = vds;
    pR(vds_prime,3.14159*.5);
    
    vec4 ltap = get_can(e.pos+vds_prime*1+TAP_STRETCH*vds);
    vec4 rtap = get_can(e.pos-vds_prime*1+TAP_STRETCH*vds);
    //RULE CALCS
    Rule current_rule=target_rule;
    if(current_rule.centers[0].frequency==vec4(0) && current_rule.centers[5].amplitude==vec4(0)){
        current_rule = Rule(generate_random_centers(floor(e.cohort)));
    }
    mutate_rule(current_rule,sliders.w,floor(e.cohort));

    vec4 centap=get_can(e.pos);

    float tap_scaling = 15.542*.5*sliders.z*5;
    ltap *= tap_scaling;
    rtap *= tap_scaling;
    
    pR(ltap.xy,-PI/3);
    pR(rtap.xy,PI/3);
    vec2 strafe =vec2(0);
    vec4 noiseval=sym(strafe,ltap.xy,rtap.xy,e.vel,current_rule);//random_rbf_noise(vec4(.01*(ltap.xy-get_can(e.pos).xy),.01*(rtap.xy-get_can(e.pos).xy)),floor(e.cohort*6));

    // Apply output gain to Fourier network result
    noiseval *= RULE_OUTPUT_GAIN;
    strafe *= RULE_OUTPUT_GAIN;

    vec2 force=(noiseval.xy);

    //ALTERNATE COLORATION MODES. RULE BASED:
    //e.color.xy=fract(noiseval.zw);
    //COHORT BASED COLOR:
    e.color.xy=vec2(e.cohort/float(COHORTS),0.75);
    e.color.z=1;

    //DRAG AND APPLY FORCE 
    e.vel =e.vel*DRAG+ (force)*dt;

if(EDGE_BOUNCE){
        float edge_band=.8;
        
        if (e.pos.x < -1.0 || e.pos.x > 1.0){
            e.vel.x=-e.vel.x;//e.vel.x-=.01*e.pos.x*dt;//e.vel.x = -e.vel.x;
            e.pos.x=edgeflect(e.pos.x);
        }
        float y_edge = canvas_resolution.y/canvas_resolution.x;
        if (e.pos.y < -y_edge || e.pos.y > y_edge){
            e.vel.y=-e.vel.y;// e.vel.y-=.01*e.pos.y*dt; //e.vel.y = -e.vel.y;
            e.pos.y=edgeflect(e.pos.y/y_edge)*y_edge;
        }
        //e.pos.x = clamp(e.pos.x, -1.0, 1.0);
        //e.pos.y = clamp(e.pos.y, -1.0, 1.0);

    }
    e.pos += e.vel * dt;
    e.pos += strafe * dt*STRAFE_SCALE;
    // Boundary bouncing
    
    
    
    if(EDGE_KILL&&e.status_code>0){
        if (e.pos.x < -1.0 || e.pos.x > 1.0 || e.pos.y < -1.0*canvas_resolution.y/canvas_resolution.x || e.pos.y > 1.0*canvas_resolution.y/canvas_resolution.x)
        {e.status_code=0;}
    }
        
    entities[index]=e;
    rules[index] = current_rule;
/////////////////////////////////////////END LOCK
release_lock(index);}

}