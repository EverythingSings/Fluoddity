#version 450
#define POS_SCALE 1.
#define EDGE_BOUNCE true
layout(local_size_x = 64) in;

//SYNC WITH BRUSH.VERT
struct Entity {
    vec2 pos;
    vec2 vel;
    int status_code; //0 means kill me, -1 means dead and on the free_list
    float size;
    float depth;
    float spare2;
    vec4 color;
    uint lock;
    uint padding0;
    uint padding1;
    uint padding2;
};
layout(std430, binding = 0) buffer EntityBuffer {
    Entity entities[];
};
uniform int frame_count;
uniform float dt;
uniform vec2 canvas_resolution;
uniform sampler2D canvas;
uniform vec4 sliders;


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
    return texture(canvas,(p/2*aspect+.5));
}
float rand(vec2 co){
    return fract(sin(dot(co.xy ,vec2(12.9898,78.233))) * 43758.5453);
}
void pR(inout vec2 p, float a) {
	p = cos(a)*p + sin(a)*vec2(p.y, -p.x);
}
vec2 trace_polygon(float t, int sides) {
    float n = float(sides);
    float phase = mod(t * n, n);
    int edge = int(phase);
    float s = fract(phase);
    
    // Generate vertices for current edge
    float angle1 = 2.0 * 3.14159265359 * float(edge) / n;
    float angle2 = 2.0 * 3.14159265359 * float(edge + 1) / n;
    
    vec2 v1 = vec2(cos(angle1), sin(angle1));
    vec2 v2 = vec2(cos(angle2), sin(angle2));
    
    return mix(v1, v2, s);
}

#define START_COUNT 6
void reset(uint index){
    int rowlen=int(sqrt(ENTITY_COUNT));
    vec2 pos=vec2(0);
    vec2 vel=vec2(.091,0);
    int status= 0;
    float size=0;
    float depth=0;
    float spare2=0;
    pR(vel,index/float(START_COUNT)*2*3.1415);
    if(index<START_COUNT){status=600;size=.01;spare2=float(index)/float(START_COUNT);}
    vec4 color=vec4(.1,.5,1,1.);
    ////////////////////////////////////////////LOCk
    //if(get_lock(index)){
        entities[index]=Entity(pos,vel,status,size,depth,spare2,color,0,0,0,0);
        release_lock(index);
    //}
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
float pulse(float x){
    return pow(max(sin(x*2),0),12)*.05;
}
float sawtooth(float x){
    return 2*abs(fract(x/2)-.5);
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
        e.status_code=e.status_code-1;
        //fade to red
        //e.color.x=mix(e.color.x,0.,.03);
        //e.color.y=mix(e.color.y,1.,.03);
        //oscilate
        //e.color.x+=cos(float(frame_count)*dt/10.)/40*dt;
    }
    

    //BUSINESS (ONLY SPAWN ON ODD FRAMES)
    int status_index=e.status_code/2;
    if(frame_count%2==1&&status_index==0&&e.depth<6){
        Entity s=Entity(e);
        s.depth+=1;
        s.status_code=30;
        s.size*=.5;
        Entity s2=Entity(s);
        vec2 impulse=.6*e.vel.yx*vec2(-1,1);
        s.vel+=impulse;
        s2.vel-=impulse;
        //spawn(s);
        //spawn(s2);
    }
    pR(e.vel,.1*dt/.62);
    if(e.color.w>0){e.size=float(e.status_code)/600*.2*sawtooth(e.status_code/16.);}
    e.color.w=length(e.vel);
    //FRICTION
    e.vel*=pow(.98,dt);
    // Update position
    e.pos += e.vel * dt;
    // Boundary bouncing

    if(EDGE_BOUNCE){
        if (e.pos.x < -1.0 || e.pos.x > 1.0) e.vel.x = -e.vel.x;
        if (e.pos.y < -1.0*canvas_resolution.y/canvas_resolution.x || e.pos.y > 1.0*canvas_resolution.y/canvas_resolution.x) e.vel.y = -e.vel.y;
        e.pos.x = clamp(e.pos.x, -1.0, 1.0);
        e.pos.y = clamp(e.pos.y, -1.0, 1.0);
    }

        entities[index]=e;
/////////////////////////////////////////END LOCK
release_lock(index);}

}