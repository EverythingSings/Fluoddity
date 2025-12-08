// Smart RBF: 8D input via 2×vec4, up to 4D output
struct RbfCenter {
    vec4 pos0;
    vec4 pos1;   // 8D position (2×vec4)
    vec4 weight; // 4D weight
};

float rbf_kernel(float x) {
    return cos(6*x);
}

vec4 rbf_noise(RbfCenter[10] centers, vec4 pos0,vec4 pos1) {
    vec4 result = vec4(0.0);

    for(int i = 0; i < 10; i++) {
        // Efficient distance calculation
        float dist = sqrt(
            dot(pos0 - centers[i].pos0, pos0 - centers[i].pos0) +
            dot(pos1 - centers[i].pos1, pos1 - centers[i].pos1)
        );

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

RbfCenter[10] generate_random_centers(float seed) {
    RbfCenter[10] centers;

    for(int i = 0; i < 10; i++) {
        // First vec4 (components 0-3)
        centers[i].pos0.x = hash(vec2(seed, float(i * 12 + 0))) * 2.0 - 0.5;
        centers[i].pos0.y = hash(vec2(seed, float(i * 12 + 1))) * 2.0 - 0.5;
        centers[i].pos0.z = hash(vec2(seed, float(i * 12 + 2))) * 2.0 - 0.5;
        centers[i].pos0.w = hash(vec2(seed, float(i * 12 + 3))) * 2.0 - 0.5;

        // Second vec4 (components 4-7)
        centers[i].pos1.x = hash(vec2(seed, float(i * 12 + 4))) * 2.0 - 0.5;
        centers[i].pos1.y = hash(vec2(seed, float(i * 12 + 5))) * 2.0 - 0.5;
        centers[i].pos1.z = hash(vec2(seed, float(i * 12 + 6))) * 2.0 - 0.5;
        centers[i].pos1.w = hash(vec2(seed, float(i * 12 + 7))) * 2.0 - 0.5;
        centers[i].weight.x = hash(vec2(seed, float(i * 12 + 8))) * 2.0 - 1.0;
        centers[i].weight.y = hash(vec2(seed, float(i * 12 + 9))) * 2.0 - 1.0;
        centers[i].weight.z = hash(vec2(seed, float(i * 12 + 10))) * 2.0 - 1.0;
        centers[i].weight.w = hash(vec2(seed, float(i * 12 + 11))) * 2.0 - 1.0;
    }

    return centers;
}

vec4 random_rbf_noise(vec4 pos0,vec4 pos1, float seed) {
    RbfCenter[10] centers = generate_random_centers(seed);
    return rbf_noise(centers, pos0,pos1);
}

vec4 normalized_rbf_noise(vec4 pos0,vec4 pos1, float seed) {
    vec4 noise = random_rbf_noise(pos0,pos1, seed);
    return noise * 0.1 + 0.5;
}

// Example usage for 8D→4D:
// vec4[2] pos8d = vec4[2](vec4(0.1, 0.2, 0.3, 0.4), vec4(0.5, 0.6, 0.7, 0.8));
// vec4 noise4d = random_rbf_noise(pos8d, 42.0);