#version 450
#define POS_SCALE 1.
#define EDGE_BOUNCE true
layout(local_size_x = 64) in;

layout(std430, binding = 0) buffer EntityBuffer {
    vec4 entities_pv[ENTITY_COUNT];
    int status_code[ENTITY_COUNT]; //1: alive 0: kill me -1: dead
    float size[ENTITY_COUNT];
    vec2 start_pos[ENTITY_COUNT];
    vec4 color[ENTITY_COUNT];
};
uniform int frame_count;
uniform float dt;
uniform vec2 canvas_resolution;
uniform sampler2D canvas;
vec4 get_can(vec2 p){
    vec2 res=textureSize(canvas,0);
    vec2 aspect=vec2(1,res.x/res.y);
    return texture(canvas,(p/2*aspect+.5));
}
void override_traits(uint index){
    entities_pv[index].zw=.1*normalize(entities_pv[index].zw);//-start_pos[index];
    color[index].xyz=vec3(1);
    //color[index].x=fract(float(index)/ENTITY_COUNT*2);
    //color[index].z*=sin(3.1415*20*float(index)/ENTITY_COUNT);
    color[index].y=0;//mod(float(index)/sqrt(ENTITY_COUNT),1);
    color[index].w=.01;
    size[index]=.001;//length(entities_pv[index].z/5);    
}
void reset(uint index){
    vec2 pos=vec2(0);
    vec2 vel=vec2(0);
    float size=0.01;
    vec4 color=vec4(1,1,1,.01);
}
float rand(vec2 co){
    return fract(sin(dot(co.xy ,vec2(12.9898,78.233))) * 43758.5453);
}
void pR(inout vec2 p, float a) {
	p = cos(a)*p + sin(a)*vec2(p.y, -p.x);
}

void main() {

    uint index = gl_GlobalInvocationID.x;
    override_traits(index);
    //DEAD CELLS DO NOTHING
    if(status_code[index]<0){return;}
    if(status_code[index]==0){
        bool push_success = free_list_push(index);
        status_code[index]=push_success?-1:0; //If we succeeded, cell dies.
    }
    if(status_code[index]>0){
        ///AGING OUT
        //status_code[index]=status_code[index]-1;
    }
    if (frame_count==69420||index >= ENTITY_COUNT) return;
    
    vec4 pos_vel = entities_pv[index];
    vec2 pos = pos_vel.xy;
    
    vec2 vel = pos_vel.zw;
    pos/=POS_SCALE;
    //pR(vel,.015*19.9*dot(pos,pos)*.125*dt/.016);

    //MANDELBROT
    //vec2 force=vec2(0);
    //float x = pos.x;
    //float y = pos.y;
    
    //vec2 targ=vec2(x*x-y*y,2*x*y);//+length(pos)*-pos;//pos*length(pos);
    //force=targ-pos;
    //vec2 force=vec2(0);
    vec2 vds=normalize(vel)*.031;
    vec2 vds_prime=vds.yx*vec2(-1,1)*.52;
    float densityF=get_can(pos+vds).z;
    float densityL=get_can(pos+vds+vds_prime).z;
    float densityR=get_can(pos+vds-vds_prime).z;
    
    float phy=.15;
    if(densityF>densityL &&densityF>densityR){
        //nothing
    }
    else if(densityL<densityR){
        pR(vel,phy);
    }
    else if(densityR<densityL){
        pR(vel,-phy);
    }
    else if(rand(pos+vel*2.1+4.)>.5){
        pR(vel,phy);
    }
    else{
        pR(vel,-phy);
    }
    //vel+=force*dt;

    // Update position
    pos += vel * dt;
    // Boundary bouncing
    pos*=POS_SCALE;
    if(EDGE_BOUNCE){
        if (pos.x < -1.0 || pos.x > 1.0) vel.x = -vel.x;
        if (pos.y < -1.0*canvas_resolution.y/canvas_resolution.x || pos.y > 1.0*canvas_resolution.y/canvas_resolution.x) vel.y = -vel.y;
        pos.x = clamp(pos.x, -1.0, 1.0);
        pos.y = clamp(pos.y, -1.0, 1.0);
    }
    entities_pv[index] = vec4(pos, vel);

}