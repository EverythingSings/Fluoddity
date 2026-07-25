use std::borrow::Cow;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Arc, mpsc};
use std::time::Instant;

use gilrs::{Axis, Button, EventType, Gilrs};
use winit::application::ApplicationHandler;
use winit::dpi::LogicalSize;
use winit::event::{ElementState, KeyEvent, WindowEvent};
use winit::event_loop::{ActiveEventLoop, ControlFlow, EventLoop};
use winit::keyboard::{Key, NamedKey};
use winit::window::{Window, WindowAttributes, WindowId};

mod video_export;

use video_export::{
    FfmpegVideoRecorder, StagedArtifact, publish_staged_artifacts, validate_video_settings,
};

const DEFAULT_WIDTH: u32 = 1280;
const DEFAULT_HEIGHT: u32 = 800;
const VIDEO_WIDTH: u32 = 3840;
const VIDEO_HEIGHT: u32 = 2160;
const SIMULATION_HZ: u32 = 60;
const MAX_OBJECTIVE_ZONES: usize = 3;
const BASE_PARTICLE_COUNT: u32 = 8192;
const MAX_RENDER_AXIS: u32 = 4096;
const MAX_RENDER_PIXELS: u64 = 4096 * 4096;
const RULE_FLOAT_COUNT: usize = 80;
const PHYSICS_SETTING_COUNT: usize = 12;
const OVERLAY_TEXT_COLUMNS: usize = 96;
const OVERLAY_TEXT_ROWS: usize = 3;
const OVERLAY_TEXT_COUNT: usize = OVERLAY_TEXT_COLUMNS * OVERLAY_TEXT_ROWS;

#[derive(Clone, Copy)]
struct PromptAction {
    steam_action: &'static str,
    fallback_label: &'static str,
    label: &'static str,
}

#[repr(C)]
#[derive(Clone, Copy, bytemuck::Pod, bytemuck::Zeroable)]
struct Params {
    width: u32,
    height: u32,
    frame: u32,
    trial_count: u32,
    cursor_x: f32,
    cursor_y: f32,
    applying: u32,
    paused: u32,
    objective_zone_count: u32,
    zone0_x: f32,
    zone0_y: f32,
    zone0_radius: f32,
    zone1_x: f32,
    zone1_y: f32,
    zone1_radius: f32,
    _zone1_pad: f32,
    zone2_x: f32,
    zone2_y: f32,
    zone2_radius: f32,
    _zone2_pad: f32,
    hazard_center_x: f32,
    hazard_width: f32,
    hazard_strength: f32,
    hazard_enabled: u32,
    rival_x: f32,
    rival_y: f32,
    rival_radius: f32,
    rival_enabled: u32,
    rule_seed: u32,
    boundary_conditions: u32,
    initial_conditions: u32,
    num_cohorts: u32,
    sensor_distance: f32,
    sensor_angle: f32,
    sensor_gain: f32,
    mutation_scale: f32,
    drag: f32,
    strafe_power: f32,
    axial_force: f32,
    lateral_force: f32,
    global_force_mult: f32,
    trail_persistence: f32,
    trail_diffusion: f32,
    hazard_rate: f32,
    orientation_mix: f32,
    absolute_orientation: u32,
    disable_symmetry: u32,
    hue_sensitivity: f32,
    color_by_cohort: u32,
    watercolor_mode: u32,
    emboss_mode: u32,
    ink_weight: f32,
    emboss_intensity: f32,
    emboss_smoothness: f32,
    _appearance_pad0: f32,
    progress: f32,
    active_zone_mask: u32,
    run_status: u32,
    _runtime_pad0: u32,
}

#[repr(C)]
#[derive(Clone, Copy, bytemuck::Pod, bytemuck::Zeroable)]
struct Particle {
    x: f32,
    y: f32,
    vx: f32,
    vy: f32,
    cohort: u32,
    rule_seed: u32,
    _pad0: u32,
    _pad1: u32,
}

#[repr(C)]
#[derive(Clone, Copy, bytemuck::Pod, bytemuck::Zeroable)]
struct NativeSetting {
    slider_value: f32,
    min_value: f32,
    max_value: f32,
    x_sweep: f32,
    y_sweep: f32,
    cohort_sweep: f32,
    jitter: f32,
    _pad0: f32,
}

impl NativeSetting {
    fn new(slider_value: f32, min_value: f32, max_value: f32) -> Self {
        Self {
            slider_value,
            min_value,
            max_value,
            x_sweep: 0.0,
            y_sweep: 0.0,
            cohort_sweep: 0.0,
            jitter: 0.0,
            _pad0: 0.0,
        }
    }
}

#[derive(Clone)]
struct Args {
    trial_path: PathBuf,
    config_path: Option<PathBuf>,
    dump_config_contract_path: Option<PathBuf>,
    dump_input_contract_path: Option<PathBuf>,
    dump_input_smoke_path: Option<PathBuf>,
    frame_count: u32,
    out_path: Option<PathBuf>,
    render_width: u32,
    render_height: u32,
    video_out_path: Option<PathBuf>,
    video_report_path: Option<PathBuf>,
    video_fps: u32,
    video_crf: u8,
    video_preset: String,
    ffmpeg_path: Option<PathBuf>,
    requested_video_frames: Option<u32>,
    window: bool,
    max_window_frames: Option<u32>,
    timing_report_path: Option<PathBuf>,
    deck_profile: bool,
    trial_id: Option<String>,
}

#[derive(Clone, Copy)]
struct InputState {
    cursor_x: f32,
    cursor_y: f32,
    applying: bool,
    paused: bool,
    right_x: f32,
    right_y: f32,
}

impl InputState {
    fn new(cursor_x: f32, cursor_y: f32) -> Self {
        Self {
            cursor_x,
            cursor_y,
            applying: false,
            paused: false,
            right_x: 0.0,
            right_y: 0.0,
        }
    }
}

