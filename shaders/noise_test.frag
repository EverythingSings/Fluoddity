        #version 450
        
        in vec2 texcoord;
        out vec4 fragColor;
        
        // RBF structures matching rbf4_4.glsl
        struct RbfCenter {
            vec4 pos;    // 4D position (vector)
            vec4 weight; // 4D weight
        };
        
        struct Rule {
            RbfCenter centers[10];
        };
        
        layout(std430, binding = 2) buffer RuleBuffer {
            Rule rules[];
        };
        
        uniform int u_index;
        uniform int u_frame_count;
        uniform float u_scale;
        
        #define PERIOD 360
        
        // RBF kernel function from rbf4_4.glsl
float rbf_kernel(float x) {
    x*=10;
    //return cos(x);
    //return cos(x);
    //return sin(x);
    x/=10;
    float sigma = 0.04;
    return 10*exp(-(x * x/50/1) / (sigma * sigma));
}
        
        // RBF noise function from rbf4_4.glsl
        vec4 rbf_noise(RbfCenter[10] centers, vec4 pos) {
            vec4 result = vec4(0.0);
            
            for(int i = 0; i < 10; i++) {
                // Efficient distance calculation
                float dist = length(pos - centers[i].pos);
                float basis = rbf_kernel(dist);
                result += centers[i].weight * basis;
            }
            
            return result;
        }
        
        void main() {
            // Map texcoord [0,1] to [-scale, scale] for x and y
            vec2 xy = (texcoord * 2.0 - 1.0) * u_scale;
            
            // Calculate time that cycles from -scale to scale over PERIOD frames
            float time_progress = float(u_frame_count % PERIOD) / float(PERIOD);
            float time = (time_progress * 2.0 - 1.0) * u_scale;
            
            // Create 4D position with time as 3rd dimension, 4th dimension ignored (set to 0)
            vec4 pos = vec4(xy.x, xy.y, time, 0.0);
            
            // Get the centers from the rule at the specified index
            RbfCenter[10] centers = rules[u_index].centers;
            
            // Calculate RBF noise
            vec4 noise = rbf_noise(centers, pos);//+.25*rbf_noise(centers,6*pos.ywzx);
            
            // Assign noise result directly to fragment color
            fragColor = noise;
        }
        