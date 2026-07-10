from dataclasses import dataclass, field, asdict
from pathlib import Path
import json
from utilities.paths import get_user_preferences_path


# ---------------------------------------------------------------------------
# Per-module preference slices
#
# PreferencesState is composed of these slices, one per subsystem, so each
# module owns its own preferences. Nested access is used everywhere:
#   prefs.tracer.sdf_enabled, prefs.optix.ao_radius, prefs.rendering.speedmult
#
# Backward compat with pre-slice (flat-key) JSON files is handled by
# _FLAT_KEY_MAP + from_flat_dict() in load_preferences().
# ---------------------------------------------------------------------------


@dataclass
class RenderingPrefs:
    """Core frame rendering / motion-blur / tonemap preferences."""
    speedmult: int = 5
    motion_blur: bool = True
    blur_quality: int = 2  # Motion blur render cadence (1 = every frame, 2 = every 2 frames, etc.)
    world_size: float = 0.40  # Legacy (unused, kept for saved-prefs backward compat)
    canvas_aspect_ratio: str = "1:1"  # Legacy (unused, kept for saved-prefs backward compat)
    entity_count: int = 4000000  # Number of active particles (all allocated entities are active)
    canvas_resolution: int = 256  # Cubic canvas dimension (W=H=D) for 3D trail textures
    rule_seed: float = 0.0
    brightness: float = 3.0  # Global brightness multiplier
    tonemap_softness: float = 2.5  # Asinh tonemap stretch (higher = more highlight compression)
    exposure: float = 0.0  # Frame blending for motion blur effect (0=disabled, 1=long exposure)


@dataclass
class BloomPrefs:
    """Bloom post-processing preferences."""
    enabled: bool = True  # Whether bloom post-processing is active
    threshold: float = 0.11  # Brightness threshold for bloom extraction
    intensity: float = 0.23  # Bloom contribution strength
    radius: float = 1.0  # Bloom blur spread


@dataclass
class RecordingPrefs:
    """Video recording preferences."""
    max_frames: int = 1800  # 150 * 12
    motion_blur_samples: int = 12
    supersample_k: int = 1
    filename_prefix: str = ""
    recording_motion_blur: bool = True  # Motion blur setting used during video recording
    recording_blur_quality: int = 1  # Blur quality setting used during video recording
    video_end_frame: int = 0  # Target frame for video to end on (0 = disabled, start immediately)
    tracer_mode: bool = False  # Use volumetric path tracer for video recording instead of normal frame assembly


@dataclass
class AdvancedDrawingPrefs:
    """Advanced force/strafe field drawing preferences."""
    enabled: bool = False  # Whether Advanced Drawing window is shown
    draw_canvas: bool = True  # "Trails / Canvas (Default)" checkbox
    draw_force_field: bool = False  # "Force Field" checkbox
    draw_strafe_field: bool = False  # "Strafe Field" checkbox
    brush_mode: int = 0  # 0=Mouse Direction, 1=Inverse, 2=Fixed, 3=Attract, 4=Repel
    fixed_direction_heading: float = 0.0  # Range -PI to PI, heading for Fixed Direction mode
    force_field_strength: float = 1.0  # Multiplier for force field effect (log scale 0.0001-10.0)
    strafe_field_strength: float = 1.0  # Multiplier for strafe field effect (log scale 0.0001-10.0)
    draw_target_overlay_opacity: float = 0.0  # Opacity of draw target field overlay in frame assembly (0-1)
    shader_driven_field: bool = False  # Use a frag shader to override the field texture
    field_override_shader: str = "march.frag"  # Currently selected field override shader filename


@dataclass
class GenericsPrefs:
    """Live-coding scratch uniform values."""
    generic0: float = 0.0
    generic1: float = 0.0
    generic2: float = 0.0
    generic3: float = 0.0
    generic4: float = 0.0
    generic5: float = 0.0
    generic6: float = 0.0
    generic7: float = 0.0


@dataclass
class ParameterLocksPrefs:
    """Parameter lock feature preferences."""
    enabled: bool = False  # Master toggle for parameter lock feature