#[derive(Clone)]
struct TrialRuntime {
    trial_index: u32,
    trial_count: u32,
    trial_id: String,
    title: String,
    objective: String,
    running_hint: String,
    zones: [ObjectiveZone; MAX_OBJECTIVE_ZONES],
    zone_count: u32,
    hold_seconds: f32,
    failure_seconds: f32,
    activity_threshold: f32,
    win_condition: WinCondition,
    hazard_enabled: bool,
    hazard_center_x: f32,
    hazard_width: f32,
    hazard_strength: f32,
    rival_enabled: bool,
    rival_x: f32,
    rival_y: f32,
    rival_radius: f32,
    rival_growth: f32,
    rival_activity_threshold: f32,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum WinCondition {
    HoldAllZones,
    TerritoryAtTimeout,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum RunStatus {
    Briefing,
    Running,
    Won,
    Failed,
}

impl RunStatus {
    fn code(self) -> u32 {
        match self {
            Self::Briefing => 0,
            Self::Running => 1,
            Self::Won => 2,
            Self::Failed => 3,
        }
    }
}

#[derive(Clone)]
struct TrialRunState {
    status: RunStatus,
    elapsed_seconds: f32,
    progress: f32,
    active_zone_mask: u32,
    player_controlled_zones: u32,
    rival_controlled_zones: u32,
    objective_status: String,
    result_title: String,
    result_summary: String,
    last_sample_frame: u32,
}

impl TrialRunState {
    fn new(trial: &TrialRuntime) -> Self {
        Self {
            status: RunStatus::Briefing,
            elapsed_seconds: 0.0,
            progress: 0.0,
            active_zone_mask: 0,
            player_controlled_zones: 0,
            rival_controlled_zones: 0,
            objective_status: "Awaiting protocol.".to_owned(),
            result_title: String::new(),
            result_summary: trial.running_hint.clone(),
            last_sample_frame: 0,
        }
    }

    fn start(&mut self, trial: &TrialRuntime) {
        if self.status == RunStatus::Briefing {
            self.status = RunStatus::Running;
            self.objective_status = trial.running_hint.clone();
            self.result_summary.clear();
        }
    }

    fn reset_to_briefing(&mut self, trial: &TrialRuntime) {
        *self = Self::new(trial);
    }

    fn running(&self) -> bool {
        self.status == RunStatus::Running
    }

    fn update_from_pixels(
        &mut self,
        trial: &TrialRuntime,
        pixels: &[u32],
        width: u32,
        height: u32,
        dt: f32,
    ) {
        if self.status != RunStatus::Running {
            return;
        }
        self.elapsed_seconds += dt.max(0.0);
        let active_mask = sample_active_zones(trial, pixels, width, height);
        self.active_zone_mask = active_mask;
        self.player_controlled_zones = active_mask.count_ones();
        self.rival_controlled_zones = rival_controlled_zones(trial, self.elapsed_seconds);

        if trial.win_condition == WinCondition::TerritoryAtTimeout {
            self.progress = (self.elapsed_seconds / trial.failure_seconds.max(0.001)).min(1.0);
            let margin = self.player_controlled_zones as i32 - self.rival_controlled_zones as i32;
            self.objective_status = format!(
                "Site control {} vs rival {}; margin {}.",
                self.player_controlled_zones, self.rival_controlled_zones, margin
            );
            if self.elapsed_seconds >= trial.failure_seconds {
                if margin > 0 {
                    self.win(format!(
                        "Rival Contained: held {} sites against {}.",
                        self.player_controlled_zones, self.rival_controlled_zones
                    ));
                } else {
                    self.fail(format!(
                        "Rival Overgrowth: held {} sites against {}.",
                        self.player_controlled_zones, self.rival_controlled_zones
                    ));
                }
            }
            return;
        }

        let all_zones_active =
            self.player_controlled_zones >= trial.zone_count && trial.zone_count > 0;
        if all_zones_active {
            self.progress = (self.progress + dt / trial.hold_seconds.max(0.001)).min(1.0);
        } else {
            self.progress = (self.progress - dt / (trial.hold_seconds.max(0.001) * 1.5)).max(0.0);
        }
        let hold_remaining = (trial.hold_seconds * (1.0 - self.progress)).max(0.0);
        self.objective_status = if all_zones_active {
            format!("Culture stable; hold {:.0}s.", hold_remaining.ceil())
        } else {
            format!(
                "Active sites {}/{}; feed marked zones.",
                self.player_controlled_zones, trial.zone_count
            )
        };

        if self.progress >= 1.0 {
            self.win(format!(
                "Culture Stabilized: held {} marked site(s).",
                self.player_controlled_zones
            ));
        } else if self.elapsed_seconds >= trial.failure_seconds {
            self.fail(format!(
                "Culture Failed: active sites {}/{} at timeout.",
                self.player_controlled_zones, trial.zone_count
            ));
        }
    }

    fn win(&mut self, summary: String) {
        self.status = RunStatus::Won;
        self.progress = 1.0;
        self.objective_status = "Assay complete.".to_owned();
        self.result_title = "SUCCESS".to_owned();
        self.result_summary = summary;
        println!(
            "trial_runtime_result status=won summary=\"{}\"",
            self.result_summary
        );
    }

    fn fail(&mut self, summary: String) {
        self.status = RunStatus::Failed;
        self.objective_status = "Assay failed.".to_owned();
        self.result_title = "FAILED".to_owned();
        self.result_summary = summary;
        println!(
            "trial_runtime_result status=failed summary=\"{}\"",
            self.result_summary
        );
    }

    fn overlay_rows(&self, trial: &TrialRuntime) -> [String; OVERLAY_TEXT_ROWS] {
        let title = if self.result_title.is_empty() {
            trial.title.clone()
        } else {
            format!("{} - {}", trial.title, self.result_title)
        };
        let status = match self.status {
            RunStatus::Briefing => format!("READY: {}", trial.objective),
            RunStatus::Running => self.objective_status.clone(),
            RunStatus::Won | RunStatus::Failed => {
                format!("{} {}", self.result_summary, self.result_next_step(trial))
            }
        };
        let prompt = match self.status {
            RunStatus::Briefing => "A START   RT APPLY   MENU PAUSE".to_owned(),
            RunStatus::Running => format!(
                "PROGRESS {:03}%   A RESUME   RT APPLY   MENU PAUSE",
                (self.progress * 100.0).round() as u32
            ),
            RunStatus::Won | RunStatus::Failed => self.result_prompt(trial),
        };
        [title, status, prompt]
    }

    fn result_next_step(&self, trial: &TrialRuntime) -> String {
        if self.status != RunStatus::Won && self.status != RunStatus::Failed {
            return String::new();
        }
        if is_final_trial(trial) {
            "Sequence complete; A restarts Trial 1.".to_owned()
        } else if self.status == RunStatus::Won {
            "Next assay unlocked; A opens the next briefing.".to_owned()
        } else {
            "Retry or continue; A opens the next briefing.".to_owned()
        }
    }

    fn result_prompt(&self, trial: &TrialRuntime) -> String {
        if is_final_trial(trial) {
            "A RESTART TRIAL 1   VIEW EXIT".to_owned()
        } else {
            "A NEXT ASSAY   VIEW EXIT".to_owned()
        }
    }

    fn prompt_actions(&self, trial: &TrialRuntime) -> Vec<PromptAction> {
        match self.status {
            RunStatus::Briefing => vec![
                PromptAction {
                    steam_action: "StartExperiment",
                    fallback_label: "A",
                    label: "Start",
                },
                PromptAction {
                    steam_action: "ApplyNutrientGel",
                    fallback_label: "R2",
                    label: "Apply",
                },
                PromptAction {
                    steam_action: "PauseExperiment",
                    fallback_label: "Menu",
                    label: "Pause",
                },
            ],
            RunStatus::Running => vec![
                PromptAction {
                    steam_action: "AimNutrientGel",
                    fallback_label: "Right Stick",
                    label: "Aim",
                },
                PromptAction {
                    steam_action: "ApplyNutrientGel",
                    fallback_label: "R2",
                    label: "Apply",
                },
                PromptAction {
                    steam_action: "PauseExperiment",
                    fallback_label: "Menu",
                    label: "Pause",
                },
            ],
            RunStatus::Won | RunStatus::Failed => vec![
                PromptAction {
                    steam_action: "StartExperiment",
                    fallback_label: "A",
                    label: if is_final_trial(trial) {
                        "Restart Trial 1"
                    } else {
                        "Next Assay"
                    },
                },
                PromptAction {
                    steam_action: "ExitExperiment",
                    fallback_label: "View",
                    label: "Exit",
                },
            ],
        }
    }
}

fn is_final_trial(trial: &TrialRuntime) -> bool {
    trial.trial_count > 0 && trial.trial_index + 1 >= trial.trial_count
}

#[derive(Clone)]
struct RuntimeConfig {
    source: Option<PathBuf>,
    notes: String,
    rule_seed: u32,
    rule_seed_value: f32,
    sensor_distance: f32,
    sensor_angle: f32,
    sensor_gain: f32,
    mutation_scale: f32,
    drag: f32,
    strafe_power: f32,
    axial_force: f32,
    lateral_force: f32,
    global_force_mult: f32,
    trail_persistence: f32,
    trail_diffusion: f32,
    hazard_rate: f32,
    orientation_mix: f32,
    absolute_orientation: u32,
    disable_symmetry: bool,
    hue_sensitivity: f32,
    color_by_cohort: bool,
    ink_weight: f32,
    watercolor_mode: bool,
    emboss_mode: u32,
    emboss_intensity: f32,
    emboss_smoothness: f32,
    parameter_sweeps_enabled: bool,
    boundary_conditions: u32,
    initial_conditions: u32,
    num_cohorts: u32,
    physics_settings: [NativeSetting; PHYSICS_SETTING_COUNT],
    rule_coefficients: [f32; RULE_FLOAT_COUNT],
    has_saved_rule: bool,
}

#[derive(Clone, Copy, Default)]
struct ObjectiveZone {
    x: f32,
    y: f32,
    radius: f32,
}

struct GpuCore {
    device: wgpu::Device,
    queue: wgpu::Queue,
    width: u32,
    height: u32,
    particle_count: u32,
    pixels: wgpu::Buffer,
    _particles: wgpu::Buffer,
    _trails: [wgpu::Buffer; 2],
    _rule_coefficients: wgpu::Buffer,
    _physics_settings: wgpu::Buffer,
    overlay_text: wgpu::Buffer,
    params: wgpu::Buffer,
    background_pipeline: wgpu::ComputePipeline,
    particle_pipeline: wgpu::ComputePipeline,
    compute_bind_groups: [wgpu::BindGroup; 2],
    render_pipeline: Option<wgpu::RenderPipeline>,
    present_bind_group: wgpu::BindGroup,
    export_pipeline: wgpu::RenderPipeline,
    export_texture: wgpu::Texture,
    export_readback: wgpu::Buffer,
    export_padded_row_bytes: u32,
}

impl GpuCore {
    async fn new(
        instance: &wgpu::Instance,
        surface: Option<&wgpu::Surface<'_>>,
        surface_format: Option<wgpu::TextureFormat>,
        width: u32,
        height: u32,
        runtime_config: &RuntimeConfig,
        trial: &TrialRuntime,
    ) -> Result<Self, Box<dyn std::error::Error>> {
        let adapter = instance
            .request_adapter(&wgpu::RequestAdapterOptions {
                power_preference: wgpu::PowerPreference::HighPerformance,
                compatible_surface: surface,
                force_fallback_adapter: false,
            })
            .await?;
        let info = adapter.get_info();
        println!(
            "wgpu_adapter name=\"{}\" backend={:?} device_type={:?}",
            info.name, info.backend, info.device_type
        );

        let (device, queue) = adapter
            .request_device(&wgpu::DeviceDescriptor {
                label: Some("fluoddity-wgpu-spike-device"),
                required_features: wgpu::Features::empty(),
                required_limits: wgpu::Limits::default(),
                experimental_features: wgpu::ExperimentalFeatures::disabled(),
                memory_hints: wgpu::MemoryHints::Performance,
                trace: wgpu::Trace::Off,
            })
            .await?;

        let pixel_count = usize::try_from(u64::from(width) * u64::from(height))?;
        let pixel_bytes = (pixel_count * std::mem::size_of::<u32>()) as u64;
        let pixels = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("pixel-storage"),
            size: pixel_bytes,
            usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_SRC,
            mapped_at_creation: false,
        });
        let trails = [
            device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("trail-storage-a"),
                size: pixel_bytes,
                usage: wgpu::BufferUsages::STORAGE,
                mapped_at_creation: false,
            }),
            device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("trail-storage-b"),
                size: pixel_bytes,
                usage: wgpu::BufferUsages::STORAGE,
                mapped_at_creation: false,
            }),
        ];
        let particle_count = particle_count_for_resolution(width, height);
        let initial_particles = initial_particles(runtime_config, particle_count, width);
        let particles = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("particle-storage"),
            size: (initial_particles.len() * std::mem::size_of::<Particle>()) as u64,
            usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        queue.write_buffer(&particles, 0, bytemuck::cast_slice(&initial_particles));
        let rule_coefficients = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("rule-coefficients"),
            size: (RULE_FLOAT_COUNT * std::mem::size_of::<f32>()) as u64,
            usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        queue.write_buffer(
            &rule_coefficients,
            0,
            bytemuck::cast_slice(&runtime_config.rule_coefficients),
        );
        let physics_settings = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("physics-settings"),
            size: (PHYSICS_SETTING_COUNT * std::mem::size_of::<NativeSetting>()) as u64,
            usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        queue.write_buffer(
            &physics_settings,
            0,
            bytemuck::cast_slice(&runtime_config.physics_settings),
        );
        let overlay_text_data = overlay_text_buffer(&TrialRunState::new(trial), trial);
        let overlay_text = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("overlay-text"),
            size: (OVERLAY_TEXT_COUNT * std::mem::size_of::<u32>()) as u64,
            usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        queue.write_buffer(&overlay_text, 0, bytemuck::cast_slice(&overlay_text_data));
        let params = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("params"),
            size: std::mem::size_of::<Params>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });

        let compute_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("spike-compute-bind-group-layout"),
            entries: &[
                storage_entry(0, wgpu::ShaderStages::COMPUTE, false),
                uniform_entry(1, wgpu::ShaderStages::COMPUTE),
                storage_entry(2, wgpu::ShaderStages::COMPUTE, false),
                storage_entry(3, wgpu::ShaderStages::COMPUTE, true),
                storage_entry(4, wgpu::ShaderStages::COMPUTE, true),
                storage_entry(5, wgpu::ShaderStages::COMPUTE, true),
                storage_entry(6, wgpu::ShaderStages::COMPUTE, true),
                storage_entry(7, wgpu::ShaderStages::COMPUTE, false),
            ],
        });
        let background_shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("spike-background"),
            source: wgpu::ShaderSource::Wgsl(Cow::Borrowed(include_str!("spike.wgsl"))),
        });
        let particle_shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("spike-particles"),
            source: wgpu::ShaderSource::Wgsl(Cow::Borrowed(include_str!("particles.wgsl"))),
        });
        let compute_pipeline_layout =
            device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
                label: Some("spike-compute-pipeline-layout"),
                bind_group_layouts: &[Some(&compute_layout)],
                immediate_size: 0,
            });
        let background_pipeline =
            device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
                label: Some("spike-background-pipeline"),
                layout: Some(&compute_pipeline_layout),
                module: &background_shader,
                entry_point: Some("main"),
                compilation_options: wgpu::PipelineCompilationOptions::default(),
                cache: None,
            });
        let particle_pipeline = device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("spike-particle-pipeline"),
            layout: Some(&compute_pipeline_layout),
            module: &particle_shader,
            entry_point: Some("main"),
            compilation_options: wgpu::PipelineCompilationOptions::default(),
            cache: None,
        });
        let compute_bind_group_a_to_b = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("spike-compute-bind-group-a-to-b"),
            layout: &compute_layout,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: pixels.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: params.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 2,
                    resource: particles.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 3,
                    resource: trails[0].as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 4,
                    resource: rule_coefficients.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 5,
                    resource: overlay_text.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 6,
                    resource: physics_settings.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 7,
                    resource: trails[1].as_entire_binding(),
                },
            ],
        });
        let compute_bind_group_b_to_a = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("spike-compute-bind-group-b-to-a"),
            layout: &compute_layout,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: pixels.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: params.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 2,
                    resource: particles.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 3,
                    resource: trails[1].as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 4,
                    resource: rule_coefficients.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 5,
                    resource: overlay_text.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 6,
                    resource: physics_settings.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 7,
                    resource: trails[0].as_entire_binding(),
                },
            ],
        });
        let compute_bind_groups = [compute_bind_group_a_to_b, compute_bind_group_b_to_a];

        let render_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("spike-render-bind-group-layout"),
            entries: &[
                storage_entry(0, wgpu::ShaderStages::FRAGMENT, true),
                uniform_entry(1, wgpu::ShaderStages::FRAGMENT),
            ],
        });
        let present_shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("spike-present"),
            source: wgpu::ShaderSource::Wgsl(Cow::Borrowed(include_str!("present.wgsl"))),
        });
        let render_pipeline_layout =
            device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
                label: Some("spike-render-pipeline-layout"),
                bind_group_layouts: &[Some(&render_layout)],
                immediate_size: 0,
            });
        let present_bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("spike-render-bind-group"),
            layout: &render_layout,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: pixels.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: params.as_entire_binding(),
                },
            ],
        });
        let render_pipeline = surface_format.map(|format| {
            create_present_pipeline(
                &device,
                &render_pipeline_layout,
                &present_shader,
                format,
                "spike-surface-pipeline",
            )
        });
        let export_format = wgpu::TextureFormat::Rgba8UnormSrgb;
        let export_pipeline = create_present_pipeline(
            &device,
            &render_pipeline_layout,
            &present_shader,
            export_format,
            "spike-export-pipeline",
        );
        let export_texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("spike-export-texture"),
            size: wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: export_format,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
            view_formats: &[],
        });
        let unpadded_row_bytes = width * 4;
        let export_padded_row_bytes = unpadded_row_bytes
            .div_ceil(wgpu::COPY_BYTES_PER_ROW_ALIGNMENT)
            * wgpu::COPY_BYTES_PER_ROW_ALIGNMENT;
        let export_readback = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("spike-export-readback"),
            size: u64::from(export_padded_row_bytes) * u64::from(height),
            usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });

        Ok(Self {
            device,
            queue,
            width,
            height,
            particle_count,
            pixels,
            _particles: particles,
            _trails: trails,
            _rule_coefficients: rule_coefficients,
            _physics_settings: physics_settings,
            overlay_text,
            params,
            background_pipeline,
            particle_pipeline,
            compute_bind_groups,
            render_pipeline,
            present_bind_group,
            export_pipeline,
            export_texture,
            export_readback,
            export_padded_row_bytes,
        })
    }

    fn encode_compute(&self, encoder: &mut wgpu::CommandEncoder, params: Params) {
        self.queue
            .write_buffer(&self.params, 0, bytemuck::bytes_of(&params));
        let compute_bind_group = &self.compute_bind_groups[(params.frame & 1) as usize];
        let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor {
            label: Some("spike-background-pass"),
            timestamp_writes: None,
        });
        pass.set_pipeline(&self.background_pipeline);
        pass.set_bind_group(0, compute_bind_group, &[]);
        pass.dispatch_workgroups(self.width.div_ceil(16), self.height.div_ceil(16), 1);
        drop(pass);

        let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor {
            label: Some("spike-particle-pass"),
            timestamp_writes: None,
        });
        pass.set_pipeline(&self.particle_pipeline);
        pass.set_bind_group(0, compute_bind_group, &[]);
        pass.dispatch_workgroups(self.particle_count.div_ceil(64), 1, 1);
    }

    fn update_overlay_text(&self, state: &TrialRunState, trial: &TrialRuntime) {
        let overlay_text_data = overlay_text_buffer(state, trial);
        self.queue.write_buffer(
            &self.overlay_text,
            0,
            bytemuck::cast_slice(&overlay_text_data),
        );
    }

    fn render_to_surface(
        &self,
        surface_texture: &wgpu::SurfaceTexture,
        params: Params,
    ) -> Result<(), Box<dyn std::error::Error>> {
        let view = surface_texture
            .texture
            .create_view(&wgpu::TextureViewDescriptor::default());
        let mut encoder = self
            .device
            .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                label: Some("spike-window-encoder"),
            });
        self.encode_compute(&mut encoder, params);
        let (viewport_x, viewport_y, viewport_width, viewport_height) = aspect_fit_viewport(
            self.width,
            self.height,
            surface_texture.texture.width(),
            surface_texture.texture.height(),
        );
        {
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("spike-render-pass"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &view,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                        store: wgpu::StoreOp::Store,
                    },
                    depth_slice: None,
                })],
                depth_stencil_attachment: None,
                timestamp_writes: None,
                occlusion_query_set: None,
                multiview_mask: None,
            });
            pass.set_pipeline(
                self.render_pipeline
                    .as_ref()
                    .ok_or("missing render pipeline")?,
            );
            pass.set_bind_group(0, &self.present_bind_group, &[]);
            pass.set_viewport(
                viewport_x as f32,
                viewport_y as f32,
                viewport_width as f32,
                viewport_height as f32,
                0.0,
                1.0,
            );
            pass.set_scissor_rect(viewport_x, viewport_y, viewport_width, viewport_height);
            pass.draw(0..3, 0..1);
        }
        self.queue.submit(Some(encoder.finish()));
        Ok(())
    }

    fn readback_pixels(&self) -> Result<Vec<u32>, Box<dyn std::error::Error>> {
        let pixel_count = usize::try_from(u64::from(self.width) * u64::from(self.height))?;
        let pixel_bytes = (pixel_count * std::mem::size_of::<u32>()) as u64;
        let readback = self.device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("readback"),
            size: pixel_bytes,
            usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let mut encoder = self
            .device
            .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                label: Some("spike-readback-encoder"),
            });
        encoder.copy_buffer_to_buffer(&self.pixels, 0, &readback, 0, pixel_bytes);
        self.queue.submit(Some(encoder.finish()));

        let slice = readback.slice(..);
        let (map_sender, map_receiver) = mpsc::channel();
        slice.map_async(wgpu::MapMode::Read, move |result| {
            let _ = map_sender.send(result);
        });
        let _ = self.device.poll(wgpu::PollType::wait_indefinitely());
        map_receiver.recv()??;
        let mapped = slice.get_mapped_range();
        let raw_pixels: Vec<u32> = bytemuck::cast_slice(&mapped).to_vec();
        drop(mapped);
        readback.unmap();
        Ok(raw_pixels)
    }

    fn readback_presented_rgba(
        &self,
        params: Params,
    ) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
        self.queue
            .write_buffer(&self.params, 0, bytemuck::bytes_of(&params));
        let view = self
            .export_texture
            .create_view(&wgpu::TextureViewDescriptor::default());
        let mut encoder = self
            .device
            .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                label: Some("spike-export-encoder"),
            });
        {
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("spike-export-present-pass"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &view,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                        store: wgpu::StoreOp::Store,
                    },
                    depth_slice: None,
                })],
                depth_stencil_attachment: None,
                timestamp_writes: None,
                occlusion_query_set: None,
                multiview_mask: None,
            });
            pass.set_pipeline(&self.export_pipeline);
            pass.set_bind_group(0, &self.present_bind_group, &[]);
            pass.draw(0..3, 0..1);
        }
        encoder.copy_texture_to_buffer(
            wgpu::TexelCopyTextureInfo {
                texture: &self.export_texture,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            wgpu::TexelCopyBufferInfo {
                buffer: &self.export_readback,
                layout: wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(self.export_padded_row_bytes),
                    rows_per_image: Some(self.height),
                },
            },
            wgpu::Extent3d {
                width: self.width,
                height: self.height,
                depth_or_array_layers: 1,
            },
        );
        self.queue.submit(Some(encoder.finish()));

        let slice = self.export_readback.slice(..);
        let (map_sender, map_receiver) = mpsc::channel();
        slice.map_async(wgpu::MapMode::Read, move |result| {
            let _ = map_sender.send(result);
        });
        let _ = self.device.poll(wgpu::PollType::wait_indefinitely());
        map_receiver.recv()??;
        let mapped = slice.get_mapped_range();
        let unpadded_row_bytes = usize::try_from(self.width * 4)?;
        let padded_row_bytes = usize::try_from(self.export_padded_row_bytes)?;
        let mut rgba = Vec::with_capacity(
            unpadded_row_bytes
                .checked_mul(self.height as usize)
                .ok_or("export frame size overflow")?,
        );
        for row in mapped
            .chunks_exact(padded_row_bytes)
            .take(self.height as usize)
        {
            rgba.extend_from_slice(&row[..unpadded_row_bytes]);
        }
        drop(mapped);
        self.export_readback.unmap();
        Ok(rgba)
    }

    fn readback_nonblank(
        &self,
        out_path: &Path,
        params: Params,
    ) -> Result<usize, Box<dyn std::error::Error>> {
        let rgba = self.readback_presented_rgba(params)?;
        let nonblank_pixels = rgba
            .chunks_exact(4)
            .filter(|pixel| pixel[0] != 0 || pixel[1] != 0 || pixel[2] != 0)
            .count();
        if nonblank_pixels == 0 {
            return Err("wgpu spike produced a blank frame".into());
        }
        write_ppm_rgba(out_path, self.width, self.height, &rgba)?;
        Ok(nonblank_pixels)
    }
}

struct WindowApp {
    args: Args,
    trials: Vec<TrialRuntime>,
    trial_index: usize,
    trial: TrialRuntime,
    runtime_config: RuntimeConfig,
    window: Option<Arc<Window>>,
    instance: Option<wgpu::Instance>,
    surface: Option<wgpu::Surface<'static>>,
    config: Option<wgpu::SurfaceConfiguration>,
    gpu: Option<GpuCore>,
    input: InputState,
    run_state: TrialRunState,
    gilrs: Option<Gilrs>,
    frame: u32,
    started: Instant,
    frame_times_ms: Vec<f64>,
    pending_sample_seconds: f32,
    video_recorder: Option<FfmpegVideoRecorder>,
    video_started: Option<Instant>,
    video_frames: u32,
    video_has_nonblank_frame: bool,
    last_rendered_state: TrialRunState,
    fatal_error: Option<String>,
    exit_requested: bool,
}

impl WindowApp {
    fn new(
        args: Args,
        trials: Vec<TrialRuntime>,
        trial_index: usize,
        runtime_config: RuntimeConfig,
    ) -> Self {
        let trial = trials[trial_index].clone();
        let cursor_x = trial.zones[0].x;
        let cursor_y = trial.zones[0].y;
        let mut run_state = TrialRunState::new(&trial);
        if args.deck_profile {
            run_state.start(&trial);
        }
        let last_rendered_state = run_state.clone();
        Self {
            args,
            trials,
            trial_index,
            trial,
            runtime_config,
            window: None,
            instance: None,
            surface: None,
            config: None,
            gpu: None,
            input: InputState::new(cursor_x, cursor_y),
            run_state,
            gilrs: Gilrs::new().ok(),
            frame: 0,
            started: Instant::now(),
            frame_times_ms: Vec::new(),
            pending_sample_seconds: 0.0,
            video_recorder: None,
            video_started: None,
            video_frames: 0,
            video_has_nonblank_frame: false,
            last_rendered_state,
            fatal_error: None,
            exit_requested: false,
        }
    }

