"""Parameter definitions and GLSL code generation for the mapping UI demo.

Defines the 12 physics parameters and generates GLSL uniform declarations
and get_X() function bodies based on the selected mapping type.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class ParamDef:
    """Definition for one physics parameter."""
    name: str           # ALL_CAPS name, e.g. 'SENSOR_GAIN'
    label: str          # Display label, e.g. 'Sensor Gain'
    group: str          # 'basics', 'forces', 'advanced'
    default_min: float
    default_max: float
    default_value: float

    @property
    def uniform_base(self) -> str:
        """Lowercase name used in GLSL uniforms, e.g. 'sensor_gain'."""
        return self.name.lower()


# The 12 physics parameters (self-contained, no main project imports)
PARAMS: list[ParamDef] = [
    # --- Basics ---
    ParamDef('SENSOR_GAIN',       'Sensor Gain',       'basics',   0.0,  10.0,  0.116),
    ParamDef('SENSOR_ANGLE',      'Sensor Angle',      'basics',  -1.0,   1.0,  0.45),
    ParamDef('SENSOR_DISTANCE',   'Sensor Distance',   'basics',   0.0,   3.0,  1.0),
    ParamDef('MUTATION_SCALE',    'Mutation Scale',     'basics',   0.0,   1.0,  0.0),
    # --- Forces ---
    ParamDef('GLOBAL_FORCE_MULT', 'Global Force Mult', 'forces',   0.0,   2.0,  1.0),
    ParamDef('DRAG',              'Drag',              'forces',  -1.0,   1.0,  0.504),
    # --- Advanced ---
    ParamDef('AXIAL_FORCE',       'Axial Force',       'advanced', -1.0,  1.0,  0.371),
    ParamDef('LATERAL_FORCE',     'Lateral Force',     'advanced', -1.0,  1.0, -0.707),
    ParamDef('STRAFE_POWER',      'Strafe Power',      'advanced',  0.0,  0.5,  0.224),
    ParamDef('TRAIL_PERSISTENCE', 'Trail Persistence', 'advanced',  0.0,  1.0,  0.938),
    ParamDef('TRAIL_DIFFUSION',   'Trail Diffusion',   'advanced',  0.0,  1.0,  1.0),
    ParamDef('HAZARD_RATE',       'Hazard Rate',       'advanced',  0.0,  0.05, 0.0),
]

PARAM_BY_NAME: dict[str, ParamDef] = {p.name: p for p in PARAMS}

PARAM_GROUPS: dict[str, list[ParamDef]] = {}
for _p in PARAMS:
    PARAM_GROUPS.setdefault(_p.group, []).append(_p)


# ---------------------------------------------------------------------------
# GLSL code generation
# ---------------------------------------------------------------------------

def generate_uniforms_local(param_name: str, mapping) -> str:
    """Generate the local uniforms block for a single parameter.

    Args:
        param_name: ALL_CAPS parameter name
        mapping: MappingState instance (imported type avoided for circular deps)
    """
    from .mapping_menu import MappingType
    base = param_name.lower()

    if mapping.mapping_type == MappingType.NONE:
        return f"uniform float {base}_slider;"

    elif mapping.mapping_type == MappingType.JITTER:
        return (
            f"uniform float {base}_slider;\n"
            f"uniform float {base}_jitter_amount;"
        )

    elif mapping.mapping_type in (MappingType.SWEEP, MappingType.FIELD, MappingType.SHADER):
        return f"uniform float {base}_slider;"

    elif mapping.mapping_type == MappingType.CUSTOM:
        lines = [f"uniform float {base}_slider;"]
        for cs in mapping.custom_sliders:
            uniform_name = _sanitize_uniform_name(cs.display_name)
            lines.append(f"uniform float {uniform_name};")
        return "\n".join(lines)

    return ""


def generate_uniforms_global(all_mappings: dict) -> str:
    """Generate the combined uniforms block for ALL parameters."""
    sections = []
    for pdef in PARAMS:
        mapping = all_mappings.get(pdef.name)
        if mapping is None:
            continue
        local = generate_uniforms_local(pdef.name, mapping)
        if local:
            sections.append(f"// --- {pdef.name} ---\n{local}")
    return "\n\n".join(sections) if sections else "// (no uniforms)"


def generate_function(param_name: str, mapping) -> str:
    """Generate the full get_X() GLSL function for a parameter.

    For Custom mapping type, the function body includes the user's custom_code.
    """
    from .mapping_menu import MappingType
    base = param_name.lower()
    func_name = f"get_{base}"

    if mapping.mapping_type == MappingType.NONE:
        return (
            f"float {func_name}(Entity e){{\n"
            f"\tfloat result = {base}_slider;\n"
            f"\treturn result;\n"
            f"}}"
        )

    elif mapping.mapping_type == MappingType.JITTER:
        return (
            f"float {func_name}(Entity e){{\n"
            f"\tfloat result = {base}_slider;\n"
            f"\tfloat random = hash(vec2(float(frame_count)+result, pos.x + pos.y * 100.0)) * 2.0 - 1.0;\n"
            f"\tresult += random * {base}_jitter_amount;\n"
            f"\treturn result;\n"
            f"}}"
        )

    elif mapping.mapping_type == MappingType.SWEEP:
        return (
            f"float {func_name}(Entity e){{\n"
            f"\tfloat result = {base}_slider;\n"
            f"\t// TODO: Sweep implementation\n"
            f"\treturn result;\n"
            f"}}"
        )

    elif mapping.mapping_type == MappingType.FIELD:
        return (
            f"float {func_name}(Entity e){{\n"
            f"\tfloat result = {base}_slider;\n"
            f"\t// TODO: Field implementation\n"
            f"\treturn result;\n"
            f"}}"
        )

    elif mapping.mapping_type == MappingType.SHADER:
        return (
            f"float {func_name}(Entity e){{\n"
            f"\tfloat result = {base}_slider;\n"
            f"\t// TODO: Shader implementation\n"
            f"\treturn result;\n"
            f"}}"
        )

    elif mapping.mapping_type == MappingType.CUSTOM:
        body = mapping.custom_code if mapping.custom_code else ""
        return (
            f"float {func_name}(Entity e){{\n"
            f"\tfloat result = {base}_slider;\n"
            f"{body}\n"
            f"\treturn result;\n"
            f"}}"
        )

    return ""


def get_function_prefix(param_name: str) -> str:
    """Get the read-only prefix for Custom mode function display."""
    base = param_name.lower()
    return f"float get_{base}(Entity e){{\n\tfloat result = {base}_slider;"


def get_function_suffix() -> str:
    """Get the read-only suffix for Custom mode function display."""
    return "\treturn result;\n}"


def _sanitize_uniform_name(name: str) -> str:
    """Ensure a name is a valid GLSL identifier."""
    result = ""
    for ch in name:
        if ch.isalnum() or ch == '_':
            result += ch
        else:
            result += '_'
    if result and result[0].isdigit():
        result = '_' + result
    return result or "unnamed"
