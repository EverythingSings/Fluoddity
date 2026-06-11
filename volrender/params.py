from __future__ import annotations
from dataclasses import dataclass


@dataclass
class GridParams:
    """Voxel grid configuration.

    bounds_min/max define the axis-aligned world-space box the grid occupies.
    Voxel size = (bounds_max - bounds_min) / resolution.
    """
    bounds_min: tuple[float, float, float]              # REQUIRED, world space
    bounds_max: tuple[float, float, float]              # REQUIRED, world space
    resolution: tuple[int, int, int] = (256, 256, 256)
    color_resolution: tuple[int, int, int] | None = None  # None = same as resolution
    majorant_resolution: tuple[int, int, int] = (32, 32, 32)

    @property
    def effective_color_resolution(self) -> tuple[int, int, int]:
        """Color grid resolution, defaulting to density resolution if not set."""
        return self.color_resolution if self.color_resolution is not None else self.resolution


@dataclass
class MediumParams:
    """Participating-medium optical properties.

    sigma_t_rgb(x) = extinction_rgb * density_scale * physical_density(x)
    Albedo is derived per-voxel from accumulated entity hue vectors.
    albedo_saturation is the ceiling on saturation (scaled by hue
    concentration R); albedo_brightness is the HSV value component.
    """
    extinction_rgb:      tuple[float, float, float] = (1.0, 1.0, 1.0)  # per-unit-density, vec3
    albedo_saturation:   float = 1.0   # saturation ceiling for per-voxel hue [0, 1]
    albedo_brightness:   float = 0.8   # HSV value component [0, 1]
    density_scale:       float = 1.0
    colored_extinction:  bool = False  # true = hue→extinction, false = hue→albedo
    hg_g:                float = 0.0   # HG asymmetry [-1,1]: >0 fwd, <0 back, 0 iso
    emission_strength:   float = 0.0   # emission intensity multiplier (0 = off)
    # Base medium (uniform fog sphere)
    fog_density:         float = 0.0   # fog sigma_t multiplier (0 = disabled)
    fog_extinction_rgb:  tuple[float, float, float] = (1.0, 1.0, 1.0)
    fog_albedo_rgb:      tuple[float, float, float] = (1.0, 1.0, 1.0)
    fog_radius:          float = 5.0   # sphere radius in world units
    fog_hg_g:            float = 0.0   # HG asymmetry for fog scattering


@dataclass
class SunParams:
    """Directional sun light (NEE-only, no visible disk).

    direction is a unit vector pointing FROM the scene TOWARD the sun
    (the direction a shadow ray marches).  Light arrives along -direction.
    Sun radiance = color_rgb * intensity.
    """
    direction: tuple[float, float, float]               # unit, scene -> sun
    color_rgb: tuple[float, float, float] = (1.0, 0.95, 0.9)
    intensity: float = 3.0
    sampling:  bool = True   # NEE shadow rays enabled


@dataclass
class SkyParams:
    """Uniform isotropic sky environment.

    Not NEE-sampled; contributes only through escaped / random-walk rays.
    A primary ray that escapes the grid returns sky as the visible background.
    """
    color_rgb: tuple[float, float, float] = (0.5, 0.7, 1.0)
    intensity: float = 1.0


@dataclass
class RenderParams:
    """Path-tracing dispatch settings."""
    num_samples:    int = 64
    batch_spp:      int = 1        # COMMENT FLAG: dispatch granularity (TDR avoidance)
    max_bounces:    int = 0        # COMMENT FLAG: 0 = unbounded (RR only)
    rr_start_depth: int = 4        # COMMENT FLAG: Russian roulette onset
    seed:           int = 0        # COMMENT FLAG: seed — deterministic RNG base