    fn init(&mut self, event_loop: &ActiveEventLoop) -> Result<(), Box<dyn std::error::Error>> {
        if self.window.is_some() {
            return Ok(());
        }
        let (_, _, preview_width, preview_height) = aspect_fit_viewport(
            self.args.render_width,
            self.args.render_height,
            DEFAULT_WIDTH,
            DEFAULT_HEIGHT,
        );
        let window = Arc::new(
            event_loop.create_window(
                WindowAttributes::default()
                    .with_title("Xenoculture: Trial Dish")
                    .with_inner_size(LogicalSize::new(
                        f64::from(preview_width),
                        f64::from(preview_height),
                    )),
            )?,
        );
        let instance = wgpu::Instance::new(wgpu::InstanceDescriptor::new_without_display_handle());
        let surface = instance.create_surface(window.clone())?;
        let adapter = pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions {
            power_preference: wgpu::PowerPreference::HighPerformance,
            compatible_surface: Some(&surface),
            force_fallback_adapter: false,
        }))?;
        let size = window.inner_size();
        let mut config = surface
            .get_default_config(&adapter, size.width.max(1), size.height.max(1))
            .ok_or("surface is not supported by selected adapter")?;
        config.present_mode = wgpu::PresentMode::Fifo;

        // Recreate the GPU core with the same surface compatibility and final format.
        let gpu = pollster::block_on(GpuCore::new(
            &instance,
            Some(&surface),
            Some(config.format),
            self.args.render_width,
            self.args.render_height,
            &self.runtime_config,
            &self.trial,
        ))?;
        surface.configure(&gpu.device, &config);
        println!(
            "wgpu_window_result width={} height={} format={:?}",
            config.width, config.height, config.format
        );
        if let Some(output_path) = self.args.video_out_path.as_deref() {
            self.video_recorder = Some(FfmpegVideoRecorder::start(
                self.args.ffmpeg_path.as_deref(),
                output_path,
                self.args.render_width,
                self.args.render_height,
                self.args.video_fps,
                self.args.video_crf,
                &self.args.video_preset,
            )?);
            self.video_started = Some(Instant::now());
            println!(
                "native_window_recording_started output={} width={} height={} fps={}",
                output_path.display(),
                self.args.render_width,
                self.args.render_height,
                self.args.video_fps
            );
        }
        self.window = Some(window);
        self.instance = Some(instance);
        self.surface = Some(surface);
        self.config = Some(config);
        self.gpu = Some(gpu);
        Ok(())
    }

    fn params(&self) -> Params {
        params_for_frame(
            self.frame,
            self.args.render_width,
            self.args.render_height,
            &self.trial,
            &self.input,
            &self.run_state,
            &self.runtime_config,
        )
    }

    fn start_or_resume(&mut self) {
        match self.run_state.status {
            RunStatus::Briefing => self.run_state.start(&self.trial),
            RunStatus::Won | RunStatus::Failed => {
                self.advance_or_reset_trial();
            }
            RunStatus::Running => {}
        }
        self.input.paused = false;
    }

    fn advance_or_reset_trial(&mut self) {
        self.trial_index = next_trial_index(self.trial_index, self.trials.len());
        self.trial = self.trials[self.trial_index].clone();
        self.input = InputState::new(self.trial.zones[0].x, self.trial.zones[0].y);
        self.run_state = TrialRunState::new(&self.trial);
    }

    fn poll_controller(&mut self) {
        let Some(gilrs) = self.gilrs.as_mut() else {
            return;
        };
        let mut should_start_or_resume = false;
        while let Some(event) = gilrs.next_event() {
            match event.event {
                EventType::ButtonPressed(Button::South, _) => should_start_or_resume = true,
                EventType::ButtonPressed(Button::Start, _)
                | EventType::ButtonPressed(Button::Mode, _) => {
                    self.input.paused = !self.input.paused;
                }
                EventType::ButtonPressed(Button::Select, _) => {
                    self.exit_requested = true;
                }
                EventType::ButtonPressed(Button::RightTrigger2, _)
                | EventType::ButtonPressed(Button::RightTrigger, _) => {
                    self.input.applying = true;
                }
                EventType::ButtonReleased(Button::RightTrigger2, _)
                | EventType::ButtonReleased(Button::RightTrigger, _) => {
                    self.input.applying = false;
                }
                EventType::AxisChanged(Axis::RightStickX, value, _) => {
                    self.input.right_x = deadzone(value);
                }
                EventType::AxisChanged(Axis::RightStickY, value, _) => {
                    self.input.right_y = deadzone(value);
                }
                _ => {}
            }
        }
        if should_start_or_resume {
            self.start_or_resume();
        }
        apply_controller_cursor_step(&mut self.input);
    }

    fn sample_run_state(&mut self, frame_dt: f32) {
        if !self.run_state.running() {
            self.pending_sample_seconds = 0.0;
            return;
        }
        self.pending_sample_seconds += frame_dt.max(0.0);
        if self.frame.saturating_sub(self.run_state.last_sample_frame) < 15 {
            return;
        }
        let pixels_result = {
            let Some(gpu) = self.gpu.as_ref() else {
                return;
            };
            gpu.readback_pixels()
        };
        match pixels_result {
            Ok(pixels) => {
                self.run_state.last_sample_frame = self.frame;
                let sampled_seconds = self.pending_sample_seconds;
                self.pending_sample_seconds = 0.0;
                self.run_state.update_from_pixels(
                    &self.trial,
                    &pixels,
                    self.args.render_width,
                    self.args.render_height,
                    sampled_seconds,
                );
            }
            Err(error) => eprintln!("trial readback error: {error}"),
        }
    }

    fn render(&mut self, event_loop: &ActiveEventLoop) {
        let frame_started = Instant::now();
        self.poll_controller();
        if self.exit_requested {
            event_loop.exit();
            return;
        }
        let Some(surface) = self.surface.as_ref() else {
            return;
        };
        let Some(gpu) = self.gpu.as_ref() else {
            return;
        };
        let texture = match surface.get_current_texture() {
            wgpu::CurrentSurfaceTexture::Success(texture)
            | wgpu::CurrentSurfaceTexture::Suboptimal(texture) => texture,
            wgpu::CurrentSurfaceTexture::Timeout | wgpu::CurrentSurfaceTexture::Occluded => return,
            wgpu::CurrentSurfaceTexture::Outdated | wgpu::CurrentSurfaceTexture::Lost => {
                if let (Some(config), Some(gpu)) = (self.config.as_ref(), self.gpu.as_ref()) {
                    surface.configure(&gpu.device, config);
                }
                return;
            }
            wgpu::CurrentSurfaceTexture::Validation => {
                eprintln!("surface validation error");
                self.fatal_error = Some("surface validation error".to_owned());
                event_loop.exit();
                return;
            }
        };
        gpu.update_overlay_text(&self.run_state, &self.trial);
        self.last_rendered_state = self.run_state.clone();
        let params = self.params();
        if let Err(error) = gpu.render_to_surface(&texture, params) {
            eprintln!("render error: {error}");
            self.fatal_error = Some(format!("render error: {error}"));
            event_loop.exit();
            return;
        }
        let recorded_rgba = if self.video_recorder.is_some() {
            match gpu.readback_presented_rgba(params) {
                Ok(rgba) => Some(rgba),
                Err(error) => {
                    eprintln!("native window recording readback error: {error}");
                    self.fatal_error =
                        Some(format!("native window recording readback error: {error}"));
                    event_loop.exit();
                    return;
                }
            }
        } else {
            None
        };
        texture.present();
        if let (Some(recorder), Some(rgba)) =
            (self.video_recorder.as_mut(), recorded_rgba.as_deref())
        {
            if let Err(error) = recorder.write_rgba_frame(rgba) {
                eprintln!("native window recording error: {error}");
                self.fatal_error = Some(format!("native window recording error: {error}"));
                event_loop.exit();
                return;
            }
            self.video_frames = self.video_frames.saturating_add(1);
            if !self.video_has_nonblank_frame {
                self.video_has_nonblank_frame = rgba
                    .chunks_exact(4)
                    .any(|pixel| pixel[0] != 0 || pixel[1] != 0 || pixel[2] != 0);
            }
        }
        let frame_ms = frame_started.elapsed().as_secs_f64() * 1000.0;
        let sample_seconds = if self.video_recorder.is_some() {
            1.0 / self.args.video_fps as f32
        } else {
            (frame_ms / 1000.0).max(1.0 / f64::from(SIMULATION_HZ)) as f32
        };
        self.sample_run_state(sample_seconds);
        self.frame_times_ms.push(frame_ms);
        self.frame = self.frame.saturating_add(1);
        if let Some(max_frames) = self.args.max_window_frames
            && self.frame >= max_frames
        {
            if let Err(error) = self.finish_timing_report() {
                eprintln!("timing report error: {error}");
                self.fatal_error = Some(format!("timing report error: {error}"));
            }
            event_loop.exit();
        }
    }

    fn finish_timing_report(&self) -> Result<(), Box<dyn std::error::Error>> {
        let seconds = self.started.elapsed().as_secs_f64().max(0.000_001);
        let frames = self.frame_times_ms.len().max(1);
        let avg_frame_ms = self.frame_times_ms.iter().sum::<f64>() / frames as f64;
        let worst_frame_ms = self.frame_times_ms.iter().copied().fold(0.0_f64, f64::max);
        let avg_fps = f64::from(self.frame) / seconds;
        println!(
            "wgpu_window_timing frames={} avg_fps={avg_fps:.2} avg_frame_ms={avg_frame_ms:.2} worst_frame_ms={worst_frame_ms:.2}",
            self.frame
        );
        println!(
            "trial_runtime_state status={} progress={:.3} active_zones={} rival_zones={} elapsed_seconds={:.2}",
            self.run_state.status.code(),
            self.run_state.progress,
            self.run_state.player_controlled_zones,
            self.run_state.rival_controlled_zones,
            self.run_state.elapsed_seconds
        );
        if let Some(path) = self.args.timing_report_path.as_ref() {
            write_timing_report(
                path,
                &self.args,
                &self.trial,
                &self.runtime_config,
                self.frame,
                seconds,
                avg_fps,
                avg_frame_ms,
                worst_frame_ms,
                Some(&self.run_state),
            )?;
            println!("wgpu_timing_report output={}", path.display());
        }
        Ok(())
    }

    fn finish_video_recording(&mut self) -> Result<(), Box<dyn std::error::Error>> {
        let Some(mut recorder) = self.video_recorder.take() else {
            if let Some(error) = self.fatal_error.take() {
                return Err(error.into());
            }
            return Ok(());
        };
        if let Some(error) = self.fatal_error.take() {
            drop(recorder);
            return Err(error.into());
        }
        if let Some(requested_frames) = self.args.requested_video_frames
            && self.video_frames != requested_frames
        {
            drop(recorder);
            return Err(format!(
                "window recording ended with {} frames; requested {requested_frames}",
                self.video_frames
            )
            .into());
        }
        if !self.video_has_nonblank_frame {
            drop(recorder);
            return Err("window recording did not capture a nonblank frame".into());
        }
        let encoded_frames = recorder.finish_encoding()?;
        if encoded_frames != self.video_frames {
            return Err(format!(
                "window recorder encoded {encoded_frames} frames; tracked {}",
                self.video_frames
            )
            .into());
        }
        let video_path = self
            .args
            .video_out_path
            .as_deref()
            .ok_or("window recording is missing its output path")?;
        let report_path = self
            .args
            .video_report_path
            .clone()
            .unwrap_or_else(|| video_path.with_extension("json"));
        let report_artifact = StagedArtifact::new(&report_path, "report")?;
        let encode_seconds = self
            .video_started
            .map(|started| started.elapsed().as_secs_f64())
            .unwrap_or(0.0);
        let particle_count = self
            .gpu
            .as_ref()
            .map(|gpu| gpu.particle_count)
            .unwrap_or_else(|| {
                particle_count_for_resolution(self.args.render_width, self.args.render_height)
            });
        write_video_report(
            report_artifact.temporary_path(),
            &self.args,
            &self.trial,
            &self.runtime_config,
            &self.last_rendered_state,
            encoded_frames,
            encode_seconds,
            particle_count,
            self.frame,
            None,
            "window-frame-capture",
            false,
            recorder.staged_output_bytes()?,
        )?;
        publish_staged_artifacts(&[
            (recorder.staged_output_path(), video_path),
            (
                report_artifact.temporary_path(),
                report_artifact.output_path(),
            ),
        ])?;
        recorder.mark_published()?;
        println!(
            "native_window_recording_result output={} report={} width={} height={} fps={} frames={} duration_seconds={:.3}",
            video_path.display(),
            report_path.display(),
            self.args.render_width,
            self.args.render_height,
            self.args.video_fps,
            encoded_frames,
            f64::from(encoded_frames) / f64::from(self.args.video_fps),
        );
        Ok(())
    }
}

impl ApplicationHandler for WindowApp {
    fn resumed(&mut self, event_loop: &ActiveEventLoop) {
        if let Err(error) = self.init(event_loop) {
            eprintln!("window init error: {error}");
            self.fatal_error = Some(format!("window init error: {error}"));
            event_loop.exit();
        }
    }

    fn window_event(
        &mut self,
        event_loop: &ActiveEventLoop,
        _window_id: WindowId,
        event: WindowEvent,
    ) {
        match event {
            WindowEvent::CloseRequested => event_loop.exit(),
            WindowEvent::Resized(size) => {
                if size.width > 0
                    && size.height > 0
                    && let (Some(surface), Some(config), Some(gpu)) = (
                        self.surface.as_ref(),
                        self.config.as_mut(),
                        self.gpu.as_ref(),
                    )
                {
                    config.width = size.width;
                    config.height = size.height;
                    surface.configure(&gpu.device, config);
                }
            }
            WindowEvent::KeyboardInput {
                event:
                    KeyEvent {
                        logical_key,
                        state: ElementState::Pressed,
                        ..
                    },
                ..
            } => match logical_key.as_ref() {
                Key::Named(NamedKey::Escape) => event_loop.exit(),
                Key::Named(NamedKey::Space) => {
                    if self.run_state.status == RunStatus::Briefing {
                        self.run_state.start(&self.trial);
                    } else if matches!(self.run_state.status, RunStatus::Won | RunStatus::Failed) {
                        self.advance_or_reset_trial();
                    } else {
                        self.input.paused = !self.input.paused;
                    }
                }
                Key::Named(NamedKey::Enter) => {
                    if self.run_state.status == RunStatus::Briefing {
                        self.run_state.start(&self.trial);
                    } else if matches!(self.run_state.status, RunStatus::Won | RunStatus::Failed) {
                        self.advance_or_reset_trial();
                    } else {
                        self.input.applying = true;
                    }
                }
                Key::Named(NamedKey::ArrowLeft) => {
                    self.input.cursor_x = (self.input.cursor_x - 0.025).clamp(0.0, 1.0);
                }
                Key::Named(NamedKey::ArrowRight) => {
                    self.input.cursor_x = (self.input.cursor_x + 0.025).clamp(0.0, 1.0);
                }
                Key::Named(NamedKey::ArrowUp) => {
                    self.input.cursor_y = (self.input.cursor_y - 0.025).clamp(0.0, 1.0);
                }
                Key::Named(NamedKey::ArrowDown) => {
                    self.input.cursor_y = (self.input.cursor_y + 0.025).clamp(0.0, 1.0);
                }
                _ => {}
            },
            WindowEvent::KeyboardInput {
                event:
                    KeyEvent {
                        logical_key: Key::Named(NamedKey::Enter),
                        state: ElementState::Released,
                        ..
                    },
                ..
            } => self.input.applying = false,
            WindowEvent::RedrawRequested => self.render(event_loop),
            _ => {}
        }
    }

    fn about_to_wait(&mut self, event_loop: &ActiveEventLoop) {
        event_loop.set_control_flow(ControlFlow::Poll);
        if let Some(window) = self.window.as_ref() {
            window.request_redraw();
        }
    }
}

