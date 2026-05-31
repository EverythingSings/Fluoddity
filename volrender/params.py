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
    splat_outer_product: bool = True                    # splat d⊗d now (read later)


@dataclass
class MediumParams:
    """Participating-medium optical properties.

    sigma_t_rgb(x) = extinction_rgb * density_scale * physical_density(x)
    albedo_rgb is the single-scatter albedo; scattering is folded as a
    throughput multiply by albedo_rgb at each real collision.
    """
    extinction_rgb: tuple[float, float, float] = (1.0, 1.0, 1.0)  # per-unit-density, vec3
    albedo_rgb:     tuple[float, float, float] = (0.8, 0.8, 0.8)  # single-scatter albedo
    density_scale:  float = 1.0


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
    seed:           int = 0
