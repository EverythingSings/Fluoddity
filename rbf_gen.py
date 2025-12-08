def generate_rbf_glsl_source_extended(num_centers=10, in_dim=3, out_dim=3):
    """
    Enhanced RBF GLSL generator supporting up to 8D input via paired vec4s.
    Much more efficient than arrays while supporting higher dimensions.
    """
    
    def get_glsl_type(dim, is_input=False):
        if dim <= 4:
            return "float" if dim == 1 else f"vec{dim}"
        elif is_input and dim == 8:
            return "vec4[2]"  # Special case: 8D as 2 vec4s
        else:
            return f"float[{dim}]"  # Fallback to arrays
    
    def get_zero_constructor(dim, is_input=False):
        if dim <= 4:
            return "0.0" if dim == 1 else f"vec{dim}(0.0)"
        elif is_input and dim == 8:
            return "vec4[2](vec4(0.0), vec4(0.0))"
        else:
            return f"float[{dim}](0.0)"
    
    def generate_distance_calculation(in_dim):
        if in_dim <= 4:
            return "length(pos - centers[i].pos)"
        elif in_dim == 8:
            return """sqrt(
            dot(pos[0] - centers[i].pos[0], pos[0] - centers[i].pos[0]) +
            dot(pos[1] - centers[i].pos[1], pos[1] - centers[i].pos[1])
        )"""
        else:
            # Fallback to loop for other dimensions
            return f"""({{
            float dist_sq = 0.0;
            for(int d = 0; d < {in_dim}; d++) {{
                float diff = pos[d] - centers[i].pos[d];
                dist_sq += diff * diff;
            }}
            sqrt(dist_sq);
        }})"""
    
    def generate_random_centers_code(num_centers, in_dim, out_dim):
        code = f"""RbfCenter[{num_centers}] generate_random_centers(float seed) {{
    RbfCenter[{num_centers}] centers;
    
    for(int i = 0; i < {num_centers}; i++) {{"""
        
        if in_dim <= 4:
            # Standard vec generation
            components = ['x', 'y', 'z', 'w'][:in_dim]
            for j, comp in enumerate(components):
                if in_dim == 1:
                    code += f"""
        centers[i].pos = hash(vec2(seed, float(i * {in_dim + out_dim} + {j}))) * 2.0 - 0.5;"""
                else:
                    code += f"""
        centers[i].pos.{comp} = hash(vec2(seed, float(i * {in_dim + out_dim} + {j}))) * 2.0 - 0.5;"""
        
        elif in_dim == 8:
            # Special 8D case: two vec4s
            code += f"""
        // First vec4 (components 0-3)
        centers[i].pos[0].x = hash(vec2(seed, float(i * {in_dim + out_dim} + 0))) * 2.0 - 0.5;
        centers[i].pos[0].y = hash(vec2(seed, float(i * {in_dim + out_dim} + 1))) * 2.0 - 0.5;
        centers[i].pos[0].z = hash(vec2(seed, float(i * {in_dim + out_dim} + 2))) * 2.0 - 0.5;
        centers[i].pos[0].w = hash(vec2(seed, float(i * {in_dim + out_dim} + 3))) * 2.0 - 0.5;
        
        // Second vec4 (components 4-7)
        centers[i].pos[1].x = hash(vec2(seed, float(i * {in_dim + out_dim} + 4))) * 2.0 - 0.5;
        centers[i].pos[1].y = hash(vec2(seed, float(i * {in_dim + out_dim} + 5))) * 2.0 - 0.5;
        centers[i].pos[1].z = hash(vec2(seed, float(i * {in_dim + out_dim} + 6))) * 2.0 - 0.5;
        centers[i].pos[1].w = hash(vec2(seed, float(i * {in_dim + out_dim} + 7))) * 2.0 - 0.5;"""
        
        # Output weights (always standard since out_dim <= 4)
        if out_dim <= 4:
            components = ['x', 'y', 'z', 'w'][:out_dim]
            for j, comp in enumerate(components):
                if out_dim == 1:
                    code += f"""
        centers[i].weight = hash(vec2(seed, float(i * {in_dim + out_dim} + {in_dim + j}))) * 2.0 - 1.0;"""
                else:
                    code += f"""
        centers[i].weight.{comp} = hash(vec2(seed, float(i * {in_dim + out_dim} + {in_dim + j}))) * 2.0 - 1.0;"""
        
        code += """
    }
    
    return centers;
}"""
        return code
    
    # Generate the full GLSL code
    in_type = get_glsl_type(in_dim, is_input=True)
    out_type = get_glsl_type(out_dim, is_input=False)
    distance_calc = generate_distance_calculation(in_dim)
    
    code = f"""// Smart RBF: 8D input via 2×vec4, up to 4D output
struct RbfCenter {{
    {in_type} pos;    // {in_dim}D position ({'2×vec4' if in_dim == 8 else 'vector'})
    {out_type} weight; // {out_dim}D weight
}};

float rbf_kernel(float x) {{
    return cos(6*x);
}}

{out_type} rbf_noise(RbfCenter[{num_centers}] centers, {in_type} pos) {{
    {out_type} result = {get_zero_constructor(out_dim)};
    
    for(int i = 0; i < {num_centers}; i++) {{
        // Efficient distance calculation
        float dist = {distance_calc};
        
        float basis = rbf_kernel(dist);
        result += centers[i].weight * basis;
    }}
    
    return result;
}}

float hash(vec2 co){{
    return fract(sin(dot(co.xy ,vec2(12.9898,78.233))) * 43758.5453);
}}

{generate_random_centers_code(num_centers, in_dim, out_dim)}

{out_type} random_rbf_noise({in_type} pos, float seed) {{
    RbfCenter[{num_centers}] centers = generate_random_centers(seed);
    return rbf_noise(centers, pos);
}}

{out_type} normalized_rbf_noise({in_type} pos, float seed) {{
    {out_type} noise = random_rbf_noise(pos, seed);
    return noise * 0.1 + 0.5;
}}

// Example usage for 8D→4D:
// vec4[2] pos8d = vec4[2](vec4(0.1, 0.2, 0.3, 0.4), vec4(0.5, 0.6, 0.7, 0.8));
// vec4 noise4d = random_rbf_noise(pos8d, 42.0);"""

    return code



if __name__ == "__main__":
    print("=== 8D→4D Smart RBF Implementation ===")
    print(generate_rbf_glsl_source_extended(10, 4, 4))
    print("\n" + "="*60)