fn main() {
    if let Err(error) = run() {
        eprintln!("error: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args = parse_args()?;
    if let Some(path) = args.dump_input_contract_path.as_ref() {
        write_input_contract(path)?;
        println!("input_contract_json={}", path.display());
        return Ok(());
    }
    let runtime_config = load_runtime_config(args.config_path.as_deref())?;
    if let Some(path) = args.dump_config_contract_path.as_ref() {
        write_config_contract(path, &runtime_config)?;
        println!("config_contract_json={}", path.display());
        return Ok(());
    }
    let trials = load_trial_sequence(&args.trial_path)?;
    let trial_index = selected_trial_index(&trials, args.trial_id.as_deref())?;
    let trial = trials[trial_index].clone();
    if let Some(path) = args.dump_input_smoke_path.as_ref() {
        write_input_smoke_report(path, &trials, trial_index, &runtime_config)?;
        println!("input_smoke_json={}", path.display());
        return Ok(());
    }
    println!(
        "trial_contract_result id={} title=\"{}\" objective=\"{}\" zones={} first_zone=({:.3},{:.3},r={:.3})",
        trial.trial_id,
        trial.title,
        trial.objective,
        trial.zone_count,
        trial.zones[0].x,
        trial.zones[0].y,
        trial.zones[0].radius
    );
    println!(
        "config_contract_result source={} rule_seed={:.3} sensor_distance={:.3} sensor_angle={:.3} sensor_gain={:.3} drag={:.3} global_force_mult={:.3} trail_persistence={:.3} hazard_rate={:.4} boundary_conditions={} initial_conditions={} num_cohorts={} disable_symmetry={} absolute_orientation={} orientation_mix={:.3} hue_sensitivity={:.3} color_by_cohort={} parameter_sweeps_enabled={} ink_weight={:.3} watercolor_mode={} emboss_mode={} emboss_intensity={:.3} emboss_smoothness={:.3}",
        runtime_config
            .source
            .as_ref()
            .map(|path| path.display().to_string())
            .unwrap_or_else(|| "defaults".to_owned()),
        runtime_config.rule_seed_value,
        runtime_config.sensor_distance,
        runtime_config.sensor_angle,
        runtime_config.sensor_gain,
        runtime_config.drag,
        runtime_config.global_force_mult,
        runtime_config.trail_persistence,
        runtime_config.hazard_rate,
        runtime_config.boundary_conditions,
        runtime_config.initial_conditions,
        runtime_config.num_cohorts,
        runtime_config.disable_symmetry,
        runtime_config.absolute_orientation,
        runtime_config.orientation_mix,
        runtime_config.hue_sensitivity,
        runtime_config.color_by_cohort,
        runtime_config.parameter_sweeps_enabled,
        runtime_config.ink_weight,
        runtime_config.watercolor_mode,
        runtime_config.emboss_mode,
        runtime_config.emboss_intensity,
        runtime_config.emboss_smoothness
    );
    println!(
        "rule_contract_result saved_rule={} coeff_count={}",
        runtime_config.has_saved_rule, RULE_FLOAT_COUNT
    );
    if args.window {
        let event_loop = EventLoop::new()?;
        let mut app = WindowApp::new(args, trials, trial_index, runtime_config);
        event_loop.run_app(&mut app)?;
        app.finish_video_recording()?;
        Ok(())
    } else {
        pollster::block_on(run_headless(args, trial, runtime_config))
    }
}

async fn run_headless(
    args: Args,
    trial: TrialRuntime,
    runtime_config: RuntimeConfig,
) -> Result<(), Box<dyn std::error::Error>> {
    let instance = wgpu::Instance::new(wgpu::InstanceDescriptor::new_without_display_handle());
    let gpu = GpuCore::new(
        &instance,
        None,
        None,
        args.render_width,
        args.render_height,
        &runtime_config,
        &trial,
    )
    .await?;
    let mut run_state = TrialRunState::new(&trial);
    run_state.start(&trial);
    let input = InputState {
        cursor_x: trial.zones[0].x,
        cursor_y: trial.zones[0].y,
        applying: true,
        paused: false,
        right_x: 0.0,
        right_y: 0.0,
    };
    let mut recorder = if let Some(output_path) = args.video_out_path.as_deref() {
        Some(FfmpegVideoRecorder::start(
            args.ffmpeg_path.as_deref(),
            output_path,
            args.render_width,
            args.render_height,
            args.video_fps,
            args.video_crf,
            &args.video_preset,
        )?)
    } else {
        None
    };
    let output_fps = if recorder.is_some() {
        args.video_fps
    } else {
        SIMULATION_HZ
    };
    let mut simulation_ticks = 0u32;
    let mut sampled_through_tick = 0u32;
    let mut last_presented_rgba = None;
    let mut last_params = None;
    let mut last_rendered_state = run_state.clone();
    let started = Instant::now();
    for output_frame in 0..args.frame_count {
        let target_ticks = simulation_ticks_for_output_frames(output_frame + 1, output_fps)?;
        while simulation_ticks < target_ticks {
            gpu.update_overlay_text(&run_state, &trial);
            last_rendered_state = run_state.clone();
            let params = params_for_frame(
                simulation_ticks,
                args.render_width,
                args.render_height,
                &trial,
                &input,
                &run_state,
                &runtime_config,
            );
            let mut encoder = gpu
                .device
                .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                    label: Some("spike-frame-encoder"),
                });
            gpu.encode_compute(&mut encoder, params);
            gpu.queue.submit(Some(encoder.finish()));
            last_params = Some(params);
            simulation_ticks = simulation_ticks.saturating_add(1);
            if simulation_ticks.is_multiple_of(15) {
                let pixels = gpu.readback_pixels()?;
                let sampled_ticks = simulation_ticks.saturating_sub(sampled_through_tick);
                run_state.update_from_pixels(
                    &trial,
                    &pixels,
                    args.render_width,
                    args.render_height,
                    sampled_ticks as f32 / SIMULATION_HZ as f32,
                );
                sampled_through_tick = simulation_ticks;
            }
        }
        if let Some(recorder) = recorder.as_mut() {
            let params =
                last_params.ok_or("native video export did not render a simulation tick")?;
            let rgba = gpu.readback_presented_rgba(params)?;
            recorder.write_rgba_frame(&rgba)?;
            last_presented_rgba = Some(rgba);
        }
    }
    if sampled_through_tick < simulation_ticks {
        let pixels = gpu.readback_pixels()?;
        let sampled_ticks = simulation_ticks.saturating_sub(sampled_through_tick);
        run_state.update_from_pixels(
            &trial,
            &pixels,
            args.render_width,
            args.render_height,
            sampled_ticks as f32 / SIMULATION_HZ as f32,
        );
    }
    let final_params = last_params.ok_or("headless render did not produce a frame")?;
    let mut poster_artifact = None;
    let nonblank_pixels = if let Some(rgba) = last_presented_rgba.as_deref() {
        let nonblank = rgba
            .chunks_exact(4)
            .filter(|pixel| pixel[0] != 0 || pixel[1] != 0 || pixel[2] != 0)
            .count();
        if nonblank == 0 {
            return Err("native video export produced a blank frame".into());
        }
        if let Some(out_path) = args.out_path.as_deref() {
            if recorder.is_some() {
                let artifact = StagedArtifact::new(out_path, "poster")?;
                write_ppm_rgba(
                    artifact.temporary_path(),
                    args.render_width,
                    args.render_height,
                    rgba,
                )?;
                poster_artifact = Some(artifact);
            } else {
                write_ppm_rgba(out_path, args.render_width, args.render_height, rgba)?;
            }
        }
        nonblank
    } else {
        let out_path = args
            .out_path
            .as_deref()
            .ok_or("headless frame capture requires --out")?;
        gpu.readback_nonblank(out_path, final_params)?
    };

    let mut video_result = None;
    if let Some(recorder) = recorder.as_mut() {
        let encoded_frames = recorder.finish_encoding()?;
        if encoded_frames != args.frame_count {
            return Err(format!(
                "FFmpeg encoded {encoded_frames} frames; expected {}",
                args.frame_count
            )
            .into());
        }
        let video_path = args
            .video_out_path
            .clone()
            .ok_or("video recorder is missing its output path")?;
        let report_path = args
            .video_report_path
            .clone()
            .unwrap_or_else(|| video_path.with_extension("json"));
        let report_artifact = StagedArtifact::new(&report_path, "report")?;
        let encode_seconds = started.elapsed().as_secs_f64().max(0.000_001);
        write_video_report(
            report_artifact.temporary_path(),
            &args,
            &trial,
            &runtime_config,
            &last_rendered_state,
            encoded_frames,
            encode_seconds,
            gpu.particle_count,
            simulation_ticks,
            args.out_path.as_deref(),
            "offline-fixed-step",
            true,
            recorder.staged_output_bytes()?,
        )?;
        let mut staged_artifacts = vec![(recorder.staged_output_path(), video_path.as_path())];
        if let Some(artifact) = poster_artifact.as_ref() {
            staged_artifacts.push((artifact.temporary_path(), artifact.output_path()));
        }
        staged_artifacts.push((
            report_artifact.temporary_path(),
            report_artifact.output_path(),
        ));
        publish_staged_artifacts(&staged_artifacts)?;
        recorder.mark_published()?;
        video_result = Some((video_path, report_path, encoded_frames));
    }

    let elapsed = started.elapsed();
    let seconds = elapsed.as_secs_f64().max(0.000_001);
    let avg_fps = f64::from(args.frame_count) / seconds;
    let avg_frame_ms = seconds * 1000.0 / f64::from(args.frame_count);
    println!(
        "wgpu_spike_result trials={} frames={} width={} height={} particles={} avg_fps={avg_fps:.2} avg_frame_ms={avg_frame_ms:.2} nonblank_pixels={} output={}",
        trial.trial_count,
        args.frame_count,
        args.render_width,
        args.render_height,
        gpu.particle_count,
        nonblank_pixels,
        args.out_path
            .as_ref()
            .map(|path| path.display().to_string())
            .unwrap_or_else(|| "none".to_owned())
    );
    if let Some((video_path, report_path, encoded_frames)) = video_result {
        println!(
            "native_video_export_result output={} report={} width={} height={} fps={} frames={} duration_seconds={:.3} codec=h264 pixel_format=yuv420p crf={} preset={}",
            video_path.display(),
            report_path.display(),
            args.render_width,
            args.render_height,
            args.video_fps,
            encoded_frames,
            f64::from(encoded_frames) / f64::from(args.video_fps),
            args.video_crf,
            args.video_preset,
        );
    }
    println!(
        "trial_runtime_state status={} progress={:.3} active_zones={} rival_zones={} elapsed_seconds={:.2}",
        run_state.status.code(),
        run_state.progress,
        run_state.player_controlled_zones,
        run_state.rival_controlled_zones,
        run_state.elapsed_seconds
    );
    Ok(())
}

fn validate_render_dimensions(width: u32, height: u32) -> Result<(), Box<dyn std::error::Error>> {
    if width == 0 || height == 0 {
        return Err("render width and height must be greater than zero".into());
    }
    if width > MAX_RENDER_AXIS || height > MAX_RENDER_AXIS {
        return Err(format!(
            "render width and height must each be at most {MAX_RENDER_AXIS} pixels"
        )
        .into());
    }
    let pixels = u64::from(width) * u64::from(height);
    if pixels > MAX_RENDER_PIXELS {
        return Err(format!(
            "render size {width}x{height} exceeds the native export limit of {MAX_RENDER_PIXELS} pixels"
        )
        .into());
    }
    Ok(())
}

fn aspect_fit_viewport(
    source_width: u32,
    source_height: u32,
    target_width: u32,
    target_height: u32,
) -> (u32, u32, u32, u32) {
    let source_width = source_width.max(1);
    let source_height = source_height.max(1);
    let target_width = target_width.max(1);
    let target_height = target_height.max(1);
    let source_cross = u64::from(source_width) * u64::from(target_height);
    let target_cross = u64::from(target_width) * u64::from(source_height);
    let (width, height) = if source_cross <= target_cross {
        let width = u32::try_from(
            (u64::from(target_height) * u64::from(source_width) + u64::from(source_height) / 2)
                / u64::from(source_height),
        )
        .unwrap_or(target_width)
        .clamp(1, target_width);
        (width, target_height)
    } else {
        let height = u32::try_from(
            (u64::from(target_width) * u64::from(source_height) + u64::from(source_width) / 2)
                / u64::from(source_width),
        )
        .unwrap_or(target_height)
        .clamp(1, target_height);
        (target_width, height)
    };
    (
        (target_width - width) / 2,
        (target_height - height) / 2,
        width,
        height,
    )
}

fn simulation_ticks_for_output_frames(
    output_frames: u32,
    output_fps: u32,
) -> Result<u32, Box<dyn std::error::Error>> {
    if output_fps == 0 {
        return Err("output FPS must be greater than zero".into());
    }
    Ok(u32::try_from(
        (u64::from(output_frames) * u64::from(SIMULATION_HZ)).div_ceil(u64::from(output_fps)),
    )?)
}

fn create_present_pipeline(
    device: &wgpu::Device,
    layout: &wgpu::PipelineLayout,
    shader: &wgpu::ShaderModule,
    format: wgpu::TextureFormat,
    label: &str,
) -> wgpu::RenderPipeline {
    device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
        label: Some(label),
        layout: Some(layout),
        vertex: wgpu::VertexState {
            module: shader,
            entry_point: Some("vs_main"),
            buffers: &[],
            compilation_options: wgpu::PipelineCompilationOptions::default(),
        },
        fragment: Some(wgpu::FragmentState {
            module: shader,
            entry_point: Some("fs_main"),
            targets: &[Some(wgpu::ColorTargetState {
                format,
                blend: Some(wgpu::BlendState::REPLACE),
                write_mask: wgpu::ColorWrites::ALL,
            })],
            compilation_options: wgpu::PipelineCompilationOptions::default(),
        }),
        primitive: wgpu::PrimitiveState::default(),
        depth_stencil: None,
        multisample: wgpu::MultisampleState::default(),
        multiview_mask: None,
        cache: None,
    })
}

fn storage_entry(
    binding: u32,
    visibility: wgpu::ShaderStages,
    read_only: bool,
) -> wgpu::BindGroupLayoutEntry {
    wgpu::BindGroupLayoutEntry {
        binding,
        visibility,
        ty: wgpu::BindingType::Buffer {
            ty: wgpu::BufferBindingType::Storage { read_only },
            has_dynamic_offset: false,
            min_binding_size: None,
        },
        count: None,
    }
}

fn uniform_entry(binding: u32, visibility: wgpu::ShaderStages) -> wgpu::BindGroupLayoutEntry {
    wgpu::BindGroupLayoutEntry {
        binding,
        visibility,
        ty: wgpu::BindingType::Buffer {
            ty: wgpu::BufferBindingType::Uniform,
            has_dynamic_offset: false,
            min_binding_size: None,
        },
        count: None,
    }
}

