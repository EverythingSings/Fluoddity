// Smart RBF: 8D input via 2×vec4, up to 4D output
struct RbfCenter {
    vec4 pos;    // 4D position (vector)
    vec4 weight; // 4D weight
};
uniform vec4 sliders;
float rbf_kernel(float x) {
    x*=10;
    return cos(x);
    //return cos(x);
    //return sin(x);
    //x/=10;
    //float sigma = 0.04;
    //return 10*exp(-(x * x/50/1) / (sigma * sigma));
}

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

// PCG hash - bit-exact across all platforms (replaces fract(sin()) for cross-platform determinism)
uint pcg_hash(uint seed) {
    uint state = seed * 747796405u + 2891336453u;
    uint word = ((state >> ((state >> 28u) + 4u)) ^ state) * 277803737u;
    return (word >> 22u) ^ word;
}

float hash(vec2 co){
    uvec2 u = uvec2(floatBitsToUint(co.x), floatBitsToUint(co.y));
    uint h = pcg_hash(u.x ^ pcg_hash(u.y));
    return float(h) / float(0xffffffffu);
}

// OLD UNSTABLE VERSION (revert if PCG causes issues):
// float hash(vec2 co){
//     return fract(sin(dot(co.xy ,vec2(12.9898,78.233))) * 43758.5453);
// }
vec4 hash4(vec2 co){
    return vec4(
        hash(co),
        hash(co*-1+5),
        hash(co.yx-100),
        hash(co.yx*-1 + 25)
    );
}

RbfCenter[10] generate_random_centers(float seed) {
    RbfCenter[10] centers;

    for(int i = 0; i < 10; i++) {
        centers[i].pos.x = hash(vec2(seed, float(i * 8 + 0))) * 2.0 - 1.;
        centers[i].pos.y = hash(vec2(seed, float(i * 8 + 1))) * 2.0 - 1.;
        centers[i].pos.z = hash(vec2(seed, float(i * 8 + 2))) * 2.0 - 1.;
        centers[i].pos.w = hash(vec2(seed, float(i * 8 + 3))) * 2.0 - 1.;
        centers[i].weight.x = hash(vec2(seed, float(i * 8 + 4))) * 2.0 - 1.0;
        centers[i].weight.y = hash(vec2(seed, float(i * 8 + 5))) * 2.0 - 1.0;
        centers[i].weight.z = hash(vec2(seed, float(i * 8 + 6))) * 2.0 - 1.0;
        centers[i].weight.w = hash(vec2(seed, float(i * 8 + 7))) * 2.0 - 1.0;
    }

    return centers;
}

vec4 random_rbf_noise(vec4 pos, float seed) {
    RbfCenter[10] centers = generate_random_centers(seed);
    return rbf_noise(centers, pos);
}

vec4 normalized_rbf_noise(vec4 pos, float seed) {
    vec4 noise = random_rbf_noise(pos, seed);
    return noise * 0.1 + 0.5;
}
