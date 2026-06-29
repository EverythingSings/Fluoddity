#extension GL_NV_shader_atomic_float : require
#extension GL_NV_gpu_shader5 : require
#extension GL_NV_shader_atomic_fp16_vector : require
// Fourier Feature Network: 6D input -> 6D output
struct FourierCenter {
    vec4 frequency;       // first 4 frequency dimensions
    vec4 amplitude;       // first 4 amplitude/weight dimensions
    vec2 frequency_ext;   // extra 2 frequency dimensions (dims 5-6)
    vec2 amplitude_ext;   // extra 2 amplitude/weight dimensions (channels 5-6)
};


// Fourier basis evaluation: 6D input, returns first 4 output channels
// pos_hi provides dimensions 5-6 of the input (currently passed as vec2(0,0))
vec4 fourier_noise(FourierCenter[10] centers, vec4 pos_lo, vec2 pos_hi) {
    vec4 result = vec4(0.0);

    for(int i = 0; i < 10; i++) {
        // Compute phase from 6D dot product
        float phase = dot(pos_lo, centers[i].frequency)
                    + dot(pos_hi, centers[i].frequency_ext);

        // Add per-center phase offset to break degeneracy at origin
        // Use a deterministic offset based on center index and amplitude values
        float phase_offset =2*float(i) * 0.6283 + centers[i].amplitude.w * 3.14159;

        // Create basis functions from phase with offset
        // Using sin/cos pairs at fundamental and first harmonic for richer representation
        vec4 basis = vec4(
            sin(phase + phase_offset),
            cos(phase + phase_offset * 0.7),  // Different offsets for variety
            sin(phase * 2.0 + phase_offset * 1.3),
            cos(phase * 2.0 + phase_offset * 0.5)
        );

        // Weight and accumulate (first 4 output channels)
        result += centers[i].amplitude * basis;
    }

    return result;
}

// Full 6D output version: returns all 6 channels via out parameters
void fourier_noise_6(FourierCenter[10] centers, vec4 pos_lo, vec2 pos_hi,
                     out vec4 result_lo, out vec2 result_hi) {
    result_lo = vec4(0.0);
    result_hi = vec2(0.0);

    for(int i = 0; i < 10; i++) {
        // Compute phase from 6D dot product
        float phase = dot(pos_lo, centers[i].frequency)
                    + dot(pos_hi, centers[i].frequency_ext);

        float phase_offset = 2*float(i) * 0.6283 + centers[i].amplitude.w * 3.14159;

        // Basis for first 4 output channels (same as fourier_noise)
        vec4 basis_lo = vec4(
            sin(phase + phase_offset),
            cos(phase + phase_offset * 0.7),
            sin(phase * 2.0 + phase_offset * 1.3),
            cos(phase * 2.0 + phase_offset * 0.5)
        );
        // Basis for output channels 5-6 (third harmonic)
        vec2 basis_hi = vec2(
            sin(phase * 3.0 + phase_offset * 1.7),
            cos(phase * 3.0 + phase_offset * 0.3)
        );

        result_lo += centers[i].amplitude * basis_lo;
        result_hi += centers[i].amplitude_ext * basis_hi;
    }
}

// PCG hash - bit-exact across all platforms
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

vec4 hash4(vec2 co){
    return vec4(
        hash(co),
        hash(co*-1+5),
        hash(co.yx-100),
        hash(co.yx*-1 + 25)
    );
}

FourierCenter[10] generate_random_centers(float seed) {
    FourierCenter[10] centers;

    for(int i = 0; i < 10; i++) {
        // Generate frequency vectors (first 4 dims)
        // Bias towards lower frequencies for smoother base behaviors
        // Range: [-2, 2] with bias towards [-1, 1]
        // NOTE: i*8 stride preserved for backward compat with old seeds
        float freq_scale = 1.0 + 2.0 * pow(hash(vec2(seed, float(i * 8 + 0))), 2.0);
        centers[i].frequency.x = (hash(vec2(seed, float(i * 8 + 0))) * 2.0 - 1.0) * freq_scale;
        centers[i].frequency.y = (hash(vec2(seed, float(i * 8 + 1))) * 2.0 - 1.0) * freq_scale;
        centers[i].frequency.z = (hash(vec2(seed, float(i * 8 + 2))) * 2.0 - 1.0) * freq_scale;
        centers[i].frequency.w = (hash(vec2(seed, float(i * 8 + 3))) * 2.0 - 1.0) * freq_scale;

        // Generate amplitude vectors (first 4 dims)
        // Range: [-1, 1]
        centers[i].amplitude.x = hash(vec2(seed, float(i * 8 + 4))) * 2.0 - 1.0;
        centers[i].amplitude.y = hash(vec2(seed, float(i * 8 + 5))) * 2.0 - 1.0;
        centers[i].amplitude.z = hash(vec2(seed, float(i * 8 + 6))) * 2.0 - 1.0;
        centers[i].amplitude.w = hash(vec2(seed, float(i * 8 + 7))) * 2.0 - 1.0;

        // Generate extension fields (dims 5-6)
        // Separate offset range (100+) to avoid collision with original hash seeds
        centers[i].frequency_ext.x = (hash(vec2(seed, float(100 + i * 4 + 0))) * 2.0 - 1.0) * freq_scale;
        centers[i].frequency_ext.y = (hash(vec2(seed, float(100 + i * 4 + 1))) * 2.0 - 1.0) * freq_scale;
        centers[i].amplitude_ext.x = hash(vec2(seed, float(100 + i * 4 + 2))) * 2.0 - 1.0;
        centers[i].amplitude_ext.y = hash(vec2(seed, float(100 + i * 4 + 3))) * 2.0 - 1.0;
    }

    return centers;
}

vec4 random_fourier_noise(vec4 pos, float seed) {
    FourierCenter[10] centers = generate_random_centers(seed);
    return fourier_noise(centers, pos, vec2(0.0));
}

vec4 normalized_fourier_noise(vec4 pos, float seed) {
    vec4 noise = random_fourier_noise(pos, seed);
    return noise * 0.1 + 0.5;
}