@dataclass
class TracerPrefs:
    """Volumetric path tracer preferences."""
    sdf_enabled: bool = True
    colored_extinction: bool = False
    extinction_rgb: list = field(default_factory=lambda: [1.0, 1.0, 1.0])
    albedo_saturation: float = 1.0
    albedo_brightness: float = 0.8
    density_scale: float = 0.0001
    hg_g: float = 0.0  # HG phase asymmetry [-1,1]
    emission_strength: float = 0.0  # emission intensity (0 = off)
    sun_direction: list = field(default_factory=lambda: [0.577, 0.577, 0.577])
    sun_color: list = field(default_factory=lambda: [1.0, 0.95, 0.9])
    sun_intensity: float = 3.0
    sky_color: list = field(default_factory=lambda: [0.5, 0.7, 1.0])
    sky_intensity: float = 1.0
    num_samples: int = 64
    exposure: float = 1.5
    realtime_mode: int = 0  # 0=Off, 1=1spp, 2=Accumulate
    max_bounces: int = 0  # 0=unbounded (RR only)
    firefly_clamp: bool = False
    firefly_clamp_max: float = 10.0
    resolution_scale: float = 1.0  # multiplier on render resolution
    density_resolution_log2: int = 9   # 2^9 = 512
    color_resolution_log2: int = 9     # 2^9 = 512
    majorant_resolution_log2: int = 7  # 2^7 = 128
    sun_sampling: bool = True  # NEE sun shadow rays
    photosphere: bool = False  # skybox texture mode


@dataclass
class OptixPrefs:
    """OptiX raytracer + path tracer preferences (spheres and PT are one subsystem)."""
    # OptiX raytracer settings
    enabled: bool = False
    sphere_radius_scale: float = 1.0
    light_direction: list = field(default_factory=lambda: [0.577, 0.577, 0.577])
    light_color: list = field(default_factory=lambda: [1.0, 1.0, 1.0])
    light_intensity: float = 1.0
    shadows_enabled: bool = True
    ambient: float = 0.12
    sky_color_top: list = field(default_factory=lambda: [0.45, 0.62, 0.85])
    sky_color_bottom: list = field(default_factory=lambda: [0.08, 0.08, 0.10])
    ao_enabled: bool = False
    ao_num_rays: int = 2
    ao_radius: float = 0.5
    ambient_color: list = field(default_factory=lambda: [1.0, 1.0, 1.0])  # Rasterize ambient tint (scaled by `ambient`)
    albedo_saturation: float = 0.8
    albedo_brightness: float = 1.0
    sphere_size_jitter: float = 0.0  # Per-sphere radius jitter to reduce banding (0-1)
    use_curves: bool = False  # Toggle: render entities as round linear curves instead of spheres
    curve_length: float = 1.0  # Distance between curve control points (multiplier on entity_size * radius_scale)
    curve_r0: float = 1.0  # Radius at first control point (multiplier on entity_size * radius_scale)
    curve_r1: float = 0.5  # Radius at second control point (multiplier on entity_size * radius_scale)
    sdf_enabled: bool = False  # Enable SDF scene geometry in OptiX renderers
    resolution_scale: float = 1.0  # multiplier on render resolution

    # OptiX RT mode and path tracer settings
    rt_mode: int = 0  # 0=Rasterize, 1=X spp, 2=Accumulate
    rt_realtime_samples: int = 1  # Samples/frame for RT: X spp mode (1-8)
    rt_preview_spp: int = 64  # Target SPP for Re-render Preview
    pt_sun_sampling: bool = True
    pt_max_bounces: int = 8
    pt_rr_start_depth: int = 3
    pt_firefly_clamp: bool = True
    pt_firefly_clamp_max: float = 50.0
    pt_global_material: int = 0  # 0=Lambert, 1=Glossy, 2=Mirror
    pt_glossy_ior: float = 1.5
    pt_emission_intensity: float = 10.0  # Emissive radiance multiplier for negative-hue entities
    pt_denoise_enabled: bool = False
    rz_denoise_enabled: bool = False  # Denoise in rasterize mode (separate beauty pass)
    pt_env_sky_nee: bool = False  # Use cosine-lobe environment sky for NEE instead of directional sun
    pt_photosphere: bool = False  # Use equirectangular environment map for sky


