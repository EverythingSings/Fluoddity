#version 430
        
        in vec2 texcoord;
        
        uniform sampler2D brush_tex;
        uniform sampler2D view_brush_tex;
        uniform sampler2D can_tex;
        uniform sampler2D view_can_tex;
        uniform float DRAIN;
        uniform float VIEWDRAIN;
        layout(location = 0) out vec4 can_out;
        layout(location = 1) out vec4 view_can_out;
        
        //////////////TONE MAPPING
        vec3 ACESFilm(vec3 x)
        {
            float a = 2.51f;
            float b = 0.03f;
            float c = 2.43f;
            float d = 0.59f;
            float e = 0.14f;
            return clamp((x*(a*x + b)) / (x*(c*x + d) + e), 0.0f, 1.0f);
        }
        vec3 LessThan(vec3 f, float value)
        {
            return vec3(
                (f.x < value) ? 1.0f : 0.0f,
                (f.y < value) ? 1.0f : 0.0f,
                (f.z < value) ? 1.0f : 0.0f);
        }
        
        vec3 LinearToSRGB(vec3 rgb)
        {
            rgb = clamp(rgb, 0.0f, 1.0f);
            
            return mix(
                pow(rgb, vec3(1.0f / 2.4f)) * 1.055f - 0.055f,
                rgb * 12.92f,
                LessThan(rgb, 0.0031308f)
            );
        }
        
        vec3 SRGBToLinear(vec3 rgb)
        {
            rgb = clamp(rgb, 0.0f, 1.0f);
            
            return mix(
                pow(((rgb + 0.055f) / 1.055f), vec3(2.4f)),
                rgb / 12.92f,
                LessThan(rgb, 0.04045f)
            );
        }
        vec4 getCan(vec2 p,sampler2D sam){
            return texture(sam,p);
        }
        vec4 getBlur(vec2 pos,sampler2D sam){

            ivec2 imsz=textureSize(sam,0);
            vec2 texelSize = 1.0 / vec2(imsz);
            //pos=(floor(pos*vec2(imsz))+.5)/imsz;
            vec3 off=vec3(1./vec2(imsz),0);
            vec2 np=pos+off.zy;
            vec2 sp=pos-off.zy;
            vec2 wp=pos-off.xz;
            vec2 ep=pos+off.xz;
            vec4 nc=getCan(np,sam);
            vec4 sc=getCan(sp,sam);
            vec4 wc=getCan(wp,sam);
            vec4 ec=getCan(ep,sam);
            float K=0;
            return (getCan(pos,sam)*K+nc+sc+wc+ec)/(4.+K);
    }
    
    float sdSegment( in vec2 p, in vec2 a, in vec2 b )
    {
        vec2 pa = p-a, ba = b-a;
        float h = clamp( dot(pa,ba)/dot(ba,ba), 0.0, 1.0 );
        return length( pa - ba*h );
    }
    float sd_grid(vec2 p){
        return length(p)-.3;
    }

        void main() {
            vec4 brush_color = texture(brush_tex, texcoord);
            vec2 view_texcoord=texcoord;
            //view_texcoord=view_texcoord.yx*vec2(1,-1);
            vec4 view_brush_color=texture(view_brush_tex,view_texcoord);
            vec4 can_color = getBlur(texcoord,can_tex);
            //vec4 can_color = texture(can_tex, texcoord);
            //vec4 view_can_color = getBlur(texcoord,view_can_tex);//texture(view_can_tex, texcoord);
            vec4 view_can_color = texture(view_can_tex, texcoord);
            // Additive application: new_color = old_color + brush
            can_out = can_color*DRAIN+(1-DRAIN)*brush_color;
            
            //can_out.xyz=max(vec3(0),can_out.xyz);

            //brush_color.xyz*=.2045;
            //view_brush_color.xyz=ACESFilm(view_brush_color.xyz);
            //view_brush_color.xyz=LinearToSRGB(view_brush_color.xyz);
            view_brush_color.xyz/=pow(length(view_brush_color.xyz)+.01,.575);//vec3(pow(view_brush_color.xyz,vec3(.4)));
            //view_can_out=max(view_can_color,view_brush_color);
            //float alpha=min(1,view_brush_color.w);
            //view_can_out.xyz=mix(view_can_color.xyz*.95, view_brush_color.xyz,alpha);
            
            //view_can_out.xyz=mix(view_can_color.xyz,view_brush_color.xyz,DRAIN);
            
            
            //view_can_out = clamp(view_can_out,vec4(0),vec4(1));
            vec3 BASE_VIEW_COL = 0*vec3(-.25);//0*3.*.2*vec3(0,61,74)/255.;

            //if(sd_grid(texcoord)<0){BASE_VIEW_COL=vec3(1);}
            view_can_out.xyz=VIEWDRAIN*(view_can_color.xyz-BASE_VIEW_COL)+(1-VIEWDRAIN)*view_brush_color.xyz;
            if(VIEWDRAIN==1){view_can_out.xyz=view_can_color.xyz+.001*view_brush_color.xyz;}
            //view_can_out.xyz*=DRAIN;
            view_can_out.xyz+=BASE_VIEW_COL;
        }