fn parse_args() -> Result<Args, Box<dyn std::error::Error>> {
    let mut trial_path = PathBuf::from("artifacts/trial_definitions.json");
    let mut config_path = None;
    let mut frame_count_arg = None;
    let mut out_path_arg = None;
    let mut render_width_arg = None;
    let mut render_height_arg = None;
    let mut video_out_path = None;
    let mut video_report_path = None;
    let mut video_seconds = None;
    let mut video_fps = 60;
    let mut video_crf = 15;
    let mut video_preset = "slow".to_owned();
    let mut ffmpeg_path = None;
    let mut dump_config_contract_path = None;
    let mut dump_input_contract_path = None;
    let mut dump_input_smoke_path = None;
    let mut window = false;
    let mut max_window_frames = None;
    let mut timing_report_path = None;
    let mut deck_profile = false;
    let mut trial_id = None;
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--trial" => trial_path = PathBuf::from(args.next().ok_or("--trial needs a path")?),
            "--config" => {
                config_path = Some(PathBuf::from(args.next().ok_or("--config needs a path")?))
            }
            "--dump-config-contract" => {
                dump_config_contract_path = Some(PathBuf::from(
                    args.next().ok_or("--dump-config-contract needs a path")?,
                ));
            }
            "--dump-input-contract" => {
                dump_input_contract_path = Some(PathBuf::from(
                    args.next().ok_or("--dump-input-contract needs a path")?,
                ));
            }
            "--dump-input-smoke" => {
                dump_input_smoke_path = Some(PathBuf::from(
                    args.next().ok_or("--dump-input-smoke needs a path")?,
                ));
            }
            "--frames" => {
                frame_count_arg = Some(
                    args.next()
                        .ok_or("--frames needs a count")?
                        .parse()
                        .map_err(|_| "--frames must be an integer")?,
                );
            }
            "--out" => out_path_arg = Some(PathBuf::from(args.next().ok_or("--out needs a path")?)),
            "--render-width" => {
                render_width_arg = Some(
                    args.next()
                        .ok_or("--render-width needs a pixel count")?
                        .parse()
                        .map_err(|_| "--render-width must be an integer")?,
                );
            }
            "--render-height" => {
                render_height_arg = Some(
                    args.next()
                        .ok_or("--render-height needs a pixel count")?
                        .parse()
                        .map_err(|_| "--render-height must be an integer")?,
                );
            }
            "--video-out" => {
                video_out_path = Some(PathBuf::from(
                    args.next().ok_or("--video-out needs an MP4 path")?,
                ));
            }
            "--video-report" => {
                video_report_path = Some(PathBuf::from(
                    args.next().ok_or("--video-report needs a JSON path")?,
                ));
            }
            "--video-seconds" => {
                video_seconds = Some(
                    args.next()
                        .ok_or("--video-seconds needs a duration")?
                        .parse::<f64>()
                        .map_err(|_| "--video-seconds must be a number")?,
                );
            }
            "--video-fps" => {
                video_fps = args
                    .next()
                    .ok_or("--video-fps needs a frame rate")?
                    .parse()
                    .map_err(|_| "--video-fps must be an integer")?;
            }
            "--video-crf" => {
                video_crf = args
                    .next()
                    .ok_or("--video-crf needs a value")?
                    .parse()
                    .map_err(|_| "--video-crf must be an integer")?;
            }
            "--video-preset" => {
                video_preset = args.next().ok_or("--video-preset needs a name")?;
            }
            "--ffmpeg" => {
                ffmpeg_path = Some(PathBuf::from(
                    args.next().ok_or("--ffmpeg needs an executable path")?,
                ));
            }
            "--trial-id" => trial_id = Some(args.next().ok_or("--trial-id needs an id")?),
            "--window" => window = true,
            "--deck-profile" => {
                deck_profile = true;
                window = true;
                max_window_frames.get_or_insert(3600);
                timing_report_path
                    .get_or_insert_with(|| PathBuf::from("artifacts/wgpu_deck_timing.json"));
            }
            "--max-window-frames" => {
                max_window_frames = Some(
                    args.next()
                        .ok_or("--max-window-frames needs a count")?
                        .parse()
                        .map_err(|_| "--max-window-frames must be an integer")?,
                );
            }
            "--timing-report" => {
                timing_report_path = Some(PathBuf::from(
                    args.next().ok_or("--timing-report needs a path")?,
                ));
            }
            "--help" | "-h" => {
                println!(
                    "usage: fluoddity-wgpu-spike [--trial artifacts/trial_definitions.json] [--trial-id bloom] [--config physics_configs/Core/Bubbles.json] [--dump-config-contract artifacts/native-wgpu/config_contract.json] [--dump-input-contract artifacts/native-wgpu/input_contract.json] [--dump-input-smoke artifacts/native-wgpu/input_smoke.json] [--frames 120 | --video-seconds 10] [--out artifacts/wgpu_spike_frame.ppm] [--render-width 1280] [--render-height 800] [--video-out export.mp4] [--video-report export.json] [--video-fps 60] [--video-crf 15] [--video-preset slow] [--ffmpeg path/to/ffmpeg] [--window] [--max-window-frames 300] [--deck-profile] [--timing-report artifacts/wgpu_deck_timing.json]"
                );
                std::process::exit(0);
            }
            other => return Err(format!("unknown argument: {other}").into()),
        }
    }
    if frame_count_arg.is_some() && video_seconds.is_some() {
        return Err("--frames and --video-seconds are mutually exclusive".into());
    }
    if video_seconds.is_some() && video_out_path.is_none() {
        return Err("--video-seconds requires --video-out".into());
    }
    if video_report_path.is_some() && video_out_path.is_none() {
        return Err("--video-report requires --video-out".into());
    }
    let video_mode = video_out_path.is_some();
    let render_width = render_width_arg.unwrap_or(if video_mode {
        VIDEO_WIDTH
    } else {
        DEFAULT_WIDTH
    });
    let render_height = render_height_arg.unwrap_or(if video_mode {
        VIDEO_HEIGHT
    } else {
        DEFAULT_HEIGHT
    });
    validate_render_dimensions(render_width, render_height)?;
    if video_mode {
        validate_video_settings(
            render_width,
            render_height,
            video_fps,
            video_crf,
            &video_preset,
        )?;
        let output = video_out_path.as_ref().expect("video mode has output path");
        let is_mp4 = output
            .extension()
            .and_then(|extension| extension.to_str())
            .is_some_and(|extension| extension.eq_ignore_ascii_case("mp4"));
        if !is_mp4 {
            return Err("--video-out must use an .mp4 extension".into());
        }
        if window && video_fps != SIMULATION_HZ {
            return Err(format!(
                "window frame capture currently requires --video-fps {SIMULATION_HZ}; use offline export for other frame rates"
            )
            .into());
        }
    }
    let frame_count = if let Some(seconds) = video_seconds {
        if !seconds.is_finite() || seconds <= 0.0 {
            return Err("--video-seconds must be a finite number greater than zero".into());
        }
        let frames = (seconds * f64::from(video_fps)).round();
        if frames < 1.0 || frames > f64::from(u32::MAX) {
            return Err("--video-seconds produces an unsupported frame count".into());
        }
        frames as u32
    } else {
        frame_count_arg.unwrap_or(if video_mode { video_fps * 10 } else { 120 })
    };
    if frame_count == 0 {
        return Err("--frames must be greater than zero".into());
    }
    let requested_video_frames =
        if video_mode && (video_seconds.is_some() || frame_count_arg.is_some()) {
            Some(frame_count)
        } else {
            None
        };
    if window && let Some(requested_frames) = requested_video_frames {
        if let Some(max_frames) = max_window_frames
            && max_frames != requested_frames
        {
            return Err(
                "--max-window-frames must match the frame count requested by --frames or --video-seconds"
                    .into(),
            );
        }
        max_window_frames = Some(requested_frames);
    }
    if max_window_frames == Some(0) {
        return Err("--max-window-frames must be greater than zero".into());
    }
    let out_path = if video_mode {
        out_path_arg
    } else {
        Some(out_path_arg.unwrap_or_else(|| PathBuf::from("artifacts/wgpu_spike_frame.ppm")))
    };
    if window && video_mode && out_path.is_some() {
        return Err(
            "--out poster capture is only supported by offline video export; window frame capture does not write a poster"
                .into(),
        );
    }
    if video_mode {
        let video_path = video_out_path.as_ref().expect("video mode has output path");
        let report_path = video_report_path
            .as_ref()
            .cloned()
            .unwrap_or_else(|| video_path.with_extension("json"));
        let mut additional_outputs = Vec::new();
        if let Some(path) = timing_report_path.as_deref() {
            additional_outputs.push(("--timing-report", path));
        }
        if let Some(path) = dump_config_contract_path.as_deref() {
            additional_outputs.push(("--dump-config-contract", path));
        }
        if let Some(path) = dump_input_contract_path.as_deref() {
            additional_outputs.push(("--dump-input-contract", path));
        }
        if let Some(path) = dump_input_smoke_path.as_deref() {
            additional_outputs.push(("--dump-input-smoke", path));
        }
        validate_distinct_output_paths(
            video_path,
            out_path.as_deref(),
            &report_path,
            &additional_outputs,
        )?;
        if let Some(poster_path) = out_path.as_ref() {
            let poster_is_ppm = poster_path
                .extension()
                .and_then(|extension| extension.to_str())
                .is_some_and(|extension| extension.eq_ignore_ascii_case("ppm"));
            if !poster_is_ppm {
                return Err("--out must use a .ppm extension during video export".into());
            }
        }
        let report_is_json = report_path
            .extension()
            .and_then(|extension| extension.to_str())
            .is_some_and(|extension| extension.eq_ignore_ascii_case("json"));
        if !report_is_json {
            return Err("--video-report must use a .json extension".into());
        }
    }
    Ok(Args {
        trial_path,
        config_path,
        dump_config_contract_path,
        dump_input_contract_path,
        dump_input_smoke_path,
        frame_count,
        out_path,
        render_width,
        render_height,
        video_out_path,
        video_report_path,
        video_fps,
        video_crf,
        video_preset,
        ffmpeg_path,
        requested_video_frames,
        window,
        max_window_frames,
        timing_report_path,
        deck_profile,
        trial_id,
    })
}

fn lexical_absolute(path: &Path) -> Result<PathBuf, Box<dyn std::error::Error>> {
    let source = if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir()?.join(path)
    };
    let mut normalized = PathBuf::new();
    for component in source.components() {
        match component {
            std::path::Component::CurDir => {}
            std::path::Component::ParentDir => {
                normalized.pop();
            }
            other => normalized.push(other.as_os_str()),
        }
    }
    Ok(normalized)
}

fn validate_distinct_output_paths(
    video_path: &Path,
    poster_path: Option<&Path>,
    report_path: &Path,
    additional_paths: &[(&str, &Path)],
) -> Result<(), Box<dyn std::error::Error>> {
    let mut outputs = vec![
        ("--video-out", lexical_absolute(video_path)?),
        ("--video-report", lexical_absolute(report_path)?),
    ];
    if let Some(path) = poster_path {
        outputs.push(("--out", lexical_absolute(path)?));
    }
    for (label, path) in additional_paths {
        outputs.push((*label, lexical_absolute(path)?));
    }
    for left in 0..outputs.len() {
        for right in (left + 1)..outputs.len() {
            if outputs[left].1 == outputs[right].1 {
                return Err(format!(
                    "video export output paths must be distinct paths; {} collides with {}",
                    outputs[left].0, outputs[right].0
                )
                .into());
            }
        }
    }
    Ok(())
}

fn params_for_frame(
    frame: u32,
    width: u32,
    height: u32,
    trial: &TrialRuntime,
    input: &InputState,
    run_state: &TrialRunState,
    runtime_config: &RuntimeConfig,
) -> Params {
    let actively_running = run_state.status == RunStatus::Running && !input.paused;
    Params {
        width,
        height,
        frame,
        trial_count: trial.trial_count,
        cursor_x: input.cursor_x,
        cursor_y: input.cursor_y,
        applying: u32::from(input.applying && actively_running),
        paused: u32::from(!actively_running),
        objective_zone_count: trial.zone_count,
        zone0_x: trial.zones[0].x,
        zone0_y: trial.zones[0].y,
        zone0_radius: trial.zones[0].radius,
        zone1_x: trial.zones[1].x,
        zone1_y: trial.zones[1].y,
        zone1_radius: trial.zones[1].radius,
        _zone1_pad: 0.0,
        zone2_x: trial.zones[2].x,
        zone2_y: trial.zones[2].y,
        zone2_radius: trial.zones[2].radius,
        _zone2_pad: 0.0,
        hazard_center_x: trial.hazard_center_x,
        hazard_width: trial.hazard_width,
        hazard_strength: trial.hazard_strength,
        hazard_enabled: u32::from(trial.hazard_enabled),
        rival_x: trial.rival_x,
        rival_y: trial.rival_y,
        rival_radius: trial.rival_radius,
        rival_enabled: u32::from(trial.rival_enabled),
        rule_seed: runtime_config.rule_seed,
        boundary_conditions: runtime_config.boundary_conditions,
        initial_conditions: runtime_config.initial_conditions,
        num_cohorts: runtime_config.num_cohorts,
        sensor_distance: runtime_config.sensor_distance,
        sensor_angle: runtime_config.sensor_angle,
        sensor_gain: runtime_config.sensor_gain,
        mutation_scale: runtime_config.mutation_scale,
        drag: runtime_config.drag,
        strafe_power: runtime_config.strafe_power,
        axial_force: runtime_config.axial_force,
        lateral_force: runtime_config.lateral_force,
        global_force_mult: runtime_config.global_force_mult,
        trail_persistence: runtime_config.trail_persistence,
        trail_diffusion: runtime_config.trail_diffusion,
        hazard_rate: runtime_config.hazard_rate,
        orientation_mix: runtime_config.orientation_mix,
        absolute_orientation: runtime_config.absolute_orientation,
        disable_symmetry: u32::from(runtime_config.disable_symmetry),
        hue_sensitivity: runtime_config.hue_sensitivity,
        color_by_cohort: u32::from(runtime_config.color_by_cohort),
        watercolor_mode: u32::from(runtime_config.watercolor_mode),
        emboss_mode: runtime_config.emboss_mode,
        ink_weight: runtime_config.ink_weight,
        emboss_intensity: runtime_config.emboss_intensity,
        emboss_smoothness: runtime_config.emboss_smoothness,
        _appearance_pad0: 0.0,
        progress: run_state.progress,
        active_zone_mask: run_state.active_zone_mask,
        run_status: run_state.status.code(),
        _runtime_pad0: 0,
    }
}

fn apply_controller_cursor_step(input: &mut InputState) {
    input.cursor_x = (input.cursor_x + input.right_x * 0.012).clamp(0.0, 1.0);
    input.cursor_y = (input.cursor_y - input.right_y * 0.012).clamp(0.0, 1.0);
}

fn input_smoke_snapshot(
    label: &str,
    frame: u32,
    trial: &TrialRuntime,
    input: &InputState,
    run_state: &TrialRunState,
    runtime_config: &RuntimeConfig,
) -> serde_json::Value {
    let params = params_for_frame(
        frame,
        DEFAULT_WIDTH,
        DEFAULT_HEIGHT,
        trial,
        input,
        run_state,
        runtime_config,
    );
    let overlay_rows = run_state.overlay_rows(trial);
    let prompt_actions: Vec<_> = run_state
        .prompt_actions(trial)
        .iter()
        .map(|action| {
            serde_json::json!({
                "steam_action": action.steam_action,
                "fallback_label": action.fallback_label,
                "label": action.label,
            })
        })
        .collect();
    serde_json::json!({
        "label": label,
        "trial_id": trial.trial_id,
        "trial_index": trial.trial_index,
        "status": run_state.status.code(),
        "overlay": {
            "title": overlay_rows[0],
            "status": overlay_rows[1],
            "prompt": overlay_rows[2],
            "prompt_actions": prompt_actions,
        },
        "input": {
            "cursor_x": input.cursor_x,
            "cursor_y": input.cursor_y,
            "applying": input.applying,
            "paused": input.paused,
            "right_x": input.right_x,
            "right_y": input.right_y,
        },
        "params": {
            "applying": params.applying,
            "paused": params.paused,
            "cursor_x": params.cursor_x,
            "cursor_y": params.cursor_y,
            "run_status": params.run_status,
        },
    })
}

