"""ImagePipeline + OverlayCompositor — the split of the old FrameAssembler.

Step 7 pulls the *universal image pipeline* (temporal accumulation, tonemap,
watercolor, EXPOSURE long-exposure blend, SDF preview, and now bloom) out of the
overlay markup. Renderers own an `ImagePipeline` and return finished (tonemapped,
bloomed) frames; the orchestrator runs an `OverlayCompositor` afterwards to draw
UI markup (sweep reticle, draw ring, field overlay) over the finished frame for
*display only* — so recorded video frames stay markup-free.

- `ImagePipeline` drives `shaders/image_pipeline.frag` and internally applies
  `BloomProcessor`. Same accumulation contract as the old FrameAssembler
  (`assemble_frame(..., total_samples, current_sample_index)` returns the
  finished texture on the final sample, else None).
- `OverlayCompositor` drives `shaders/overlay.frag` over a finished frame.
"""
from __future__ import annotations

import moderngl
import numpy as np

from utilities.gl_helpers import tryset, tryset_mat4, read_shader


def _create_image_pipeline_shader(ctx, total_samples):
    """Compile image_pipeline.frag with SDF scene includes + sample count."""
    vertex_shader = read_shader('shaders/frame_assembly.vert')
    fragment_shader = read_shader('shaders/image_pipeline.frag')
    fragment_shader = fragment_shader.replace('{total_samples}', str(total_samples))

    # Prepend SDF scene definition (common.glsl + volume_scene.glsl) after #version
    common_src = read_shader('volrender/shaders/common.glsl')
    scene_src = read_shader('volrender/shaders/volume_scene.glsl')
    insert_pos = fragment_shader.find("\n")
    fragment_shader = (fragment_shader[:insert_pos + 1]
                       + common_src + scene_src
                       + fragment_shader[insert_pos + 1:])
    return ctx.program(vertex_shader=vertex_shader, fragment_shader=fragment_shader)


def _fullscreen_quad_vao(ctx, shader):
    vertices = np.array([-1.0, -1.0, 1.0, -1.0, 1.0, 1.0, -1.0, 1.0], dtype=np.float32)
    indices = np.array([0, 1, 2, 0, 2, 3], dtype=np.uint32)
    vbo = ctx.buffer(vertices.tobytes())
    ibo = ctx.buffer(indices.tobytes())
    return ctx.vertex_array(shader, [(vbo, '2f', 'position')], ibo)


class ImagePipeline:
    """Temporal accumulation + tonemap + watercolor + SDF preview + bloom.

    Owns the accumulation buffer and (lazily) a BloomProcessor. Returns a
    finished, tonemapped (and optionally bloomed) texture on the final sample.
    Overlay markup is NOT applied here — that is the OverlayCompositor's job.
    """

    def __init__(self, ctx):
        self.ctx = ctx
        self.resources = None
        self._bloom_processor = None

    def _setup(self, width, height, total_samples):
        accumulation_texture = self.ctx.texture((width, height), 4, dtype='f4')
        accumulation_texture.filter = (moderngl.NEAREST, moderngl.NEAREST)
        accumulation_fbo = self.ctx.framebuffer(color_attachments=[accumulation_texture])
        shader = _create_image_pipeline_shader(self.ctx, total_samples)
        vao = _fullscreen_quad_vao(self.ctx, shader)
        return {
            'accumulation_fbo': accumulation_fbo,
            'accumulation_texture': accumulation_texture,
            'shader': shader,
            'vao': vao,
            'total_samples': total_samples,
            'width': width,
            'height': height,
        }

    def assemble_frame(self, input_texture, total_samples, current_sample_index,
                       brightness=1.0, exposure=0.0, ink_weight=1.0,
                       watercolor_mode=False, tonemap_softness=1.0,
                       sdf_enabled=False, inv_view_proj=None,
                       sdf_sun_dir=(0.577, 0.577, 0.577),
                       sdf_sun_color=(3.0, 3.0, 3.0),
                       sdf_sky_color=(0.5, 0.7, 1.0),
                       bloom_enabled=False, bloom_threshold=0.8,
                       bloom_intensity=0.5, bloom_radius=1.0):
        """Accumulate one sample; on the final sample return the finished texture.

        Bloom (when enabled and not in watercolor mode) is applied here, so the
        returned texture is fully finished.
        """
        input_width, input_height = input_texture.size
        recreate = (
            self.resources is None
            or self.resources['total_samples'] != total_samples
            or self.resources['width'] != input_width
            or self.resources['height'] != input_height
        )
        if recreate:
            if self.resources is not None:
                self._release_resources()
            self.resources = self._setup(input_width, input_height, total_samples)

        is_first_frame = (current_sample_index == 0)
        final_sample = (current_sample_index == total_samples - 1)

        input_texture.use(location=0)
        self.resources['accumulation_texture'].use(location=1)

        shader = self.resources['shader']
        shader['input_frame'] = 0
        shader['accumulation_buffer'] = 1
        shader['is_first_frame'] = is_first_frame
        shader['final_sample'] = final_sample
        tryset(shader, 'BRIGHTNESS', brightness)
        tryset(shader, 'EXPOSURE', exposure)
        tryset(shader, 'INK_WEIGHT', ink_weight)
        tryset(shader, 'WATERCOLOR_MODE', watercolor_mode)
        tryset(shader, 'TONEMAP_SOFTNESS', tonemap_softness)
        # SDF preview uniforms
        tryset(shader, 'u_sdf_enabled', sdf_enabled)
        if sdf_enabled and inv_view_proj is not None:
            tryset_mat4(shader, 'u_inv_view_proj', inv_view_proj)
            tryset(shader, 'u_sdf_sun_dir', sdf_sun_dir)
            tryset(shader, 'u_sdf_sun_color', sdf_sun_color)
            tryset(shader, 'u_sdf_sky_color', sdf_sky_color)

        self.resources['accumulation_fbo'].use()
        self.resources['vao'].render()

        if not final_sample:
            return None

        result = self.resources['accumulation_texture']
        if bloom_enabled and not watercolor_mode and result is not None:
            result = self._apply_bloom(result, bloom_threshold, bloom_intensity,
                                       bloom_radius, tonemap_softness)
        return result

    def _apply_bloom(self, texture, threshold, intensity, radius, tonemap_softness):
        if self._bloom_processor is None:
            from utilities.bloom import BloomProcessor
            self._bloom_processor = BloomProcessor(self.ctx)
        return self._bloom_processor.process(
            texture, threshold, intensity, radius,
            tonemap_softness=tonemap_softness,
        )

    def get_current_texture(self):
        if self.resources is None:
            return None
        return self.resources['accumulation_texture']

    def reset(self):
        if self.resources is not None:
            self.resources['accumulation_fbo'].clear()

    def _release_resources(self):
        if self.resources is not None:
            self.resources['accumulation_fbo'].release()
            self.resources['accumulation_texture'].release()
            self.resources['shader'].release()
            self.resources['vao'].release()
            self.resources = None

    def cleanup(self):
        self._release_resources()
        if self._bloom_processor is not None:
            self._bloom_processor.cleanup()
            self._bloom_processor = None