@dataclass
class Camera3DPrefs:
    """3D camera preferences."""
    render_3d: bool = True
    fov: float = 50.0
    aperture: float = 0.0  # DOF lens radius
    focal_plane_depth: float = 5.0  # DOF focal plane distance
    move_speed: float = 2.0
    rotate_speed: float = 2.0
    orbit_center: list = field(default_factory=lambda: [0.0, 0.0, 0.0])
    orbit_rate: float = 0.0


@dataclass
class UIWindowsPrefs:
    """Window visibility flags + general UI interaction preferences."""
    # Window visibility
    show_preferences_window: bool = True
    show_controls_window: bool = False
    show_parameter_sweeps_window: bool = False
    show_tutorial_window: bool = True
    show_performance_window: bool = False
    show_generics_window: bool = False
    show_radio_window: bool = False
    show_plotting_window: bool = False
    show_video_recording_window: bool = False
    show_three_d_window: bool = False
    show_scheduled_renders_window: bool = False
    show_tracer_window: bool = False
    show_optix_window: bool = False

    # UI interaction
    physics_tooltips_enabled: bool = True
    debug_arrows: bool = False  # Visual debug overlay for velocity field
    arrow_sensitivity: float = 15.0  # Velocity scale for debug arrows (pow(2, x))
    mouse_mode: str = "Select Particle"  # "Select Particle" or "Draw Trail"
    draw_size: float = 0.031  # Gaussian kernel width for trail drawing
    draw_power: float = 1.0  # Velocity strength when drawing trails
    menu_close_threshold: float = 80.0  # Distance in pixels before menus auto-close

    # Physics slider group collapsed states (True = expanded/open, False = collapsed)
    physics_group_basics: bool = True  # Default: open (trail sensors + mutation)
    physics_group_forces: bool = True  # Default: open (global force mult, drag)
    physics_group_advanced: bool = False  # Default: collapsed
    physics_group_additional: bool = False  # Default: collapsed
    physics_group_notes: bool = False  # Default: collapsed

    # Load menu collapsed states (True = expanded/open, False = collapsed)
    load_menu_core_open: bool = True  # Default: open
    load_menu_custom_open: bool = True  # Default: open
    load_menu_advanced_open: bool = False  # Default: collapsed


@dataclass
class PreferencesState:
    """User preferences that persist between program sessions.

    Composed of per-module slices so each subsystem owns its own prefs.
    Access is nested: prefs.rendering.speedmult, prefs.tracer.sdf_enabled, etc.
    """
    rendering: RenderingPrefs = field(default_factory=RenderingPrefs)
    bloom: BloomPrefs = field(default_factory=BloomPrefs)
    recording: RecordingPrefs = field(default_factory=RecordingPrefs)
    advanced_drawing: AdvancedDrawingPrefs = field(default_factory=AdvancedDrawingPrefs)
    generics: GenericsPrefs = field(default_factory=GenericsPrefs)
    parameter_locks: ParameterLocksPrefs = field(default_factory=ParameterLocksPrefs)
    tracer: TracerPrefs = field(default_factory=TracerPrefs)
    optix: OptixPrefs = field(default_factory=OptixPrefs)
    camera3d: Camera3DPrefs = field(default_factory=Camera3DPrefs)
    ui_windows: UIWindowsPrefs = field(default_factory=UIWindowsPrefs)


# The slice attribute names on PreferencesState (top-level nested-JSON keys).
_SLICE_ATTRS = tuple(PreferencesState.__dataclass_fields__.keys())