fn write_input_smoke_report(
    path: &Path,
    trials: &[TrialRuntime],
    selected_index: usize,
    runtime_config: &RuntimeConfig,
) -> Result<(), Box<dyn std::error::Error>> {
    if let Some(parent) = path.parent()
        && !parent.as_os_str().is_empty()
    {
        fs::create_dir_all(parent)?;
    }

    let mut trial_index = if trials.len() > 1 { 0 } else { selected_index };
    let mut trial = trials[trial_index].clone();
    let mut run_state = TrialRunState::new(&trial);
    let mut input = InputState::new(trial.zones[0].x, trial.zones[0].y);
    let mut snapshots = Vec::new();
    snapshots.push(input_smoke_snapshot(
        "briefing_initial",
        0,
        &trial,
        &input,
        &run_state,
        runtime_config,
    ));

    run_state.start(&trial);
    input.paused = false;
    snapshots.push(input_smoke_snapshot(
        "south_start",
        1,
        &trial,
        &input,
        &run_state,
        runtime_config,
    ));

    input.applying = true;
    snapshots.push(input_smoke_snapshot(
        "r2_apply_running",
        2,
        &trial,
        &input,
        &run_state,
        runtime_config,
    ));

    input.paused = true;
    snapshots.push(input_smoke_snapshot(
        "start_pause_suppresses_apply",
        3,
        &trial,
        &input,
        &run_state,
        runtime_config,
    ));

    input.paused = false;
    snapshots.push(input_smoke_snapshot(
        "south_resume",
        4,
        &trial,
        &input,
        &run_state,
        runtime_config,
    ));

    let before_cursor = (input.cursor_x, input.cursor_y);
    input.right_x = 1.0;
    input.right_y = -1.0;
    apply_controller_cursor_step(&mut input);
    let after_cursor = (input.cursor_x, input.cursor_y);
    snapshots.push(input_smoke_snapshot(
        "right_stick_cursor_step",
        5,
        &trial,
        &input,
        &run_state,
        runtime_config,
    ));

    run_state.win("Smoke result reached.".to_owned());
    snapshots.push(input_smoke_snapshot(
        "result_won",
        6,
        &trial,
        &input,
        &run_state,
        runtime_config,
    ));

    let result_trial_id = trial.trial_id.clone();
    if trial_index + 1 < trials.len() {
        trial_index += 1;
        trial = trials[trial_index].clone();
        run_state = TrialRunState::new(&trial);
        input = InputState::new(trial.zones[0].x, trial.zones[0].y);
    } else {
        run_state.reset_to_briefing(&trial);
        input.applying = false;
        input.paused = false;
    }
    snapshots.push(input_smoke_snapshot(
        "south_next_briefing",
        7,
        &trial,
        &input,
        &run_state,
        runtime_config,
    ));

    if trials.len() > 1 {
        trial_index = trials.len() - 1;
        trial = trials[trial_index].clone();
        run_state = TrialRunState::new(&trial);
        input = InputState::new(trial.zones[0].x, trial.zones[0].y);
        run_state.start(&trial);
        run_state.win("Smoke final result reached.".to_owned());
        snapshots.push(input_smoke_snapshot(
            "final_result_won",
            8,
            &trial,
            &input,
            &run_state,
            runtime_config,
        ));
        trial_index = 0;
        trial = trials[trial_index].clone();
        run_state = TrialRunState::new(&trial);
        input = InputState::new(trial.zones[0].x, trial.zones[0].y);
        snapshots.push(input_smoke_snapshot(
            "final_next_restarts_sequence",
            9,
            &trial,
            &input,
            &run_state,
            runtime_config,
        ));
    }

    let payload = serde_json::json!({
        "schema": "fluoddity.native_input_runtime_smoke.v1",
        "status": "pass",
        "runtime": "rust-wgpu",
        "requested_trial_id": trials[selected_index].trial_id,
        "trial_id": snapshots[0]["trial_id"],
        "next_trial_id": snapshots[7]["trial_id"],
        "restart_trial_id": snapshots.last().map(|snapshot| snapshot["trial_id"].clone()).unwrap_or(serde_json::Value::Null),
        "checks": {
            "briefing_starts_paused": snapshots[0]["params"]["paused"] == 1,
            "south_starts_running": snapshots[1]["params"]["paused"] == 0 && snapshots[1]["params"]["run_status"] == 1,
            "r2_applies_when_running": snapshots[2]["params"]["applying"] == 1,
            "pause_suppresses_apply": snapshots[3]["params"]["paused"] == 1 && snapshots[3]["params"]["applying"] == 0,
            "resume_restores_running": snapshots[4]["params"]["paused"] == 0,
            "right_stick_moves_cursor": after_cursor.0 > before_cursor.0 && after_cursor.1 > before_cursor.1,
            "result_state_reached": snapshots[6]["params"]["run_status"] == 2,
            "south_next_returns_to_briefing": snapshots[7]["params"]["run_status"] == 0 && snapshots[7]["params"]["paused"] == 1 && snapshots[7]["params"]["applying"] == 0,
            "south_next_advances_trial": snapshots[7]["trial_id"] != result_trial_id,
            "final_result_state_reached": snapshots.len() > 8 && snapshots[8]["params"]["run_status"] == 2,
            "final_next_restarts_sequence": snapshots.len() > 9 && snapshots[9]["trial_index"] == 0 && snapshots[9]["params"]["run_status"] == 0 && snapshots[9]["params"]["applying"] == 0,
            "result_overlay_names_next_assay": snapshots[6]["overlay"]["status"].as_str().map(|value| value.contains("Next assay unlocked")).unwrap_or(false) && snapshots[6]["overlay"]["prompt"].as_str().map(|value| value.contains("A NEXT ASSAY")).unwrap_or(false),
            "final_overlay_names_sequence_complete": snapshots.len() > 8 && snapshots[8]["overlay"]["status"].as_str().map(|value| value.contains("Sequence complete")).unwrap_or(false) && snapshots[8]["overlay"]["prompt"].as_str().map(|value| value.contains("A RESTART TRIAL 1")).unwrap_or(false),
            "result_overlay_uses_view_exit": snapshots[6]["overlay"]["prompt"].as_str().map(|value| value.contains("VIEW EXIT")).unwrap_or(false),
            "prompt_actions_are_structured": snapshots.iter().all(|snapshot| snapshot["overlay"]["prompt_actions"].as_array().map(|actions| !actions.is_empty() && actions.iter().all(|action| action["steam_action"].as_str().map(|value| !value.is_empty()).unwrap_or(false) && action["fallback_label"].as_str().map(|value| !value.is_empty()).unwrap_or(false))).unwrap_or(false)),
        },
        "cursor_delta": {
            "x": after_cursor.0 - before_cursor.0,
            "y": after_cursor.1 - before_cursor.1,
        },
        "snapshots": snapshots,
    });
    fs::write(path, serde_json::to_string_pretty(&payload)?)?;
    Ok(())
}

fn load_runtime_config(path: Option<&Path>) -> Result<RuntimeConfig, Box<dyn std::error::Error>> {
    let mut config = RuntimeConfig::default();
    let Some(path) = path else {
        return Ok(config);
    };
    let text = fs::read_to_string(path)
        .map_err(|error| format!("failed to read config {}: {error}", path.display()))?;
    let value: serde_json::Value = serde_json::from_str(&text)?;
    let physics = value
        .get("physics")
        .ok_or("physics config must contain a `physics` object")?;
    let settings = value.get("settings");
    let appearance = value.get("appearance");
    config.source = Some(path.to_path_buf());
    config.notes = value
        .get("notes")
        .and_then(|notes| notes.as_str())
        .unwrap_or("")
        .to_owned();
    config.rule_seed_value = settings
        .and_then(|settings| optional_number_field(settings, "rule_seed"))
        .or_else(|| optional_number_field(physics, "rule_seed"))
        .unwrap_or(0.42);
    config.rule_seed = seed_from_float(config.rule_seed_value);
    config.sensor_distance = optional_number_field(physics, "sensor_distance")
        .map(|value| (value * 0.018).clamp(0.006, 0.08))
        .unwrap_or(config.sensor_distance);
    config.sensor_angle =
        optional_number_field(physics, "sensor_angle").unwrap_or(config.sensor_angle);
    config.sensor_gain = optional_number_field(physics, "sensor_gain")
        .unwrap_or(config.sensor_gain)
        .clamp(0.05, 8.0);
    config.mutation_scale = optional_number_field(physics, "mutation_scale")
        .unwrap_or(config.mutation_scale)
        .clamp(0.0, 2.0);
    config.drag = optional_number_field(physics, "drag")
        .unwrap_or(config.drag)
        .clamp(0.0, 1.0);
    config.strafe_power = optional_number_field(physics, "strafe_power")
        .unwrap_or(config.strafe_power)
        .clamp(-2.0, 2.0);
    config.axial_force =
        optional_number_field(physics, "axial_force").unwrap_or(config.axial_force);
    config.lateral_force =
        optional_number_field(physics, "lateral_force").unwrap_or(config.lateral_force);
    config.global_force_mult = optional_number_field(physics, "global_force_mult")
        .unwrap_or(config.global_force_mult)
        .clamp(0.0, 4.0);
    config.trail_persistence = optional_number_field(physics, "trail_persistence")
        .unwrap_or(config.trail_persistence)
        .clamp(0.0, 0.999);
    config.trail_diffusion = optional_number_field(physics, "trail_diffusion")
        .unwrap_or(config.trail_diffusion)
        .clamp(0.0, 4.0);
    config.hazard_rate = optional_number_field(physics, "hazard_rate")
        .unwrap_or(config.hazard_rate)
        .clamp(0.0, 0.05);
    config.parameter_sweeps_enabled = optional_bool_field(&value, "parameter_sweeps_enabled")
        .unwrap_or(config.parameter_sweeps_enabled);
    if let Some(settings) = settings {
        config.boundary_conditions = optional_u32_field(settings, "boundary_conditions")
            .unwrap_or(config.boundary_conditions)
            .min(2);
        config.initial_conditions = optional_u32_field(settings, "initial_conditions")
            .unwrap_or(config.initial_conditions)
            .min(2);
        config.num_cohorts = optional_u32_field(settings, "num_cohorts")
            .unwrap_or(config.num_cohorts)
            .clamp(1, 144);
        config.disable_symmetry =
            optional_bool_field(settings, "disable_symmetry").unwrap_or(config.disable_symmetry);
        config.absolute_orientation = optional_u32_field(settings, "absolute_orientation")
            .unwrap_or(config.absolute_orientation)
            .min(2);
        config.orientation_mix = optional_number_field(settings, "orientation_mix")
            .unwrap_or(config.orientation_mix)
            .clamp(0.0, 1.0);
    }
    if let Some(appearance) = appearance {
        config.hue_sensitivity = optional_number_field(appearance, "hue_sensitivity")
            .unwrap_or(config.hue_sensitivity)
            .clamp(0.0, 4.0);
        config.color_by_cohort =
            optional_bool_field(appearance, "color_by_cohort").unwrap_or(config.color_by_cohort);
        config.ink_weight = optional_number_field(appearance, "ink_weight")
            .unwrap_or(config.ink_weight)
            .clamp(0.0, 8.0);
        config.watercolor_mode =
            optional_bool_field(appearance, "watercolor_mode").unwrap_or(config.watercolor_mode);
        config.emboss_mode = optional_u32_field(appearance, "emboss_mode")
            .unwrap_or(config.emboss_mode)
            .min(2);
        config.emboss_intensity = optional_number_field(appearance, "emboss_intensity")
            .unwrap_or(config.emboss_intensity)
            .clamp(0.0, 4.0);
        config.emboss_smoothness = optional_number_field(appearance, "emboss_smoothness")
            .unwrap_or(config.emboss_smoothness)
            .clamp(0.001, 4.0);
    }
    config.physics_settings = build_physics_settings(&config, &value);
    if let Some(rule_values) = value.get("rule").and_then(|rule| rule.as_array()) {
        if rule_values.len() == RULE_FLOAT_COUNT {
            for (index, rule_value) in rule_values.iter().enumerate() {
                config.rule_coefficients[index] = rule_value.as_f64().unwrap_or(0.0) as f32;
            }
            config.has_saved_rule = !rule_is_zero(&config.rule_coefficients);
        } else {
            return Err(format!(
                "physics config rule must contain {RULE_FLOAT_COUNT} floats, found {}",
                rule_values.len()
            )
            .into());
        }
    }
    Ok(config)
}

impl Default for RuntimeConfig {
    fn default() -> Self {
        let rule_seed_value = 0.42;
        Self {
            source: None,
            notes: String::new(),
            rule_seed: seed_from_float(rule_seed_value),
            rule_seed_value,
            sensor_distance: 0.018,
            sensor_angle: 0.45,
            sensor_gain: 1.0,
            mutation_scale: 0.137,
            drag: 0.504,
            strafe_power: 0.224,
            axial_force: 0.371,
            lateral_force: -0.707,
            global_force_mult: 0.399,
            trail_persistence: 0.938,
            trail_diffusion: 1.0,
            hazard_rate: 0.0,
            orientation_mix: 1.0,
            absolute_orientation: 0,
            disable_symmetry: false,
            hue_sensitivity: 0.5,
            color_by_cohort: true,
            ink_weight: 1.0,
            watercolor_mode: false,
            emboss_mode: 0,
            emboss_intensity: 0.5,
            emboss_smoothness: 0.1,
            parameter_sweeps_enabled: false,
            boundary_conditions: 0,
            initial_conditions: 0,
            num_cohorts: 64,
            physics_settings: default_physics_settings(),
            rule_coefficients: [0.0; RULE_FLOAT_COUNT],
            has_saved_rule: false,
        }
    }
}

struct SettingDef {
    field: &'static str,
    label: &'static str,
    default_min: f32,
    default_max: f32,
    native_scale: f32,
}

const SETTING_DEFS: [SettingDef; PHYSICS_SETTING_COUNT] = [
    SettingDef {
        field: "AXIAL_FORCE",
        label: "Axial Force",
        default_min: -1.0,
        default_max: 1.0,
        native_scale: 1.0,
    },
    SettingDef {
        field: "LATERAL_FORCE",
        label: "Lateral Force",
        default_min: -1.0,
        default_max: 1.0,
        native_scale: 1.0,
    },
    SettingDef {
        field: "SENSOR_GAIN",
        label: "Sensor Gain",
        default_min: 0.0,
        default_max: 10.0,
        native_scale: 1.0,
    },
    SettingDef {
        field: "MUTATION_SCALE",
        label: "Mutation Scale",
        default_min: 0.0,
        default_max: 1.0,
        native_scale: 1.0,
    },
    SettingDef {
        field: "DRAG",
        label: "Drag",
        default_min: -1.0,
        default_max: 1.0,
        native_scale: 1.0,
    },
    SettingDef {
        field: "STRAFE_POWER",
        label: "Strafe Power",
        default_min: 0.0,
        default_max: 0.5,
        native_scale: 1.0,
    },
    SettingDef {
        field: "SENSOR_ANGLE",
        label: "Sensor Angle",
        default_min: -1.0,
        default_max: 1.0,
        native_scale: 1.0,
    },
    SettingDef {
        field: "GLOBAL_FORCE_MULT",
        label: "Global Force Mult",
        default_min: 0.0,
        default_max: 2.0,
        native_scale: 1.0,
    },
    SettingDef {
        field: "SENSOR_DISTANCE",
        label: "Sensor Distance",
        default_min: 0.0,
        default_max: 3.0,
        native_scale: 0.018,
    },
    SettingDef {
        field: "TRAIL_PERSISTENCE",
        label: "Trail Persistence",
        default_min: 0.0,
        default_max: 1.0,
        native_scale: 1.0,
    },
    SettingDef {
        field: "TRAIL_DIFFUSION",
        label: "Trail Diffusion",
        default_min: 0.0,
        default_max: 1.0,
        native_scale: 1.0,
    },
    SettingDef {
        field: "HAZARD_RATE",
        label: "Hazard Rate",
        default_min: 0.0,
        default_max: 0.05,
        native_scale: 1.0,
    },
];

fn default_physics_settings() -> [NativeSetting; PHYSICS_SETTING_COUNT] {
    let mut settings = [NativeSetting::new(0.0, 0.0, 1.0); PHYSICS_SETTING_COUNT];
    let defaults = [
        0.371, -0.707, 1.0, 0.137, 0.504, 0.224, 0.45, 0.399, 0.018, 0.938, 1.0, 0.0,
    ];
    for (index, setting) in settings.iter_mut().enumerate() {
        let def = &SETTING_DEFS[index];
        *setting = NativeSetting::new(
            defaults[index],
            def.default_min * def.native_scale,
            def.default_max * def.native_scale,
        );
    }
    settings
}

fn build_physics_settings(
    config: &RuntimeConfig,
    root: &serde_json::Value,
) -> [NativeSetting; PHYSICS_SETTING_COUNT] {
    let mut settings = [NativeSetting::new(0.0, 0.0, 1.0); PHYSICS_SETTING_COUNT];
    let values = [
        config.axial_force,
        config.lateral_force,
        config.sensor_gain,
        config.mutation_scale,
        config.drag,
        config.strafe_power,
        config.sensor_angle,
        config.global_force_mult,
        config.sensor_distance,
        config.trail_persistence,
        config.trail_diffusion,
        config.hazard_rate,
    ];
    for (index, setting) in settings.iter_mut().enumerate() {
        let def = &SETTING_DEFS[index];
        let (min_value, max_value) = slider_range(
            root,
            def.label,
            def.default_min,
            def.default_max,
            def.native_scale,
        );
        *setting = NativeSetting::new(values[index], min_value, max_value);
        if config.parameter_sweeps_enabled {
            setting.x_sweep = sweep_value(root, "x", def.field);
            setting.y_sweep = sweep_value(root, "y", def.field);
            setting.cohort_sweep = sweep_value(root, "cohort", def.field);
        }
        setting.jitter = jitter_value(root, def.field);
    }
    settings
}

fn slider_range(
    root: &serde_json::Value,
    label: &str,
    default_min: f32,
    default_max: f32,
    scale: f32,
) -> (f32, f32) {
    let range = root
        .get("slider_ranges")
        .and_then(|ranges| ranges.get(label))
        .and_then(|range| range.as_array());
    if let Some(range) = range
        && range.len() >= 2
    {
        let min_value = range[0].as_f64().unwrap_or(default_min as f64) as f32 * scale;
        let max_value = range[1].as_f64().unwrap_or(default_max as f64) as f32 * scale;
        return (min_value, max_value);
    }
    (default_min * scale, default_max * scale)
}

fn sweep_value(root: &serde_json::Value, axis: &str, field: &str) -> f32 {
    root.get("sweeps")
        .and_then(|sweeps| sweeps.get(axis))
        .and_then(|axis_values| axis_values.get(field))
        .and_then(|value| value.as_f64())
        .unwrap_or(0.0) as f32
}

fn jitter_value(root: &serde_json::Value, field: &str) -> f32 {
    root.get("jitters")
        .and_then(|jitters| jitters.get(field))
        .and_then(|value| value.as_f64())
        .unwrap_or(0.0) as f32
}

fn rule_is_zero(rule: &[f32; RULE_FLOAT_COUNT]) -> bool {
    rule.iter().all(|value| value.abs() < 0.000_001)
}

fn load_trial_sequence(path: &Path) -> Result<Vec<TrialRuntime>, Box<dyn std::error::Error>> {
    let text = fs::read_to_string(path).map_err(|error| {
        format!(
            "failed to read {}: {error}; run `python scripts/export_trial_definitions.py` first",
            path.display()
        )
    })?;
    let value: serde_json::Value = serde_json::from_str(&text)?;
    let trials = value
        .get("trials")
        .and_then(|trials| trials.as_array())
        .ok_or("trial contract must contain a `trials` array")?;
    if trials.is_empty() {
        return Err("trial contract has no trials".into());
    }
    trials
        .iter()
        .enumerate()
        .map(|(index, trial)| trial_runtime_from_value(trial, index, trials.len()))
        .collect()
}

