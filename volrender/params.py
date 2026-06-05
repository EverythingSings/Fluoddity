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
    majorant_resolution: tuple[int, int, int] = (32, 32, 32)


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