# ---------------------------------------------------------------------------
# Flat-key compatibility map: old flat JSON key -> (slice_attr, nested_field).
# The single source of truth for legacy-JSON migration and for the flat
# snapshot/restore used by services/render_spec.py.
# ---------------------------------------------------------------------------
_FLAT_KEY_MAP: dict[str, tuple[str, str]] = {
    # RenderingPrefs
    "speedmult": ("rendering", "speedmult"),
    "motion_blur": ("rendering", "motion_blur"),
    "blur_quality": ("rendering", "blur_quality"),
    "world_size": ("rendering", "world_size"),
    "canvas_aspect_ratio": ("rendering", "canvas_aspect_ratio"),
    "entity_count": ("rendering", "entity_count"),
    "canvas_resolution": ("rendering", "canvas_resolution"),
    "rule_seed": ("rendering", "rule_seed"),
    "brightness": ("rendering", "brightness"),
    "tonemap_softness": ("rendering", "tonemap_softness"),
    "exposure": ("rendering", "exposure"),
    # BloomPrefs
    "bloom_enabled": ("bloom", "enabled"),
    "bloom_threshold": ("bloom", "threshold"),
    "bloom_intensity": ("bloom", "intensity"),
    "bloom_radius": ("bloom", "radius"),
    # RecordingPrefs
    "max_frames": ("recording", "max_frames"),
    "motion_blur_samples": ("recording", "motion_blur_samples"),
    "supersample_k": ("recording", "supersample_k"),
    "filename_prefix": ("recording", "filename_prefix"),
    "recording_motion_blur": ("recording", "recording_motion_blur"),
    "recording_blur_quality": ("recording", "recording_blur_quality"),
    "video_end_frame": ("recording", "video_end_frame"),
    "tracer_mode": ("recording", "tracer_mode"),
    # AdvancedDrawingPrefs
    "advanced_drawing_enabled": ("advanced_drawing", "enabled"),
    "advanced_draw_canvas": ("advanced_drawing", "draw_canvas"),
    "advanced_draw_force_field": ("advanced_drawing", "draw_force_field"),
    "advanced_draw_strafe_field": ("advanced_drawing", "draw_strafe_field"),
    "brush_mode": ("advanced_drawing", "brush_mode"),
    "fixed_direction_heading": ("advanced_drawing", "fixed_direction_heading"),
    "force_field_strength": ("advanced_drawing", "force_field_strength"),
    "strafe_field_strength": ("advanced_drawing", "strafe_field_strength"),
    "draw_target_overlay_opacity": ("advanced_drawing", "draw_target_overlay_opacity"),
    "shader_driven_field": ("advanced_drawing", "shader_driven_field"),
    "field_override_shader": ("advanced_drawing", "field_override_shader"),
    # GenericsPrefs
    "generic0": ("generics", "generic0"),
    "generic1": ("generics", "generic1"),
    "generic2": ("generics", "generic2"),
    "generic3": ("generics", "generic3"),
    "generic4": ("generics", "generic4"),
    "generic5": ("generics", "generic5"),
    "generic6": ("generics", "generic6"),
    "generic7": ("generics", "generic7"),
    # ParameterLocksPrefs
    "parameter_locks_enabled": ("parameter_locks", "enabled"),
    # TracerPrefs
    "tracer_sdf_enabled": ("tracer", "sdf_enabled"),
    "tracer_colored_extinction": ("tracer", "colored_extinction"),
    "tracer_extinction_rgb": ("tracer", "extinction_rgb"),
    "tracer_albedo_saturation": ("tracer", "albedo_saturation"),
    "tracer_albedo_brightness": ("tracer", "albedo_brightness"),
    "tracer_density_scale": ("tracer", "density_scale"),
    "tracer_hg_g": ("tracer", "hg_g"),
    "tracer_emission_strength": ("tracer", "emission_strength"),
    "tracer_sun_direction": ("tracer", "sun_direction"),
    "tracer_sun_color": ("tracer", "sun_color"),
    "tracer_sun_intensity": ("tracer", "sun_intensity"),
    "tracer_sky_color": ("tracer", "sky_color"),
    "tracer_sky_intensity": ("tracer", "sky_intensity"),
    "tracer_num_samples": ("tracer", "num_samples"),
    "tracer_exposure": ("tracer", "exposure"),
    "tracer_realtime_mode": ("tracer", "realtime_mode"),
    "tracer_max_bounces": ("tracer", "max_bounces"),
    "tracer_firefly_clamp": ("tracer", "firefly_clamp"),
    "tracer_firefly_clamp_max": ("tracer", "firefly_clamp_max"),
    "tracer_resolution_scale": ("tracer", "resolution_scale"),
    "tracer_density_resolution_log2": ("tracer", "density_resolution_log2"),
    "tracer_color_resolution_log2": ("tracer", "color_resolution_log2"),
    "tracer_majorant_resolution_log2": ("tracer", "majorant_resolution_log2"),
    "tracer_sun_sampling": ("tracer", "sun_sampling"),
    "tracer_photosphere": ("tracer", "photosphere"),
    # OptixPrefs (spheres)
    "three_d_optix_enabled": ("optix", "enabled"),
    "three_d_optix_sphere_radius_scale": ("optix", "sphere_radius_scale"),
    "three_d_optix_light_direction": ("optix", "light_direction"),
    "three_d_optix_light_color": ("optix", "light_color"),
    "three_d_optix_light_intensity": ("optix", "light_intensity"),
    "three_d_optix_shadows_enabled": ("optix", "shadows_enabled"),
    "three_d_optix_ambient": ("optix", "ambient"),
    "three_d_optix_sky_color_top": ("optix", "sky_color_top"),
    "three_d_optix_sky_color_bottom": ("optix", "sky_color_bottom"),
    "three_d_optix_ao_enabled": ("optix", "ao_enabled"),
    "three_d_optix_ao_num_rays": ("optix", "ao_num_rays"),
    "three_d_optix_ao_radius": ("optix", "ao_radius"),
    "three_d_optix_ambient_color": ("optix", "ambient_color"),
    "three_d_optix_albedo_saturation": ("optix", "albedo_saturation"),
    "three_d_optix_albedo_brightness": ("optix", "albedo_brightness"),
    "three_d_optix_sphere_size_jitter": ("optix", "sphere_size_jitter"),
    "three_d_optix_use_curves": ("optix", "use_curves"),
    "three_d_optix_curve_length": ("optix", "curve_length"),
    "three_d_optix_curve_r0": ("optix", "curve_r0"),
    "three_d_optix_curve_r1": ("optix", "curve_r1"),
    "three_d_optix_sdf_enabled": ("optix", "sdf_enabled"),
    "three_d_optix_resolution_scale": ("optix", "resolution_scale"),
    # OptixPrefs (RT/PT)
    "three_d_rt_mode": ("optix", "rt_mode"),
    "three_d_rt_realtime_samples": ("optix", "rt_realtime_samples"),
    "three_d_rt_preview_spp": ("optix", "rt_preview_spp"),
    "three_d_pt_sun_sampling": ("optix", "pt_sun_sampling"),
    "three_d_pt_max_bounces": ("optix", "pt_max_bounces"),
    "three_d_pt_rr_start_depth": ("optix", "pt_rr_start_depth"),
    "three_d_pt_firefly_clamp": ("optix", "pt_firefly_clamp"),
    "three_d_pt_firefly_clamp_max": ("optix", "pt_firefly_clamp_max"),
    "three_d_pt_global_material": ("optix", "pt_global_material"),
    "three_d_pt_glossy_ior": ("optix", "pt_glossy_ior"),
    "three_d_pt_emission_intensity": ("optix", "pt_emission_intensity"),
    "three_d_pt_denoise_enabled": ("optix", "pt_denoise_enabled"),
    "three_d_rz_denoise_enabled": ("optix", "rz_denoise_enabled"),
    "three_d_pt_env_sky_nee": ("optix", "pt_env_sky_nee"),
    "three_d_pt_photosphere": ("optix", "pt_photosphere"),
    # Camera3DPrefs
    "three_d_render_3d": ("camera3d", "render_3d"),
    "three_d_fov": ("camera3d", "fov"),
    "three_d_aperture": ("camera3d", "aperture"),
    "three_d_focal_plane_depth": ("camera3d", "focal_plane_depth"),
    "three_d_move_speed": ("camera3d", "move_speed"),
    "three_d_rotate_speed": ("camera3d", "rotate_speed"),
    "three_d_orbit_center": ("camera3d", "orbit_center"),
    "three_d_orbit_rate": ("camera3d", "orbit_rate"),
    # UIWindowsPrefs
    "show_preferences_window": ("ui_windows", "show_preferences_window"),
    "show_controls_window": ("ui_windows", "show_controls_window"),
    "show_parameter_sweeps_window": ("ui_windows", "show_parameter_sweeps_window"),
    "show_tutorial_window": ("ui_windows", "show_tutorial_window"),
    "show_performance_window": ("ui_windows", "show_performance_window"),
    "show_generics_window": ("ui_windows", "show_generics_window"),
    "show_radio_window": ("ui_windows", "show_radio_window"),
    "show_plotting_window": ("ui_windows", "show_plotting_window"),
    "show_video_recording_window": ("ui_windows", "show_video_recording_window"),
    "show_three_d_window": ("ui_windows", "show_three_d_window"),
    "show_scheduled_renders_window": ("ui_windows", "show_scheduled_renders_window"),
    "show_tracer_window": ("ui_windows", "show_tracer_window"),
    "show_optix_window": ("ui_windows", "show_optix_window"),
    "physics_tooltips_enabled": ("ui_windows", "physics_tooltips_enabled"),
    "debug_arrows": ("ui_windows", "debug_arrows"),
    "arrow_sensitivity": ("ui_windows", "arrow_sensitivity"),
    "mouse_mode": ("ui_windows", "mouse_mode"),
    "draw_size": ("ui_windows", "draw_size"),
    "draw_power": ("ui_windows", "draw_power"),
    "menu_close_threshold": ("ui_windows", "menu_close_threshold"),
    "physics_group_basics": ("ui_windows", "physics_group_basics"),
    "physics_group_forces": ("ui_windows", "physics_group_forces"),
    "physics_group_advanced": ("ui_windows", "physics_group_advanced"),
    "physics_group_additional": ("ui_windows", "physics_group_additional"),
    "physics_group_notes": ("ui_windows", "physics_group_notes"),
    "load_menu_core_open": ("ui_windows", "load_menu_core_open"),
    "load_menu_custom_open": ("ui_windows", "load_menu_custom_open"),
    "load_menu_advanced_open": ("ui_windows", "load_menu_advanced_open"),
}