class OverlayCompositor:
    """Draws UI markup over a finished frame for display only.

    Runs `shaders/overlay.frag`: sweep reticle, draw-trail ring, and the
    advanced-drawing field overlay. Input is a finished (tonemapped) texture;
    output is a display-only texture (never sent to the video recorder).
    """

    def __init__(self, ctx):
        self.ctx = ctx
        self._shader = None
        self._vao = None
        self._out_tex = None
        self._out_fbo = None
        self._size = (0, 0)

    def _ensure(self, width, height):
        if self._shader is None:
            vert = read_shader('shaders/frame_assembly.vert')
            frag = read_shader('shaders/overlay.frag')
            self._shader = self.ctx.program(vertex_shader=vert, fragment_shader=frag)
            self._vao = _fullscreen_quad_vao(self.ctx, self._shader)
        if self._size != (width, height):
            if self._out_tex is not None:
                self._out_fbo.release()
                self._out_tex.release()
            self._out_tex = self.ctx.texture((width, height), 4, dtype='f4')
            self._out_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
            self._out_fbo = self.ctx.framebuffer(color_attachments=[self._out_tex])
            self._size = (width, height)

    def has_markup(self, *, sweep_mode, sweep_reticle_visible, trail_draw_radius,
                   field_overlay_active):
        """Whether any overlay would actually draw (lets callers skip the pass)."""
        return (
            (sweep_mode and sweep_reticle_visible)
            or (trail_draw_radius > 0.0)
            or field_overlay_active
        )

    def composite(self, input_texture, *,
                  sweep_mode=False, sweep_reticle_pos=(0.5, 0.5),
                  sweep_reticle_visible=False, screen_aspect=1.0,
                  watercolor_mode=False, exposure=0.0,
                  trail_draw_radius=0.0, mouse_screen_coords=(0.5, 0.5),
                  camera_position=(0.0, 0.0), camera_zoom=1.0,
                  canvas_resolution=(1024, 1024),
                  field_texture=None,
                  advanced_drawing_resources_initialized=False,
                  draw_target_overlay_opacity=0.0):
        """Composite markup over ``input_texture``; return a display texture."""
        width, height = input_texture.size
        self._ensure(width, height)

        input_texture.use(location=0)
        if field_texture is not None:
            field_texture.use(location=3)

        s = self._shader
        s['input_frame'] = 0
        tryset(s, 'PARAMETER_SWEEP_MODE', sweep_mode)
        tryset(s, 'sweep_reticle_pos', sweep_reticle_pos)
        tryset(s, 'sweep_reticle_visible', sweep_reticle_visible)
        tryset(s, 'screen_aspect', screen_aspect)
        tryset(s, 'WATERCOLOR_MODE', watercolor_mode)
        tryset(s, 'EXPOSURE', exposure)
        tryset(s, 'TRAIL_DRAW_RADIUS', trail_draw_radius)
        tryset(s, 'mouse_screen_coords', mouse_screen_coords)
        tryset(s, 'camera_position', camera_position)
        tryset(s, 'camera_zoom', camera_zoom)
        tryset(s, 'canvas_resolution', canvas_resolution)
        tryset(s, 'field_texture', 3)
        tryset(s, 'advanced_drawing_resources_initialized',
               advanced_drawing_resources_initialized)
        tryset(s, 'draw_target_overlay_opacity', draw_target_overlay_opacity)

        self._out_fbo.use()
        self._vao.render()
        return self._out_tex

    def cleanup(self):
        for attr in ('_out_fbo', '_out_tex', '_vao', '_shader'):
            obj = getattr(self, attr, None)
            if obj is not None:
                obj.release()
                setattr(self, attr, None)
        self._size = (0, 0)