fn selected_trial_index(
    trials: &[TrialRuntime],
    requested_trial_id: Option<&str>,
) -> Result<usize, Box<dyn std::error::Error>> {
    if let Some(requested_trial_id) = requested_trial_id {
        trials
            .iter()
            .position(|trial| trial.trial_id == requested_trial_id)
            .ok_or_else(|| format!("trial id `{requested_trial_id}` not found in contract").into())
    } else {
        Ok(0)
    }
}

fn next_trial_index(current_index: usize, trial_count: usize) -> usize {
    if trial_count == 0 || current_index + 1 >= trial_count {
        0
    } else {
        current_index + 1
    }
}

#[cfg(test)]
fn load_trial_runtime(
    path: &Path,
    requested_trial_id: Option<&str>,
) -> Result<TrialRuntime, Box<dyn std::error::Error>> {
    let trials = load_trial_sequence(path)?;
    let trial_index = selected_trial_index(&trials, requested_trial_id)?;
    Ok(trials[trial_index].clone())
}

fn trial_runtime_from_value(
    selected: &serde_json::Value,
    trial_index: usize,
    trial_count: usize,
) -> Result<TrialRuntime, Box<dyn std::error::Error>> {
    let (zones, zone_count) = objective_zones(selected)?;
    let rival_center = point_field(selected, "rival_center").unwrap_or((0.82, 0.52));
    Ok(TrialRuntime {
        trial_index: trial_index as u32,
        trial_count: trial_count as u32,
        trial_id: string_field(selected, "trial_id")?,
        title: string_field(selected, "title")?,
        objective: string_field(selected, "objective")?,
        running_hint: string_field(selected, "running_hint")?,
        zones,
        zone_count,
        hold_seconds: number_field(selected, "hold_seconds")?,
        failure_seconds: number_field(selected, "failure_seconds")?,
        activity_threshold: number_field(selected, "activity_threshold")?,
        win_condition: win_condition_field(selected)?,
        hazard_enabled: bool_field(selected, "hazard_enabled")?,
        hazard_center_x: number_field(selected, "hazard_center_x")?,
        hazard_width: number_field(selected, "hazard_width")?,
        hazard_strength: number_field(selected, "hazard_strength")?,
        rival_enabled: bool_field(selected, "rival_enabled")?,
        rival_x: rival_center.0,
        rival_y: rival_center.1,
        rival_radius: number_field(selected, "rival_radius")?,
        rival_growth: number_field(selected, "rival_growth")?,
        rival_activity_threshold: number_field(selected, "rival_activity_threshold")?,
    })
}

fn win_condition_field(
    value: &serde_json::Value,
) -> Result<WinCondition, Box<dyn std::error::Error>> {
    match string_field(value, "win_condition")?.as_str() {
        "hold_all_zones" => Ok(WinCondition::HoldAllZones),
        "territory_at_timeout" => Ok(WinCondition::TerritoryAtTimeout),
        other => Err(format!("unsupported win_condition `{other}`").into()),
    }
}

fn objective_zones(
    trial: &serde_json::Value,
) -> Result<([ObjectiveZone; MAX_OBJECTIVE_ZONES], u32), Box<dyn std::error::Error>> {
    let zone_values = trial
        .get("zones")
        .and_then(|zones| zones.as_array())
        .ok_or("trial must contain a zones array")?;
    if zone_values.is_empty() {
        return Err("trial must contain at least one zone".into());
    }
    let mut zones = [ObjectiveZone::default(); MAX_OBJECTIVE_ZONES];
    let zone_count = zone_values.len().min(MAX_OBJECTIVE_ZONES);
    for (index, zone_value) in zone_values.iter().take(MAX_OBJECTIVE_ZONES).enumerate() {
        zones[index] = objective_zone(zone_value)?;
    }
    Ok((zones, zone_count as u32))
}

fn objective_zone(
    zone_value: &serde_json::Value,
) -> Result<ObjectiveZone, Box<dyn std::error::Error>> {
    let zone = zone_value.as_array().ok_or("zone must be an array")?;
    let center_value = zone.get(1).ok_or("zone must contain a center point")?;
    let center = point_value(center_value)?;
    let radius = zone
        .get(2)
        .and_then(|radius| radius.as_f64())
        .ok_or("zone must contain a numeric radius")? as f32;
    Ok(ObjectiveZone {
        x: center.0,
        y: center.1,
        radius,
    })
}

fn point_field(
    value: &serde_json::Value,
    field: &str,
) -> Result<(f32, f32), Box<dyn std::error::Error>> {
    point_value(
        value
            .get(field)
            .ok_or_else(|| format!("missing field `{field}`"))?,
    )
}

fn point_value(value: &serde_json::Value) -> Result<(f32, f32), Box<dyn std::error::Error>> {
    let point = value.as_array().ok_or("point must be an array")?;
    let x = point
        .first()
        .and_then(|x| x.as_f64())
        .ok_or("point must contain numeric x")? as f32;
    let y = point
        .get(1)
        .and_then(|y| y.as_f64())
        .ok_or("point must contain numeric y")? as f32;
    Ok((x, y))
}

fn string_field(
    value: &serde_json::Value,
    field: &str,
) -> Result<String, Box<dyn std::error::Error>> {
    value
        .get(field)
        .and_then(|field_value| field_value.as_str())
        .map(str::to_owned)
        .ok_or_else(|| format!("missing string field `{field}`").into())
}

fn number_field(value: &serde_json::Value, field: &str) -> Result<f32, Box<dyn std::error::Error>> {
    value
        .get(field)
        .and_then(|field_value| field_value.as_f64())
        .map(|number| number as f32)
        .ok_or_else(|| format!("missing number field `{field}`").into())
}

fn optional_number_field(value: &serde_json::Value, field: &str) -> Option<f32> {
    value
        .get(field)
        .and_then(|field_value| field_value.as_f64())
        .map(|number| number as f32)
}

fn optional_u32_field(value: &serde_json::Value, field: &str) -> Option<u32> {
    value
        .get(field)
        .and_then(|field_value| field_value.as_u64())
        .and_then(|number| u32::try_from(number).ok())
}

fn optional_bool_field(value: &serde_json::Value, field: &str) -> Option<bool> {
    value
        .get(field)
        .and_then(|field_value| field_value.as_bool())
}

fn bool_field(value: &serde_json::Value, field: &str) -> Result<bool, Box<dyn std::error::Error>> {
    value
        .get(field)
        .and_then(|field_value| field_value.as_bool())
        .ok_or_else(|| format!("missing bool field `{field}`").into())
}

fn particle_count_for_resolution(width: u32, height: u32) -> u32 {
    let default_pixels = u64::from(DEFAULT_WIDTH) * u64::from(DEFAULT_HEIGHT);
    let scaled = u64::from(BASE_PARTICLE_COUNT) * u64::from(width) * u64::from(height);
    u32::try_from((scaled + default_pixels / 2) / default_pixels)
        .unwrap_or(u32::MAX)
        .max(1)
}

fn initial_particles(
    runtime_config: &RuntimeConfig,
    particle_count: u32,
    render_width: u32,
) -> Vec<Particle> {
    let mut particles = Vec::with_capacity(particle_count as usize);
    let columns = u32::try_from(
        (128 * u64::from(render_width) + u64::from(DEFAULT_WIDTH) / 2) / u64::from(DEFAULT_WIDTH),
    )
    .unwrap_or(u32::MAX)
    .clamp(1, particle_count);
    let rows = particle_count.div_ceil(columns).max(1);
    let num_cohorts = runtime_config.num_cohorts.max(1);
    for index in 0..particle_count {
        let col = index % columns;
        let row = index / columns;
        let jitter_x = hash01(index, 17) * 0.006 - 0.003;
        let jitter_y = hash01(index, 43) * 0.006 - 0.003;
        let (x, y) = match runtime_config.initial_conditions {
            1 => (
                0.08 + hash01(index, 211) * 0.84,
                0.08 + hash01(index, 307) * 0.84,
            ),
            2 => {
                let angle = (index as f32 / particle_count as f32) * std::f32::consts::TAU;
                let radius = 0.23 + hash01(index, 401) * 0.08;
                (
                    0.5 + angle.cos() * radius + jitter_x,
                    0.5 + angle.sin() * radius + jitter_y,
                )
            }
            _ => (
                0.24 + (col as f32 / columns.saturating_sub(1).max(1) as f32) * 0.52 + jitter_x,
                0.24 + (row as f32 / rows.saturating_sub(1).max(1) as f32) * 0.52 + jitter_y,
            ),
        };
        let angle = hash01(index, 91) * std::f32::consts::TAU;
        particles.push(Particle {
            x: x.clamp(0.02, 0.98),
            y: y.clamp(0.02, 0.98),
            vx: angle.cos() * 0.0015,
            vy: angle.sin() * 0.0015,
            cohort: index % num_cohorts,
            rule_seed: 0x9e37_79b9u32 ^ index.wrapping_mul(0x85eb_ca6b),
            _pad0: 0,
            _pad1: 0,
        });
    }
    particles
}

fn hash01(index: u32, salt: u32) -> f32 {
    let mut value = index
        .wrapping_mul(747_796_405)
        .wrapping_add(2_891_336_453)
        .wrapping_add(salt.wrapping_mul(97_531));
    value = ((value >> ((value >> 28) + 4)) ^ value).wrapping_mul(277_803_737);
    value = (value >> 22) ^ value;
    value as f32 / u32::MAX as f32
}

fn seed_from_float(seed: f32) -> u32 {
    let bits = seed.to_bits();
    bits ^ bits.rotate_left(13) ^ 0x9e37_79b9
}

fn sample_active_zones(trial: &TrialRuntime, pixels: &[u32], width: u32, height: u32) -> u32 {
    let mut mask = 0u32;
    for index in 0..trial.zone_count as usize {
        let zone = trial.zones[index];
        if sampled_zone_activity(zone, pixels, width, height) >= trial.activity_threshold {
            mask |= 1u32 << index;
        }
    }
    mask
}

fn sampled_zone_activity(zone: ObjectiveZone, pixels: &[u32], width: u32, height: u32) -> f32 {
    let center_x = (zone.x * width as f32).round() as i32;
    let center_y = (zone.y * height as f32).round() as i32;
    let radius = (zone.radius * width.min(height) as f32).round().max(1.0) as i32;
    let mut total = 0.0f32;
    let mut count = 0u32;
    for y in (center_y - radius)..=(center_y + radius) {
        if y < 0 || y >= height as i32 {
            continue;
        }
        for x in (center_x - radius)..=(center_x + radius) {
            if x < 0 || x >= width as i32 {
                continue;
            }
            let dx = x - center_x;
            let dy = y - center_y;
            if dx * dx + dy * dy > radius * radius {
                continue;
            }
            let pixel = pixels[(y as u32 * width + x as u32) as usize];
            let r = (pixel & 0xff) as f32 / 255.0;
            let g = ((pixel >> 8) & 0xff) as f32 / 255.0;
            let b = ((pixel >> 16) & 0xff) as f32 / 255.0;
            total += (r * 0.20 + g * 0.45 + b * 0.35).max(0.0);
            count += 1;
        }
    }
    if count == 0 {
        0.0
    } else {
        total / count as f32
    }
}

fn rival_controlled_zones(trial: &TrialRuntime, elapsed_seconds: f32) -> u32 {
    if !trial.rival_enabled {
        return 0;
    }
    let rival_radius = trial.rival_radius + elapsed_seconds * trial.rival_growth;
    let mut controlled = 0;
    for index in 0..trial.zone_count as usize {
        let zone = trial.zones[index];
        let dx = zone.x - trial.rival_x;
        let dy = zone.y - trial.rival_y;
        let influence =
            (1.0 - ((dx * dx + dy * dy).sqrt() / rival_radius.max(0.0001))).clamp(0.0, 1.0);
        if influence >= trial.rival_activity_threshold {
            controlled += 1;
        }
    }
    controlled
}

fn overlay_text_buffer(state: &TrialRunState, trial: &TrialRuntime) -> [u32; OVERLAY_TEXT_COUNT] {
    let mut buffer = [b' ' as u32; OVERLAY_TEXT_COUNT];
    for (row, line) in state.overlay_rows(trial).iter().enumerate() {
        write_overlay_line(&mut buffer, row, line);
    }
    buffer
}

fn write_overlay_line(buffer: &mut [u32; OVERLAY_TEXT_COUNT], row: usize, text: &str) {
    let offset = row * OVERLAY_TEXT_COLUMNS;
    for (column, byte) in text
        .bytes()
        .filter_map(sanitize_overlay_byte)
        .take(OVERLAY_TEXT_COLUMNS)
        .enumerate()
    {
        buffer[offset + column] = u32::from(byte);
    }
}

fn sanitize_overlay_byte(byte: u8) -> Option<u8> {
    match byte {
        b'a'..=b'z' => Some(byte.to_ascii_uppercase()),
        b'A'..=b'Z' | b'0'..=b'9' | b' ' | b':' | b'-' | b'.' => Some(byte),
        b'_' | b'/' => Some(b'-'),
        b',' | b';' => Some(b' '),
        _ => None,
    }
}

fn write_ppm_rgba(
    path: &Path,
    width: u32,
    height: u32,
    rgba: &[u8],
) -> Result<(), Box<dyn std::error::Error>> {
    let expected_bytes = usize::try_from(u64::from(width) * u64::from(height) * 4)?;
    if rgba.len() != expected_bytes {
        return Err(format!(
            "RGBA capture contains {} bytes; expected {expected_bytes}",
            rgba.len()
        )
        .into());
    }
    if let Some(parent) = path.parent()
        && !parent.as_os_str().is_empty()
    {
        fs::create_dir_all(parent)?;
    }
    let mut bytes = format!("P6\n{width} {height}\n255\n").into_bytes();
    bytes.reserve(usize::try_from(u64::from(width) * u64::from(height) * 3)?);
    for pixel in rgba.chunks_exact(4) {
        bytes.extend_from_slice(&pixel[..3]);
    }
    fs::write(path, bytes)?;
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn write_video_report(
    path: &Path,
    args: &Args,
    trial: &TrialRuntime,
    runtime_config: &RuntimeConfig,
    run_state: &TrialRunState,
    frames: u32,
    encode_seconds: f64,
    particle_count: u32,
    simulation_ticks: u32,
    poster_path: Option<&Path>,
    timeline_mode: &str,
    deterministic_timeline: bool,
    output_bytes: u64,
) -> Result<(), Box<dyn std::error::Error>> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let output_path = args
        .video_out_path
        .as_ref()
        .ok_or("video report requires a video output path")?;
    let report = serde_json::json!({
        "schema": "fluoddity.native_video_export.v1",
        "status": "pass",
        "output": output_path.display().to_string(),
        "output_bytes": output_bytes,
        "poster_frame": poster_path.map(|path| path.display().to_string()),
        "render": {
            "width": args.render_width,
            "height": args.render_height,
            "pixel_count": u64::from(args.render_width) * u64::from(args.render_height),
            "particle_count": particle_count,
            "presentation_pass": "present.wgsl",
            "captures_final_presentation": true,
            "watercolor": runtime_config.watercolor_mode,
            "emboss_mode": runtime_config.emboss_mode,
        },
        "video": {
            "container": "mp4",
            "encoder": "libx264",
            "codec": "h264",
            "pixel_format": "yuv420p",
            "color_primaries": "bt709",
            "color_transfer": "bt709",
            "color_space": "bt709",
            "color_range": "tv",
            "fps": args.video_fps,
            "frames": frames,
            "duration_seconds": f64::from(frames) / f64::from(args.video_fps),
            "crf": args.video_crf,
            "preset": args.video_preset,
            "faststart": true,
        },
        "timeline": {
            "mode": timeline_mode,
            "deterministic_frame_rate": deterministic_timeline,
            "simulation_hz": SIMULATION_HZ,
            "simulation_ticks": simulation_ticks,
            "encode_elapsed_seconds": encode_seconds,
        },
        "trial": {
            "id": trial.trial_id,
            "title": trial.title,
            "trial_count": trial.trial_count,
            "status_code": run_state.status.code(),
            "progress": run_state.progress,
            "active_zones": run_state.player_controlled_zones,
            "rival_zones": run_state.rival_controlled_zones,
            "elapsed_seconds": run_state.elapsed_seconds,
        },
        "config": {
            "source": runtime_config
                .source
                .as_ref()
                .map(|path| path.display().to_string())
                .unwrap_or_else(|| "defaults".to_owned()),
            "notes": runtime_config.notes,
            "saved_rule": runtime_config.has_saved_rule,
        },
    });
    fs::write(path, serde_json::to_string_pretty(&report)?)?;
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn write_timing_report(
    path: &Path,
    args: &Args,
    trial: &TrialRuntime,
    runtime_config: &RuntimeConfig,
    frames: u32,
    seconds: f64,
    avg_fps: f64,
    avg_frame_ms: f64,
    worst_frame_ms: f64,
    run_state: Option<&TrialRunState>,
) -> Result<(), Box<dyn std::error::Error>> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let report = serde_json::json!({
        "profile": if args.deck_profile { "deck" } else { "window" },
        "width": args.render_width,
        "height": args.render_height,
        "frames": frames,
        "elapsed_seconds": seconds,
        "avg_fps": avg_fps,
        "avg_frame_ms": avg_frame_ms,
        "worst_frame_ms": worst_frame_ms,
        "trial_id": trial.trial_id,
        "trial_count": trial.trial_count,
        "config": runtime_config
            .source
            .as_ref()
            .map(|path| path.display().to_string())
            .unwrap_or_else(|| "defaults".to_owned()),
        "notes": runtime_config.notes,
        "saved_rule": runtime_config.has_saved_rule,
        "boundary_conditions": runtime_config.boundary_conditions,
        "initial_conditions": runtime_config.initial_conditions,
        "num_cohorts": runtime_config.num_cohorts,
        "hazard_rate": runtime_config.hazard_rate,
        "disable_symmetry": runtime_config.disable_symmetry,
        "absolute_orientation": runtime_config.absolute_orientation,
        "orientation_mix": runtime_config.orientation_mix,
        "hue_sensitivity": runtime_config.hue_sensitivity,
        "color_by_cohort": runtime_config.color_by_cohort,
        "ink_weight": runtime_config.ink_weight,
        "watercolor_mode": runtime_config.watercolor_mode,
        "emboss_mode": runtime_config.emboss_mode,
        "emboss_intensity": runtime_config.emboss_intensity,
        "emboss_smoothness": runtime_config.emboss_smoothness,
        "parameter_sweeps_enabled": runtime_config.parameter_sweeps_enabled,
        "trial_runtime": run_state.map(|state| serde_json::json!({
            "status_code": state.status.code(),
            "progress": state.progress,
            "active_zones": state.player_controlled_zones,
            "rival_zones": state.rival_controlled_zones,
            "elapsed_seconds": state.elapsed_seconds,
            "objective_status": state.objective_status,
        })),
    });
    fs::write(path, serde_json::to_string_pretty(&report)?)?;
    Ok(())
}