def to_flat_dict(prefs: PreferencesState) -> dict:
    """Flatten a PreferencesState into the legacy flat-key dict.

    Used by services/render_spec.py to snapshot preferences as a flat dict.
    """
    out = {}
    for flat_key, (slice_attr, nested) in _FLAT_KEY_MAP.items():
        out[flat_key] = getattr(getattr(prefs, slice_attr), nested)
    return out


def set_flat(prefs: PreferencesState, key: str, value) -> None:
    """Set a single flat-keyed preference on the correct slice.

    No-op if the key is not a known flat preference key.
    """
    mapping = _FLAT_KEY_MAP.get(key)
    if mapping is None:
        return
    slice_attr, nested = mapping
    setattr(getattr(prefs, slice_attr), nested, value)


def from_flat_dict(data: dict) -> PreferencesState:
    """Build a PreferencesState from a legacy flat-key dict.

    Unknown keys are dropped (backward-compat filtering); missing keys keep
    their slice defaults.
    """
    prefs = PreferencesState()
    for key, value in data.items():
        set_flat(prefs, key, value)
    return prefs


def _from_nested_dict(data: dict) -> PreferencesState:
    """Build a PreferencesState from nested (current-format) JSON."""
    prefs = PreferencesState()
    for slice_attr in _SLICE_ATTRS:
        slice_data = data.get(slice_attr)
        if not isinstance(slice_data, dict):
            continue
        slice_obj = getattr(prefs, slice_attr)
        valid = set(type(slice_obj).__dataclass_fields__.keys())
        for k, v in slice_data.items():
            if k in valid:
                setattr(slice_obj, k, v)
    return prefs


def save_preferences(prefs: PreferencesState, filepath: Path | str = None) -> None:
    """Save preferences to a JSON file (nested per-slice format)."""
    if filepath is None:
        filepath = get_user_preferences_path()
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(prefs)
    filepath.write_text(json.dumps(data, indent=2))


def load_preferences(filepath: Path | str = None) -> PreferencesState:
    """Load preferences from a JSON file. Returns default preferences if file doesn't exist.

    Accepts both the current nested per-slice format and the legacy flat-key
    format written before the preferences were split into slices.
    """
    if filepath is None:
        filepath = get_user_preferences_path()
    filepath = Path(filepath)
    if not filepath.exists():
        return PreferencesState()

    try:
        data = json.loads(filepath.read_text())
        # Nested format has the slice attrs as top-level keys; legacy format is flat.
        if isinstance(data, dict) and any(k in data for k in _SLICE_ATTRS):
            return _from_nested_dict(data)
        return from_flat_dict(data)
    except (json.JSONDecodeError, TypeError) as e:
        print(f"Warning: Failed to load preferences from {filepath}: {e}")
        print("Using default preferences")
        return PreferencesState()
