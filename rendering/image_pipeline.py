"""ImagePipeline — the universal image pipeline split out of the old FrameAssembler.

Step 7 pulls the *universal image pipeline* (temporal accumulation, tonemap,
EXPOSURE long-exposure blend, and now bloom) out of the renderers. Renderers own
an `ImagePipeline` and return finished (tonemapped, bloomed) frames.

- `ImagePipeline` drives `shaders/image_pipeline.frag` and internally applies
  `BloomProcessor`. Same accumulation contract as the old FrameAssembler
  (`assemble_frame(..., total_samples, current_sample_index)` returns the
  finished texture on the final sample, else None).
"""
from __future__ import annotations

import moderngl
import numpy as np

from utilities.gl_helpers import tryset, read_shader


def _create_image_pipeline_shader(ctx, total_samples):
    """Compile image_pipeline.frag with the sample count baked in."""
    vertex_shader = read_shader('shaders/frame_assembly.vert')
    fragment_shader = read_shader('shaders/image_pipeline.frag')
    fragment_shader = fragment_shader.replace('{total_samples}', str(total_samples))
    return ctx.program(vertex_shader=vertex_shader, fragment_shader=fragment_shader)


def _fullscreen_quad_vao(ctx, shader):
    vertices = np.array([-1.0, -1.0, 1.0, -1.0, 1.0, 1.0, -1.0, 1.0], dtype=np.float32)
    indices = np.array([0, 1, 2, 0, 2, 3], dtype=np.uint32)
    vbo = ctx.buffer(vertices.tobytes())
    ibo = ctx.buffer(indices.tobytes())
    return ctx.vertex_array(shader, [(vbo, '2f', 'position')], ibo)


class ImagePipeline:
    """Temporal accumulation + tonemap + bloom.

    Owns the accumulation buffer and (lazily) a BloomProcessor. Returns a
    finished, tonemapped (and optionally bloomed) texture on the final sample.
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
                       brightness=1.0, tonemap_softness=1.0,
                       bloom_enabled=False, bloom_threshold=0.8,
                       bloom_intensity=0.5, bloom_radius=1.0):
        """Accumulate one sample; on the final sample return the finished texture.

        Bloom (when enabled) is applied here, so the returned texture is fully
        finished.
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
        tryset(shader, 'TONEMAP_SOFTNESS', tonemap_softness)

        self.resources['accumulation_fbo'].use()
        self.resources['vao'].render()

        if not final_sample:
            return None

        result = self.resources['accumulation_texture']
        if bloom_enabled and result is not None:
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
