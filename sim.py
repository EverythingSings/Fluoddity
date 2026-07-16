import moderngl
import time
import numpy as np
from utilities.gl_helpers import read_shader, shader_prepend, prepend_defines, tryset, set_rule_uniform
from state import SimState

# Global constants
SIZE_OF_ENTITY_STRUCT = 4*8  # 4 bytes per 32bit value. 8 values (pos:2, vel:2, hue:1, size:1, padding:2)
SIZE_OF_RULE_STRUCT = 10 * 12 * 4  # 10 centers * 12 floats per center * 4 bytes per float = 480

# Fixed rule buffer: 2^14 = 16384 entries (~7.7 MB).  Each cohort maps to one slot;
# only the first entity per cohort writes.  16k cohorts is far more than practical use.
RULE_BUFFER_SIZE = 16384

class Sim:
    def __init__(self, ctx: moderngl.Context, entity_count: int = 4000000, canvas_resolution: int = 256):
        self.ctx = ctx
        self._entity_count = entity_count
        self.canvas_resolution = canvas_resolution
        self.entity_count = self.get_entity_count()
        self.time = 0.0
        self.start_time_stamp = time.time()
        self.frame_count = 0
        self.setup_simulation_state()
        self.setup_shaders()

        # Current state (will be updated by apply_state each frame)
        self._state = SimState()
        self._camera_state = None  # Will be set by apply_camera_state

        # Active renderer's "Enable Dish" (SDF collider) toggle, pushed by the
        # orchestrator each frame. When False, the collider block is skipped.
        self.collider_enabled = False

        # Deferred rule buffer update mechanism (avoids 192MB/frame write cost)
        self._pending_rule_buffer_update = False  # Set true to trigger rule buffer write next frame
        self._pending_entity_id = None  # Entity ID to read back after rule buffer is written

    def get_entity_count(self) -> int:
        """Return the configured entity count (all allocated entities are active)."""
        return self._entity_count

    def get_canvas_dimensions(self) -> tuple[int, int]:
        """Return canvas dimensions (cubic: W=H=canvas_resolution)."""
        return (self.canvas_resolution, self.canvas_resolution)

    @property
    def can(self):
        """2D reference texture matching canvas dimensions (arrow overlays, field drawing, aspect-ratio queries)."""
        return self.view_slice_tex

    def setup_simulation_state(self):
        # Update entity_count in case it was changed via preferences
        self.entity_count = self.get_entity_count()
        canvas_dim_x = canvas_dim_y = self.canvas_resolution
        canvas_shape = (canvas_dim_x, canvas_dim_y)

        # Allocate state buffers
        self.entities = self.ctx.buffer(reserve=self.entity_count * SIZE_OF_ENTITY_STRUCT)
        self.rule_buffer = self.ctx.buffer(reserve=RULE_BUFFER_SIZE * SIZE_OF_RULE_STRUCT)

        # Bind entity and rule buffers
        self.entities.bind_to_storage_buffer(0)
        self.rule_buffer.bind_to_storage_buffer(2)

        self.can_read_index = 0  # Index of texture pair to read from (write to the other)

        # 3D canvas texture: packed RGBA16F (R=vx, G=vy, B=vz), double-buffered
        # Uses GL_NV_shader_atomic_fp16_vector for imageAtomicAdd on f16vec4
        canvas_3d_shape = (self.canvas_resolution, self.canvas_resolution, self.canvas_resolution)
        self.can_3d = [
            self.ctx.texture3d(canvas_3d_shape, 4, dtype='f2'),
            self.ctx.texture3d(canvas_3d_shape, 4, dtype='f2'),
        ]
        for tex in self.can_3d:
            tex.repeat_x = True
            tex.repeat_y = True
            tex.repeat_z = True

        # Clear 3D textures (4 components × 2 bytes each = 8 bytes per voxel)
        zero_data = bytes(self.canvas_resolution * self.canvas_resolution * self.canvas_resolution * 8)
        for tex in self.can_3d:
            tex.write(zero_data)

        # 2D reference texture matching canvas dimensions.
        # Used for arrow overlays, field drawing dimensions, and aspect ratio queries.
        self.view_slice_tex = self.ctx.texture(canvas_shape, 1, dtype='f4')
        self.view_slice_tex.repeat_x = True
        self.view_slice_tex.repeat_y = True

        # For camera/UI to use
        self.view_tex = self.view_slice_tex

    def setup_shaders(self):
        # 1. Entity update compute shader
        self.entity_update_source = read_shader('shaders/entity_update.glsl')
        # SDF scene definition for particle-surface interactions (before fourier so #extension stays first)
        self.entity_update_source = shader_prepend(self.entity_update_source, read_shader('volrender/shaders/volume_scene.glsl'))
        self.entity_update_source = shader_prepend(self.entity_update_source, read_shader('volrender/shaders/common.glsl'))
        self.entity_update_source = shader_prepend(self.entity_update_source, read_shader('shaders/fourier6_6.glsl'))
        self.entity_update_source = prepend_defines(self.entity_update_source, {
            'ENTITY_COUNT': self.entity_count,
            'ACTIVE_COUNT': self.entity_count,
            'RULE_BUFFER_SIZE': RULE_BUFFER_SIZE,
        })

        try:
            self.entity_update_program = self.ctx.compute_shader(self.entity_update_source)
        except Exception as e:
            print('Entity Update Compilation Failed:')
            print(e)

        tryset(self.entity_update_program, 'canvas_resolution', (self.canvas_resolution, self.canvas_resolution))
        tryset(self.entity_update_program, 'canvas_3d', 1)
        tryset(self.entity_update_program, 'canvas_3d_size', (self.canvas_resolution, self.canvas_resolution, self.canvas_resolution))

        # 2. Canvas update 3D compute shader
        try:
            self.canvas_update_3d_source = read_shader('shaders/canvas_update_3d.glsl')
            self.canvas_update_3d_program = self.ctx.compute_shader(self.canvas_update_3d_source)
        except Exception as e:
            print('Canvas Update 3D Compilation Failed:')
            print(e)

    def entity_update(self, ctx: moderngl.Context,
                      generics: tuple = None):
        '''
        Run a single physics update on all particles
        '''
        tryset(self.entity_update_program, 'frame_count', self.frame_count)
        tryset(self.entity_update_program, 'canvas_3d', 1)
        tryset(self.entity_update_program, 'canvas_3d_size', (self.canvas_resolution, self.canvas_resolution, self.canvas_resolution))

        # Active renderer's "Enable Dish" toggle gates the SDF collider block.
        tryset(self.entity_update_program, 'enable_collider', int(self.collider_enabled))

        # (Legacy force/strafe field uniforms removed with the drawing mode.)

        # Only write rules to buffer when explicitly requested (avoids 192MB/frame cost)
        tryset(self.entity_update_program, 'WRITE_RULES', self._pending_rule_buffer_update)

        self._assign_physics_setting('AXIAL_FORCE_SETTING', self._state.AXIAL_FORCE, 'Axial Force', 'AXIAL_FORCE', -1.0, 1.0)
        self._assign_physics_setting('LATERAL_FORCE_SETTING', self._state.LATERAL_FORCE, 'Lateral Force', 'LATERAL_FORCE', -1.0, 1.0)
        self._assign_physics_setting('SENSOR_GAIN_SETTING', self._state.SENSOR_GAIN, 'Sensor Gain', 'SENSOR_GAIN', 0.0, 5.0)
        self._assign_physics_setting('MUTATION_SCALE_SETTING', self._state.MUTATION_SCALE, 'Mutation Scale', 'MUTATION_SCALE', -0.5, 0.5)
        self._assign_physics_setting('DRAG_SETTING', self._state.DRAG, 'Drag', 'DRAG', -1.0, 1.0)
        self._assign_physics_setting('STRAFE_POWER_SETTING', self._state.STRAFE_POWER, 'Strafe Power', 'STRAFE_POWER', 0.0, 0.5)
        self._assign_physics_setting('SENSOR_ANGLE_SETTING', self._state.SENSOR_ANGLE, 'Sensor Angle', 'SENSOR_ANGLE', -1.0, 1.0)
        self._assign_physics_setting('GLOBAL_FORCE_MULT_SETTING', self._state.GLOBAL_FORCE_MULT, 'Global Force Mult', 'GLOBAL_FORCE_MULT', 0.0, 2.0)
        self._assign_physics_setting('SENSOR_DISTANCE_SETTING', self._state.SENSOR_DISTANCE, 'Sensor Distance', 'SENSOR_DISTANCE', 0.0, 4.0)
        tryset(self.entity_update_program, 'DISABLE_SYMMETRY', self._state.DISABLE_SYMMETRY)
        tryset(self.entity_update_program, 'ABSOLUTE_ORIENTATION', self._state.ABSOLUTE_ORIENTATION)
        tryset(self.entity_update_program, 'ORIENTATION_MIX', self._state.ORIENTATION_MIX)
        tryset(self.entity_update_program, 'GRAVITY_FORCE', self._state.GRAVITY_FORCE)
        tryset(self.entity_update_program, 'GRAVITY_STRAFE', self._state.GRAVITY_STRAFE)
        # Rule seed from sim state (saved with physics configs)
        tryset(self.entity_update_program, 'RULE_SEED', self._state.rule_seed)

        # set global and conditionally global uniforms
        tryset(self.entity_update_program, 'BOUNDARY_CONDITIONS_MODE', self._state.boundary_conditions)
        tryset(self.entity_update_program, 'RESET_MODE', self._state.initial_conditions)
        tryset(self.entity_update_program, 'INIT_SPACING', self._state.init_spacing)
        tryset(self.entity_update_program, 'COHORTS', self._state.num_cohorts)
        self._assign_physics_setting('HAZARD_RATE_SETTING', self._state.HAZARD_RATE, 'Hazard Rate', 'HAZARD_RATE', 0.0, 0.05)
        self._assign_physics_setting('TRAIL_PERSISTENCE_SETTING', self._state.TRAIL_PERSISTENCE, 'Trail Persistence', 'TRAIL_PERSISTENCE', 0.0, 1.0)

        # Radio feature uniforms
        tryset(self.entity_update_program, 'RADIO_ENABLED', self._state.RADIO_ENABLED)
        tryset(self.entity_update_program, 'RADIO_TARGET_FREQ', self._state.RADIO_TARGET_FREQ)
        tryset(self.entity_update_program, 'RADIO_BANDWIDTH', self._state.RADIO_BANDWIDTH)

        # Appearance settings from sim state (now part of physics config)
        tryset(self.entity_update_program, 'HUE_SENSITIVITY', self._state.hue_sensitivity)
        tryset(self.entity_update_program, 'COLOR_BY_COHORT', self._state.color_by_cohort)

        # Generic scratch uniforms for live-coding
        if generics is not None:
            tryset(self.entity_update_program, 'generic03', generics[0:4])
            tryset(self.entity_update_program, 'generic47', generics[4:8])

        num_workgroups = (self.entity_count + 63) // 64
        ctx.memory_barrier()
        self.entity_update_program.run(num_workgroups)

    def can_update_3d(self):
        """Apply 3D canvas decay + diffusion via compute shader.

        Handles double-buffering: reads from can_read_index, writes to 1-can_read_index.
        """
        prog = self.canvas_update_3d_program
        tryset(prog, 'canvas_3d_size', (self.canvas_resolution, self.canvas_resolution, self.canvas_resolution))
        tryset(prog, 'BOUNDARY_CONDITIONS_MODE', self._state.boundary_conditions)
        tryset(prog, 'frame_count', self.frame_count)

        trail_persistence = self._state.TRAIL_PERSISTENCE
        trail_diffusion = self._state.TRAIL_DIFFUSION

        # TRAIL_PERSISTENCE PhysicsSetting
        min_val, max_val = self._get_slider_range('Trail Persistence', 0.0, 1.0)
        tryset(prog, 'TRAIL_PERSISTENCE_SETTING.slider_value', trail_persistence)
        tryset(prog, 'TRAIL_PERSISTENCE_SETTING.min_value', min_val)
        tryset(prog, 'TRAIL_PERSISTENCE_SETTING.max_value', max_val)
        if self._state.parameter_sweeps_enabled:
            tryset(prog, 'TRAIL_PERSISTENCE_SETTING.x_sweep', self._state.x_sweeps.get('TRAIL_PERSISTENCE', 0.0))
            tryset(prog, 'TRAIL_PERSISTENCE_SETTING.y_sweep', self._state.y_sweeps.get('TRAIL_PERSISTENCE', 0.0))
        else:
            tryset(prog, 'TRAIL_PERSISTENCE_SETTING.x_sweep', 0.0)
            tryset(prog, 'TRAIL_PERSISTENCE_SETTING.y_sweep', 0.0)
        tryset(prog, 'TRAIL_PERSISTENCE_SETTING.cohort_sweep', 0.0)  # No cohort in canvas
        tryset(prog, 'TRAIL_PERSISTENCE_SETTING.jitter', self._state.jitters.get('TRAIL_PERSISTENCE', 0.0))

        # TRAIL_DIFFUSION PhysicsSetting
        min_val, max_val = self._get_slider_range('Trail Diffusion', 0.0, 1.0)
        tryset(prog, 'TRAIL_DIFFUSION_SETTING.slider_value', trail_diffusion)
        tryset(prog, 'TRAIL_DIFFUSION_SETTING.min_value', min_val)
        tryset(prog, 'TRAIL_DIFFUSION_SETTING.max_value', max_val)
        if self._state.parameter_sweeps_enabled:
            tryset(prog, 'TRAIL_DIFFUSION_SETTING.x_sweep', self._state.x_sweeps.get('TRAIL_DIFFUSION', 0.0))
            tryset(prog, 'TRAIL_DIFFUSION_SETTING.y_sweep', self._state.y_sweeps.get('TRAIL_DIFFUSION', 0.0))
        else:
            tryset(prog, 'TRAIL_DIFFUSION_SETTING.x_sweep', 0.0)
            tryset(prog, 'TRAIL_DIFFUSION_SETTING.y_sweep', 0.0)
        tryset(prog, 'TRAIL_DIFFUSION_SETTING.cohort_sweep', 0.0)
        tryset(prog, 'TRAIL_DIFFUSION_SETTING.jitter', self._state.jitters.get('TRAIL_DIFFUSION', 0.0))

        # Bind read texture as sampler
        write_index = 1 - self.can_read_index
        self.can_3d[self.can_read_index].use(location=1)
        tryset(prog, 'can_tex', 1)

        # Bind write texture as image
        self.can_3d[write_index].bind_to_image(0, read=False, write=True)

        # Dispatch compute shader
        gx = (self.canvas_resolution + 3) // 4
        gy = (self.canvas_resolution + 3) // 4
        gz = (self.canvas_resolution + 3) // 4
        prog.run(gx, gy, gz)

        # Swap buffers
        self.can_read_index = write_index

    def update(self, ctx, generics: tuple = None):
        # Bind packed 3D canvas texture for entity_update sampling (sensors) and atomic splatting
        self.can_3d[self.can_read_index].use(location=1)
        self.can_3d[self.can_read_index].bind_to_image(0, read=False, write=True)

        current_time = time.time()
        self.time = current_time - self.start_time_stamp

        # 1. Entity physics + atomic splat (reads canvas for sensors, writes trails atomically)
        self.entity_update(ctx, generics=generics)

        # 2. Memory barrier: ensure atomic writes visible to canvas fragment shader
        ctx.memory_barrier()
        ctx.disable(moderngl.BLEND)

        # 3. Canvas decay + diffusion (3D compute shader path)
        self.can_update_3d()

        self.frame_count += 1

    def _clear_3d_textures(self):
        """Clear all 3D canvas textures to zero."""
        canvas_dim_x, canvas_dim_y = self.get_canvas_dimensions()
        zero_data = bytes(canvas_dim_x * canvas_dim_y * self.canvas_resolution * 8)  # 4 components × 2 bytes
        for tex in self.can_3d:
            tex.write(zero_data)

    def clear_canvas(self):
        """Clear only the trail/canvas textures (not particles or frame count)."""
        self._clear_3d_textures()

    def reset(self):
        self.frame_count = 0
        self._clear_3d_textures()

    def reload(self):
        print('reloading shaders')
        self.setup_shaders()
        print('reload done')

    def apply_state(self, state: SimState) -> None:
        """Apply state from Orchestrator before update."""
        self._state = state

        # Set canvas texture wrap mode: GL_REPEAT for Wrap (2), clamp-to-edge otherwise
        wrap = (state.boundary_conditions == 2)
        for tex in self.can_3d:
            tex.repeat_x = wrap
            tex.repeat_y = wrap
            tex.repeat_z = wrap

    def apply_camera_state(self, camera_state) -> None:
        """Apply camera state from Orchestrator before update."""
        self._camera_state = camera_state

    def _get_slider_range(self, slider_label: str, default_min: float, default_max: float) -> tuple[float, float]:
        """Get the current min/max range for a slider from sim state."""
        if self._state is None:
            return (default_min, default_max)

        if slider_label not in self._state.slider_ranges:
            return (default_min, default_max)

        return (self._state.slider_ranges[slider_label][0],
                self._state.slider_ranges[slider_label][1])

    def calculate_setting(self, slider_value: float, min_value: float, max_value: float,
                         pos: tuple[float, float], cohort: float,
                         x_sweep: float, y_sweep: float, cohort_sweep: float) -> float:
        """Python version of GLSL calculate_setting() function.

        SYNCHRONIZED: This function must match entity_update.glsl and canvas_update_3d.glsl
        Locations to synchronize: shaders/entity_update.glsl, shaders/canvas_update_3d.glsl, sim.py

        Calculates the effective parameter value based on sweeps and position/cohort.
        Mirrors the shader function for use when clicking particles to set slider values.

        Args:
            slider_value: Base slider value when no sweeps are active
            min_value: Minimum value for parameter sweeps
            max_value: Maximum value for parameter sweeps
            pos: (x, y) world position of entity in [-1, 1] range
            cohort: Raw cohort value in [0, num_cohorts) range (from entity buffer)
            x_sweep: Sweep mode (0.0 = off, 1.0 = normal, -1.0 = inverse)
            y_sweep: Sweep mode (0.0 = off, 1.0 = normal, -1.0 = inverse)
            cohort_sweep: Sweep mode (0.0 = off, 1.0 = normal, -1.0 = inverse)

        Returns:
            Effective parameter value at the given position/cohort
        """
        import math

        # If no sweeps active, return slider value
        if x_sweep == 0.0 and y_sweep == 0.0 and cohort_sweep == 0.0:
            return slider_value

        # Convert pos from [-1, 1] to [0, 1] for mixing
        pos_norm = ((pos[0] + 1) / 2, (pos[1] + 1) / 2)

        # Convert cohort to normalized [0, 1] range, matching shader:
        # cohort = floor(cohort) / float(get_particle_cohorts())
        cohort_norm = math.floor(cohort*self._state.num_cohorts) / float(self._state.num_cohorts)

        # Accumulate sweep contributions
        result = 0.0
        active_sweeps = 0

        if x_sweep != 0.0:
            # For inverse sweep (x_sweep < 0), swap min and max
            if x_sweep > 0.0:
                result += min_value + (max_value - min_value) * pos_norm[0]
            else:
                result += max_value + (min_value - max_value) * pos_norm[0]
            active_sweeps += 1

        if y_sweep != 0.0:
            # For inverse sweep (y_sweep < 0), swap min and max
            if y_sweep > 0.0:
                result += min_value + (max_value - min_value) * pos_norm[1]
            else:
                result += max_value + (min_value - max_value) * pos_norm[1]
            active_sweeps += 1

        if cohort_sweep != 0.0:
            # For inverse sweep (cohort_sweep < 0), swap min and max
            if cohort_sweep > 0.0:
                result += min_value + (max_value - min_value) * cohort_norm
            else:
                result += max_value + (min_value - max_value) * cohort_norm
            active_sweeps += 1

        # Average the results to keep within min/max range
        return result / active_sweeps if active_sweeps > 0 else slider_value

    def _assign_physics_setting(self, uniform_name: str, slider_value: float, slider_label: str, param_name: str, default_min: float, default_max: float):
        """Assign a PhysicsSetting struct uniform with dynamically fetched min/max ranges, sweep states, and jitter."""
        min_val, max_val = self._get_slider_range(slider_label, default_min, default_max)

        tryset(self.entity_update_program, f'{uniform_name}.slider_value', slider_value)
        tryset(self.entity_update_program, f'{uniform_name}.min_value', min_val)
        tryset(self.entity_update_program, f'{uniform_name}.max_value', max_val)
        # Only apply sweeps if parameter sweeps UI is enabled
        if self._state.parameter_sweeps_enabled:
            tryset(self.entity_update_program, f'{uniform_name}.x_sweep', self._state.x_sweeps.get(param_name, 0.0))
            tryset(self.entity_update_program, f'{uniform_name}.y_sweep', self._state.y_sweeps.get(param_name, 0.0))
            tryset(self.entity_update_program, f'{uniform_name}.cohort_sweep', self._state.cohort_sweeps.get(param_name, 0.0))
        else:
            tryset(self.entity_update_program, f'{uniform_name}.x_sweep', 0.0)
            tryset(self.entity_update_program, f'{uniform_name}.y_sweep', 0.0)
            tryset(self.entity_update_program, f'{uniform_name}.cohort_sweep', 0.0)
        # Always apply jitter (independent of parameter_sweeps_enabled)
        tryset(self.entity_update_program, f'{uniform_name}.jitter', self._state.jitters.get(param_name, 0.0))

    def apply_rule(self, rule: np.ndarray | None) -> None:
        """Apply a rule to the shader."""
        if rule is None:
            set_rule_uniform(self.entity_update_program, np.zeros((10, 12), dtype=np.float32))
        else:
            set_rule_uniform(self.entity_update_program, rule)

    def get_entity_buffer(self) -> moderngl.Buffer:
        """Expose entity buffer for EntityPicker."""
        return self.entities

    def get_rule_buffer(self) -> moderngl.Buffer:
        """Expose rule buffer for rule readback."""
        return self.rule_buffer

    def request_rule_buffer_update(self, entity_id: int) -> None:
        """Request a one-time rule buffer write for the next frame.

        This triggers the expensive rule buffer write (192MB) for exactly one frame,
        allowing subsequent readback of the mutated rule for the specified entity.

        Args:
            entity_id: The entity index to read back after the buffer is written
        """
        self._pending_rule_buffer_update = True
        self._pending_entity_id = entity_id

    def consume_pending_rule_readback(self) -> int | None:
        """Check if a rule readback is ready and consume the pending state.

        Call this AFTER entity_update has run. If a rule buffer update was pending,
        this returns the entity ID to read back and clears the pending state.

        Returns:
            Entity ID to read back, or None if no readback is pending
        """
        if self._pending_rule_buffer_update and self._pending_entity_id is not None:
            entity_id = self._pending_entity_id
            # Clear the pending state - the rule buffer has been written this frame
            self._pending_rule_buffer_update = False
            self._pending_entity_id = None
            return entity_id
        return None

    def update_sliders_from_particle(self, pos: tuple[float, float], cohort: float) -> None:
        """Update all slider values based on effective values at a particle's position/cohort.

        When a particle is clicked and parameter sweeps are active, this calculates what
        the effective parameter values are at that particle's location and updates the
        sliders to show those values.

        Args:
            pos: (x, y) world position of entity in [-1, 1] range
            cohort: Normalized cohort value in [0, 1] range
        """
        # Define all 12 parameters with their state field, slider label, and default ranges
        parameters = [
            ('AXIAL_FORCE', 'Axial Force', -1.0, 1.0),
            ('LATERAL_FORCE', 'Lateral Force', -1.0, 1.0),
            ('SENSOR_GAIN', 'Sensor Gain', 0.0, 5.0),
            ('MUTATION_SCALE', 'Mutation Scale', -0.5, 0.5),
            ('DRAG', 'Drag', -1.0, 1.0),
            ('STRAFE_POWER', 'Strafe Power', 0.0, 0.5),
            ('SENSOR_ANGLE', 'Sensor Angle', -1.0, 1.0),
            ('GLOBAL_FORCE_MULT', 'Global Force Mult', 0.0, 2.0),
            ('SENSOR_DISTANCE', 'Sensor Distance', 0.0, 4.0),
            ('TRAIL_PERSISTENCE', 'Trail Persistence', 0.0, 1.0),
            ('TRAIL_DIFFUSION', 'Trail Diffusion', 0.0, 1.0),
            ('HAZARD_RATE', 'Hazard Rate', 0.0, 0.05),
        ]

        for param_name, slider_label, default_min, default_max in parameters:
            # Get current slider value
            current_value = getattr(self._state, param_name)

            # Get sweep states for this parameter (only if parameter sweeps UI is enabled)
            if self._state.parameter_sweeps_enabled:
                x_sweep = self._state.x_sweeps.get(param_name, 0.0)
                y_sweep = self._state.y_sweeps.get(param_name, 0.0)
                cohort_sweep = self._state.cohort_sweeps.get(param_name, 0.0)
            else:
                x_sweep = 0.0
                y_sweep = 0.0
                cohort_sweep = 0.0

            # Only update if at least one sweep is active
            if x_sweep != 0.0 or y_sweep != 0.0 or cohort_sweep != 0.0:
                # Get min/max range for this parameter
                min_val, max_val = self._get_slider_range(slider_label, default_min, default_max)

                # Calculate effective value at this particle's position/cohort
                effective_value = self.calculate_setting(
                    current_value, min_val, max_val,
                    pos, cohort,
                    x_sweep, y_sweep, cohort_sweep
                )

                # Update the slider value
                setattr(self._state, param_name, effective_value)

    def has_active_cohort_sweep(self) -> bool:
        """Check if any cohort sweep is active."""
        if not self._state.parameter_sweeps_enabled:
            return False
        return any(v != 0.0 for v in self._state.cohort_sweeps.values())

    def has_active_xy_sweep(self) -> bool:
        """Check if any X or Y sweep is active."""
        if not self._state.parameter_sweeps_enabled:
            return False
        has_x = any(v != 0.0 for v in self._state.x_sweeps.values())
        has_y = any(v != 0.0 for v in self._state.y_sweeps.values())
        return has_x or has_y

    def update_sliders_from_position(self, pos: tuple[float, float]) -> None:
        """Update slider values based on position only (no cohort info needed).

        Used when clicking in parameter sweep mode without a cohort sweep active.
        Uses cohort=0.5 as a neutral value.

        Args:
            pos: (x, y) world position in [-1, 1] range
        """
        self.update_sliders_from_particle(pos, cohort=0.5)

    def get_sweep_reticle_position(self) -> tuple[float, float, bool]:
        """Calculate the reticle position based on current slider values and active sweeps.

        The reticle shows where on the screen the current slider values correspond to.
        This is the location where physics doesn't change when toggling sweeps.

        Returns:
            (x, y, visible): UV coordinates (0-1) and whether reticle should be visible.
                             Returns (0.5, 0.5, False) if no X/Y sweeps are active.
        """
        if not self._state.parameter_sweeps_enabled:
            return (0.5, 0.5, False)

        # Find the active X and Y sweep parameters
        x_param = None
        x_sweep_mode = 0.0
        y_param = None
        y_sweep_mode = 0.0

        for param_name in self._state.x_sweeps:
            mode = self._state.x_sweeps.get(param_name, 0.0)
            if mode != 0.0:
                x_param = param_name
                x_sweep_mode = mode
                break

        for param_name in self._state.y_sweeps:
            mode = self._state.y_sweeps.get(param_name, 0.0)
            if mode != 0.0:
                y_param = param_name
                y_sweep_mode = mode
                break

        # If no X or Y sweep is active, don't show reticle
        if x_param is None and y_param is None:
            return (0.5, 0.5, False)

        # Parameter definitions for getting slider ranges
        param_ranges = {
            'AXIAL_FORCE': ('Axial Force', -1.0, 1.0),
            'LATERAL_FORCE': ('Lateral Force', -1.0, 1.0),
            'SENSOR_GAIN': ('Sensor Gain', 0.0, 5.0),
            'MUTATION_SCALE': ('Mutation Scale', -0.5, 0.5),
            'DRAG': ('Drag', -1.0, 1.0),
            'STRAFE_POWER': ('Strafe Power', 0.0, 0.5),
            'SENSOR_ANGLE': ('Sensor Angle', -1.0, 1.0),
            'GLOBAL_FORCE_MULT': ('Global Force Mult', 0.0, 2.0),
            'SENSOR_DISTANCE': ('Sensor Distance', 0.0, 4.0),
            'TRAIL_PERSISTENCE': ('Trail Persistence', 0.0, 1.0),
            'TRAIL_DIFFUSION': ('Trail Diffusion', 0.0, 1.0),
            'HAZARD_RATE': ('Hazard Rate',0.0,0.05)
        }

        # Calculate X position
        if x_param is not None:
            slider_label, default_min, default_max = param_ranges[x_param]
            min_val, max_val = self._get_slider_range(slider_label, default_min, default_max)
            slider_value = getattr(self._state, x_param)
            # Invert the sweep formula: pos_norm = (slider_value - min) / (max - min)
            if max_val != min_val:
                x_norm = (slider_value - min_val) / (max_val - min_val)
            else:
                x_norm = 0.5
            # For inverse sweep, flip the position
            if x_sweep_mode < 0:
                x_norm = 1.0 - x_norm
            reticle_x = x_norm
        else:
            reticle_x = 0.5  # No X sweep - use center

        # Calculate Y position
        if y_param is not None:
            slider_label, default_min, default_max = param_ranges[y_param]
            min_val, max_val = self._get_slider_range(slider_label, default_min, default_max)
            slider_value = getattr(self._state, y_param)
            if max_val != min_val:
                y_norm = (slider_value - min_val) / (max_val - min_val)
            else:
                y_norm = 0.5
            if y_sweep_mode < 0:
                y_norm = 1.0 - y_norm
            reticle_y = y_norm
        else:
            reticle_y = 0.5  # No Y sweep - use center

        return (reticle_x, reticle_y, True)
