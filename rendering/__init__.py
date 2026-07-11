"""Rendering package: the Renderer protocol, RendererHost, and the shared
image pipeline / overlay compositor (Step 7 of the modularity refactor)."""
from .renderer import Renderer, RenderCamera, VideoStrategy

__all__ = ['Renderer', 'RenderCamera', 'VideoStrategy']
