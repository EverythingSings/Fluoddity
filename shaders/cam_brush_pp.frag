#version 430
        
        in vec2 texcoord;
        out vec4 fragColor;
        uniform sampler2D brush;
        uniform sampler2D can;

        uniform vec2 cam_pos;
        uniform float cam_zoom;
        uniform vec2 tex_size;
        uniform vec2 window_size;
        
        vec2 screen_tex_to_can(vec2 tex_coords){
            //transform uv coords on screen to canvas coords. 
            vec2 pos = tex_coords * 2 - 1;
                            float tex_aspect = tex_size.x / tex_size.y;
            float window_aspect = window_size.x / window_size.y;
            
            // Calculate scale to fit texture in window
            vec2 scale;
            if (tex_aspect > window_aspect) {
                // Texture is wider than window - fit by width
                scale.x = 1.0;
                scale.y = window_aspect / tex_aspect;
            } else {
                // Texture is taller than window - fit by height  
                scale.x = tex_aspect / window_aspect;
                scale.y = 1.0;
            }
                
                pos*=cam_zoom;
                pos+=cam_pos*vec2(1,-1);
                pos/=scale;
            return (pos+1)/2;
        }
        void main() {
            vec4 can = texture(can,screen_tex_to_can(texcoord));
            vec2 mags = (abs(screen_tex_to_can(texcoord)-.5));
            if(mags.x>.5||mags.y>.5){can=vec4(0);}
            fragColor=texture(brush,texcoord);
            //SYNC WITH SAVE_FRAME_GPU.PY!!!!!!!!!!!!
            if(length(fragColor.xyz)>0)
            fragColor.xyz/=pow(length(fragColor.xyz),.575);
        }