fn write_config_contract(
    path: &Path,
    runtime_config: &RuntimeConfig,
) -> Result<(), Box<dyn std::error::Error>> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let settings: Vec<_> = runtime_config
        .physics_settings
        .iter()
        .enumerate()
        .map(|(index, setting)| {
            let def = &SETTING_DEFS[index];
            serde_json::json!({
                "field": def.field,
                "label": def.label,
                "slider_value": setting.slider_value,
                "min_value": setting.min_value,
                "max_value": setting.max_value,
                "x_sweep": setting.x_sweep,
                "y_sweep": setting.y_sweep,
                "cohort_sweep": setting.cohort_sweep,
                "jitter": setting.jitter,
            })
        })
        .collect();
    let payload = serde_json::json!({
        "schema": "fluoddity.native_config_contract.v1",
        "source": runtime_config
            .source
            .as_ref()
            .map(|path| path.display().to_string())
            .unwrap_or_else(|| "defaults".to_owned()),
        "notes": runtime_config.notes,
        "rule_seed_value": runtime_config.rule_seed_value,
        "rule_seed": runtime_config.rule_seed,
        "sensor_distance": runtime_config.sensor_distance,
        "sensor_angle": runtime_config.sensor_angle,
        "sensor_gain": runtime_config.sensor_gain,
        "mutation_scale": runtime_config.mutation_scale,
        "drag": runtime_config.drag,
        "strafe_power": runtime_config.strafe_power,
        "axial_force": runtime_config.axial_force,
        "lateral_force": runtime_config.lateral_force,
        "global_force_mult": runtime_config.global_force_mult,
        "trail_persistence": runtime_config.trail_persistence,
        "trail_diffusion": runtime_config.trail_diffusion,
        "hazard_rate": runtime_config.hazard_rate,
        "orientation_mix": runtime_config.orientation_mix,
        "absolute_orientation": runtime_config.absolute_orientation,
        "disable_symmetry": runtime_config.disable_symmetry,
        "hue_sensitivity": runtime_config.hue_sensitivity,
        "color_by_cohort": runtime_config.color_by_cohort,
        "ink_weight": runtime_config.ink_weight,
        "watercolor_mode": runtime_config.watercolor_mode,
        "emboss_mode": runtime_config.emboss_mode,
        "emboss_intensity": runtime_config.emboss_intensity,
        "emboss_smoothness": runtime_config.emboss_smoothness,
        "parameter_sweeps_enabled": runtime_config.parameter_sweeps_enabled,
        "boundary_conditions": runtime_config.boundary_conditions,
        "initial_conditions": runtime_config.initial_conditions,
        "num_cohorts": runtime_config.num_cohorts,
        "has_saved_rule": runtime_config.has_saved_rule,
        "rule_float_count": RULE_FLOAT_COUNT,
        "physics_settings": settings,
    });
    fs::write(path, serde_json::to_string_pretty(&payload)?)?;
    Ok(())
}

fn write_input_contract(path: &Path) -> Result<(), Box<dyn std::error::Error>> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let payload = serde_json::json!({
        "schema": "fluoddity.native_input_contract.v1",
        "runtime": "rust-wgpu",
        "input_backend": "gilrs",
        "cursor": {
            "axis_x": "RightStickX",
            "axis_y": "RightStickY",
            "deadzone": 0.18,
            "speed_per_frame": 0.012,
            "clamp": [0.0, 1.0],
        },
        "actions": [
            {
                "action": "StartOrResume",
                "buttons": ["South"],
                "effect": "Start briefing trial, clear paused state, or return result state to briefing.",
            },
            {
                "action": "PauseToggle",
                "buttons": ["Start", "Mode"],
                "effect": "Toggle native paused flag.",
            },
            {
                "action": "ApplyNutrientGel",
                "buttons": ["RightTrigger2", "RightTrigger"],
                "effect": "Hold to apply only while the trial is actively running.",
            },
            {
                "action": "ExitExperiment",
                "buttons": ["Select"],
                "effect": "Exit the native player window.",
            },
        ],
        "prompt_states": [
            {
                "status": "briefing",
                "prompt_actions": ["StartExperiment", "ApplyNutrientGel", "PauseExperiment"],
            },
            {
                "status": "running",
                "prompt_actions": ["AimNutrientGel", "ApplyNutrientGel", "PauseExperiment"],
            },
            {
                "status": "result",
                "prompt_actions": ["StartExperiment", "ExitExperiment"],
            },
        ],
        "keyboard_fallback": [
            {
                "keys": ["Enter", "Space"],
                "action": "StartOrResume",
            },
            {
                "keys": ["Escape", "P"],
                "action": "PauseToggle",
            },
            {
                "keys": ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"],
                "action": "MoveApplicator",
            },
        ],
        "deck_requirements": [
            "Right stick moves applicator.",
            "R2 applies nutrient gel only while running.",
            "A starts or resumes.",
            "Start/Menu pauses or resumes.",
            "View exits the native player window.",
            "No text entry is required by this native runtime spike.",
        ],
    });
    fs::write(path, serde_json::to_string_pretty(&payload)?)?;
    Ok(())
}

fn deadzone(value: f32) -> f32 {
    if value.abs() < 0.18 { 0.0 } else { value }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    fn repo_root() -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(|path| path.parent())
            .expect("runtime crate should live under runtime/rust-wgpu-spike")
            .to_path_buf()
    }

    fn approx_eq(left: f32, right: f32, epsilon: f32) {
        assert!(
            (left - right).abs() <= epsilon,
            "expected {left} to be within {epsilon} of {right}"
        );
    }

    #[test]
    fn loads_saved_bubbles_config_contract() {
        let path = repo_root()
            .join("physics_configs")
            .join("Core")
            .join("Bubbles.json");
        let config = load_runtime_config(Some(&path)).expect("Bubbles config should load");

        assert_eq!(config.source.as_deref(), Some(path.as_path()));
        assert!(config.has_saved_rule);
        assert_eq!(config.boundary_conditions, 2);
        assert_eq!(config.initial_conditions, 0);
        assert_eq!(config.num_cohorts, 64);
        assert_eq!(config.physics_settings.len(), PHYSICS_SETTING_COUNT);
        approx_eq(config.sensor_distance, 1.64_f32 * 0.018, 0.000_001);
        approx_eq(config.sensor_angle, -0.144, 0.000_001);
        approx_eq(config.sensor_gain, 3.988_130_3, 0.000_001);
        approx_eq(config.trail_persistence, 0.943, 0.000_001);
    }

    #[test]
    fn rejects_malformed_saved_rule_count() {
        let path = repo_root()
            .join("physics_configs")
            .join("Core")
            .join("Bubbles.json");
        let mut value: serde_json::Value =
            serde_json::from_str(&fs::read_to_string(path).expect("Bubbles config should exist"))
                .expect("Bubbles config should parse");
        value["rule"] = serde_json::json!([0.0, 1.0, 2.0]);

        let temp_path = std::env::temp_dir().join("fluoddity_bad_rule_count.json");
        fs::write(&temp_path, serde_json::to_string_pretty(&value).unwrap())
            .expect("test should write temp config");
        let error = match load_runtime_config(Some(&temp_path)) {
            Ok(_) => panic!("bad saved rule length should be rejected"),
            Err(error) => error.to_string(),
        };
        let _ = fs::remove_file(&temp_path);

        assert!(error.contains("rule must contain 80 floats"), "{error}");
    }

    #[test]
    fn loads_rival_bloom_trial_contract() {
        let path = repo_root().join("artifacts").join("trial_definitions.json");
        let trial = load_trial_runtime(&path, Some("rival_bloom"))
            .expect("exported Rival Bloom trial should load");

        assert_eq!(trial.trial_count, 3);
        assert_eq!(trial.trial_id, "rival_bloom");
        assert_eq!(trial.zone_count, 3);
        assert!(trial.rival_enabled);
        assert!(!trial.hazard_enabled);
        approx_eq(trial.rival_x, 0.84, 0.000_001);
        approx_eq(trial.rival_y, 0.50, 0.000_001);
        approx_eq(trial.failure_seconds, 80.0, 0.000_001);
    }

    #[test]
    fn loads_ordered_trial_sequence_for_native_next_flow() {
        let path = repo_root().join("artifacts").join("trial_definitions.json");
        let trials = load_trial_sequence(&path).expect("exported trial sequence should load");

        assert_eq!(trials.len(), 3);
        assert_eq!(trials[0].trial_index, 0);
        assert_eq!(trials[0].trial_id, "bloom");
        assert_eq!(trials[1].trial_index, 1);
        assert_eq!(trials[1].trial_id, "antibiotic_band");
        assert_eq!(trials[2].trial_index, 2);
        assert_eq!(trials[2].trial_id, "rival_bloom");
        assert_eq!(
            selected_trial_index(&trials, Some("antibiotic_band")).unwrap(),
            1
        );
    }

    #[test]
    fn next_trial_index_wraps_at_end_of_sequence() {
        assert_eq!(next_trial_index(0, 3), 1);
        assert_eq!(next_trial_index(1, 3), 2);
        assert_eq!(next_trial_index(2, 3), 0);
        assert_eq!(next_trial_index(0, 0), 0);
    }

    #[test]
    fn result_overlay_names_next_assay_and_sequence_restart() {
        let path = repo_root().join("artifacts").join("trial_definitions.json");
        let trials = load_trial_sequence(&path).expect("exported trial sequence should load");

        let mut first_state = TrialRunState::new(&trials[0]);
        first_state.win("Smoke result reached.".to_owned());
        let first_rows = first_state.overlay_rows(&trials[0]);
        assert!(first_rows[1].contains("Next assay unlocked"));
        assert!(first_rows[2].contains("A NEXT ASSAY"));
        assert!(first_rows[2].contains("VIEW EXIT"));
        let first_actions: Vec<_> = first_state
            .prompt_actions(&trials[0])
            .iter()
            .map(|action| action.steam_action)
            .collect();
        assert_eq!(first_actions, ["StartExperiment", "ExitExperiment"]);

        let mut final_state = TrialRunState::new(&trials[2]);
        final_state.win("Smoke final result reached.".to_owned());
        let final_rows = final_state.overlay_rows(&trials[2]);
        assert!(final_rows[1].contains("Sequence complete"));
        assert!(final_rows[2].contains("A RESTART TRIAL 1"));
        assert!(final_rows[2].contains("VIEW EXIT"));
        let final_actions: Vec<_> = final_state
            .prompt_actions(&trials[2])
            .iter()
            .map(|action| action.steam_action)
            .collect();
        assert_eq!(final_actions, ["StartExperiment", "ExitExperiment"]);
    }

    #[test]
    fn rejects_unknown_trial_id() {
        let path = repo_root().join("artifacts").join("trial_definitions.json");
        let error = match load_trial_runtime(&path, Some("missing_trial")) {
            Ok(_) => panic!("unknown trial id should be rejected"),
            Err(error) => error.to_string(),
        };

        assert!(error.contains("missing_trial"), "{error}");
    }

    #[test]
    fn result_reset_returns_to_briefing_state() {
        let path = repo_root().join("artifacts").join("trial_definitions.json");
        let trial =
            load_trial_runtime(&path, Some("bloom")).expect("exported Bloom trial should load");
        let mut state = TrialRunState::new(&trial);

        state.start(&trial);
        state.win("Smoke result reached.".to_owned());
        assert_eq!(state.status, RunStatus::Won);
        assert_eq!(state.progress, 1.0);
        assert_eq!(state.result_title, "SUCCESS");

        state.reset_to_briefing(&trial);
        assert_eq!(state.status, RunStatus::Briefing);
        assert_eq!(state.progress, 0.0);
        assert_eq!(state.active_zone_mask, 0);
        assert!(state.result_title.is_empty());
        assert_eq!(state.result_summary, trial.running_hint);
    }

    #[test]
    fn video_frame_rates_share_the_same_sixty_hz_simulation_timeline() {
        assert_eq!(simulation_ticks_for_output_frames(30, 30).unwrap(), 60);
        assert_eq!(simulation_ticks_for_output_frames(60, 60).unwrap(), 60);
        assert_eq!(simulation_ticks_for_output_frames(120, 120).unwrap(), 60);
        assert_eq!(simulation_ticks_for_output_frames(1, 120).unwrap(), 1);
        assert_eq!(simulation_ticks_for_output_frames(2, 120).unwrap(), 1);
    }

    #[test]
    fn uhd_export_scales_particle_density_with_pixel_area() {
        assert_eq!(
            particle_count_for_resolution(DEFAULT_WIDTH, DEFAULT_HEIGHT),
            BASE_PARTICLE_COUNT
        );
        assert_eq!(particle_count_for_resolution(3840, 2160), 66_355);
    }

    #[test]
    fn render_dimensions_reject_an_axis_beyond_the_gpu_contract() {
        let error = validate_render_dimensions(16_384, 2)
            .unwrap_err()
            .to_string();
        assert!(error.contains("at most 4096"), "{error}");
    }

    #[test]
    fn window_preview_letterboxes_to_the_export_aspect_ratio() {
        assert_eq!(
            aspect_fit_viewport(3840, 2160, DEFAULT_WIDTH, DEFAULT_HEIGHT),
            (0, 40, 1280, 720)
        );
        assert_eq!(
            aspect_fit_viewport(DEFAULT_WIDTH, DEFAULT_HEIGHT, 1920, 1080),
            (96, 0, 1728, 1080)
        );
    }

    #[test]
    fn video_outputs_must_not_overwrite_each_other() {
        let error = validate_distinct_output_paths(
            Path::new("exports/master.mp4"),
            Some(Path::new("exports/../exports/master.mp4")),
            Path::new("exports/master.json"),
            &[],
        )
        .unwrap_err()
        .to_string();
        assert!(error.contains("must be distinct"), "{error}");
    }

    #[test]
    fn timing_report_must_not_clobber_a_window_recording() {
        let timing_path = Path::new("exports/master.mp4");
        let error = validate_distinct_output_paths(
            Path::new("exports/master.mp4"),
            None,
            Path::new("exports/master.json"),
            &[("--timing-report", timing_path)],
        )
        .unwrap_err()
        .to_string();
        assert!(error.contains("--timing-report"), "{error}");
        assert!(error.contains("--video-out"), "{error}");
    }
}
