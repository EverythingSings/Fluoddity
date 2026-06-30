from __future__ import annotations

import numpy as np

from state import ObjectiveZone, TrialState


TRIAL_DEFINITIONS = [
    {
        "trial_id": "bloom",
        "title": "Trial 1: Bloom",
        "objective": "Sustain the first culture in the marked nutrient zone.",
        "briefing": (
            "Xenobiology station K-7 has received a dormant culture from deep "
            "space. Apply nutrient gel to wake the specimen and keep the marked "
            "zone alive."
        ),
        "station_line": "K-7 orbital lab: first contact assay opened.",
        "story_line": (
            "You are the remote operator aboard K-7, waking an unknown culture "
            "inside a sealed alien dish."
        ),
        "running_hint": "The primer has woken the specimen. Feed the marked zone until it stabilizes.",
        "protocol_steps": [
            "Observe the marked zone.",
            "Add nutrient gel until the specimen stabilizes.",
        ],
        "unlocked_tools": ["Nutrient Gel"],
        "current_tool": "Nutrient Gel",
        "primer_enabled": True,
        "primer_center": (0.50, 0.50),
        "primer_radius": 0.050,
        "primer_power": 1.20,
        "primer_seconds": 1.20,
        "hold_seconds": 6.0,
        "failure_seconds": 60.0,
        "activity_threshold": 0.0007,
        "hazard_enabled": False,
        "zones": [
            ("A", (0.50, 0.50), 0.10),
        ],
    },
    {
        "trial_id": "antibiotic_band",
        "title": "Trial 2: Antibiotic Band",
        "objective": "Sustain the culture across the antibiotic band.",
        "briefing": (
            "The second dish is crossed by an antibiotic scar. Weak trails fade "
            "inside the red band, so the culture must grow a stable route through "
            "or around it."
        ),
        "station_line": "K-7 orbital lab: hostile reagent detected.",
        "story_line": (
            "The second dish contains an antibiotic scar from a failed containment "
            "attempt; the specimen must learn to survive it."
        ),
        "running_hint": "The antibiotic band erases weak trails. Build stable growth on both sides.",
        "protocol_steps": [
            "Watch the red scar interrupt weak growth.",
            "Feed a route that survives across it.",
            "Hold every marked culture site.",
        ],
        "unlocked_tools": ["Nutrient Gel"],
        "current_tool": "Nutrient Gel",
        "primer_enabled": True,
        "primer_center": (0.48, 0.35),
        "primer_radius": 0.042,
        "primer_power": 0.90,
        "primer_seconds": 0.80,
        "hold_seconds": 10.0,
        "failure_seconds": 90.0,
        "activity_threshold": 0.0007,
        "hazard_enabled": True,
        "hazard_name": "Antibiotic Band",
        "hazard_center_x": 0.50,
        "hazard_width": 0.16,
        "hazard_strength": 0.82,
        "zones": [
            ("A", (0.48, 0.35), 0.08),
            ("B", (0.76, 0.42), 0.08),
            ("C", (0.50, 0.72), 0.08),
        ],
    },
    {
        "trial_id": "rival_bloom",
        "title": "Trial 3: Rival Bloom",
        "objective": "Hold more marked culture sites than the rival bloom when the assay ends.",
        "briefing": (
            "A rival bloom is entering from the right side of the dish. Keep "
            "your culture alive in more marked sites than the contaminant before "
            "the assay closes."
        ),
        "station_line": "K-7 orbital lab: contaminant bloom breached containment.",
        "story_line": (
            "A rival bloom has entered the assay chamber. Your strain is no longer "
            "being observed in isolation."
        ),
        "running_hint": "Outgrow the rival bloom. Mutate only when the current strain stalls.",
        "protocol_steps": [
            "Feed near-side and center sites first.",
            "Irradiate only if the strain stalls.",
            "Revert once if the new strain collapses.",
        ],
        "unlocked_tools": ["Nutrient Gel", "Irradiate Strain", "Revert Strain"],
        "current_tool": "Nutrient Gel",
        "irradiation_charges": 3,
        "irradiation_cooldown_seconds": 8.0,
        "revert_charges": 1,
        "primer_enabled": True,
        "primer_center": (0.48, 0.34),
        "primer_radius": 0.042,
        "primer_power": 0.90,
        "primer_seconds": 0.80,
        "hold_seconds": 0.0,
        "failure_seconds": 80.0,
        "activity_threshold": 0.0007,
        "win_condition": "territory_at_timeout",
        "rival_enabled": True,
        "rival_name": "Rival Bloom",
        "rival_center": (0.84, 0.50),
        "rival_radius": 0.15,
        "rival_growth": 0.0016,
        "rival_strength": 0.72,
        "rival_activity_threshold": 0.50,
        "zones": [
            ("A", (0.48, 0.34), 0.08),
            ("B", (0.50, 0.50), 0.08),
            ("C", (0.76, 0.66), 0.08),
        ],
    },
]


class TrialService:
    """Evaluates the first game-mode Trial Dish.

    The V1 Bloom objective uses throttled readback from the simulation canvas.
    A zone is active when trail density or flow magnitude inside the target
    circle clears the trial threshold.
    """

    def __init__(self):
        self._sample_accumulator = 0.0
        self._sample_interval = 0.25
        self._mask_cache: dict[tuple[int, int, tuple[float, float], float], np.ndarray] = {}

    def load_trial(self, trial: TrialState, index: int) -> None:
        index = max(0, min(index, len(TRIAL_DEFINITIONS) - 1))
        definition = TRIAL_DEFINITIONS[index]
        trial.trial_index = index
        trial.trial_count = len(TRIAL_DEFINITIONS)
        trial.trial_id = definition["trial_id"]
        trial.title = definition["title"]
        trial.objective = definition["objective"]
        trial.briefing = definition["briefing"]
        trial.station_line = definition.get("station_line", "")
        trial.story_line = definition.get("story_line", "")
        trial.running_hint = definition.get("running_hint", "")
        trial.guidance_title = "Station Guidance"
        trial.guidance_message = "Awaiting protocol start."
        trial.protocol_steps = list(definition.get("protocol_steps", []))
        trial.unlocked_tools = list(definition.get("unlocked_tools", ["Nutrient Gel"]))
        trial.default_tool = definition.get("current_tool", "Nutrient Gel")
        trial.current_tool = trial.default_tool
        trial.tool_feedback = ""
        trial.tool_feedback_seconds = 0.0
        trial.irradiation_max_charges = definition.get("irradiation_charges", 0)
        trial.irradiation_charges = trial.irradiation_max_charges
        trial.irradiation_cooldown_seconds = definition.get("irradiation_cooldown_seconds", 0.0)
        trial.irradiation_cooldown_remaining = 0.0
        trial.revert_max_charges = definition.get("revert_charges", 0)
        trial.revert_charges = trial.revert_max_charges
        trial.preserved_strain_available = False
        trial.irradiation_uses = 0
        trial.revert_uses = 0
        trial.primer_enabled = definition.get("primer_enabled", False)
        trial.primer_center = definition.get("primer_center", (0.5, 0.5))
        trial.primer_radius = definition.get("primer_radius", 0.055)
        trial.primer_power = definition.get("primer_power", 1.0)
        trial.primer_seconds = definition.get("primer_seconds", 1.0)
        trial.primer_remaining = 0.0
        trial.hold_seconds = definition["hold_seconds"]
        trial.failure_seconds = definition["failure_seconds"]
        trial.activity_threshold = definition["activity_threshold"]
        trial.win_condition = definition.get("win_condition", "hold_all_zones")
        trial.player_controlled_zones = 0
        trial.rival_controlled_zones = 0
        trial.hazard_enabled = definition.get("hazard_enabled", False)
        trial.hazard_name = definition.get("hazard_name", "Antibiotic Band")
        trial.hazard_center_x = definition.get("hazard_center_x", 0.5)
        trial.hazard_width = definition.get("hazard_width", 0.0)
        trial.hazard_strength = definition.get("hazard_strength", 0.0)
        trial.rival_enabled = definition.get("rival_enabled", False)
        trial.rival_name = definition.get("rival_name", "Rival Bloom")
        trial.rival_center = definition.get("rival_center", (0.82, 0.52))
        trial.rival_radius = definition.get("rival_radius", 0.10)
        trial.rival_growth = definition.get("rival_growth", 0.004)
        trial.rival_strength = definition.get("rival_strength", 0.65)
        trial.rival_activity_threshold = definition.get("rival_activity_threshold", 0.45)
        trial.zones = [
            ObjectiveZone(name, center, radius)
            for name, center, radius in definition["zones"]
        ]
        self.reset(trial)

    def next_trial(self, trial: TrialState) -> None:
        self.load_trial(trial, min(trial.trial_index + 1, len(TRIAL_DEFINITIONS) - 1))

    def restart_sequence(self, trial: TrialState) -> None:
        self.load_trial(trial, 0)

    def reset(self, trial: TrialState) -> None:
        trial.status = "briefing"
        trial.paused = False
        trial.elapsed_seconds = 0.0
        trial.progress = 0.0
        trial.objective_status = "Awaiting protocol."
        trial.result_title = ""
        trial.result_grade = ""
        trial.result_summary = ""
        trial.result_next_step = ""
        trial.guidance_title = "Station Guidance"
        trial.guidance_message = "Awaiting protocol start."
        trial.tool_feedback = ""
        trial.tool_feedback_seconds = 0.0
        trial.current_tool = trial.default_tool
        trial.irradiation_charges = trial.irradiation_max_charges
        trial.irradiation_cooldown_remaining = 0.0
        trial.revert_charges = trial.revert_max_charges
        trial.preserved_strain_available = False
        trial.irradiation_uses = 0
        trial.revert_uses = 0
        trial.player_controlled_zones = 0
        trial.rival_controlled_zones = 0
        trial.primer_remaining = 0.0
        for zone in trial.zones:
            zone.active = False
            zone.activity = 0.0
            zone.rival_activity = 0.0
            zone.rival_controlled = False
        self._sample_accumulator = 0.0
        self._update_guidance(trial)

    def sterilize(self, trial: TrialState) -> None:
        """Reset the current dish as an explicit game/lab action."""
        self.reset(trial)
        trial.guidance_title = "Dish Sterilized"
        trial.guidance_message = "Dish sterilized. Review the protocol before restarting the assay."
        trial.objective_status = "Sterilized; awaiting protocol."

    def start_trial(self, trial: TrialState) -> None:
        """Move a briefing into the running assay state."""
        trial.status = "running"
        trial.paused = False
        if trial.primer_enabled:
            trial.primer_remaining = trial.primer_seconds
        self._update_objective_status(trial)
        self._update_guidance(trial)

    def process_requests(self, trial: TrialState, ui_state) -> None:
        """Handle game-mode one-shot requests before app commands consume them."""
        if not trial.game_mode:
            return

        if ui_state.request_trial_next:
            self.next_trial(trial)
            return

        if ui_state.request_trial_restart_sequence:
            self.restart_sequence(trial)
            return

        if ui_state.request_trial_retry:
            self.load_trial(trial, trial.trial_index)
            return

        if ui_state.request_reset or ui_state.request_full_reset:
            self.sterilize(trial)
            return

        if ui_state.request_trial_start and trial.briefing_active:
            self.start_trial(trial)
            return

        trial_running = not trial.briefing_active and not trial.won and not trial.failed
        if ui_state.request_trial_pause and trial_running:
            trial.paused = not trial.paused
            trial.guidance_title = "Station Stasis" if trial.paused else "Station Guidance"
            trial.guidance_message = (
                "Assay paused. Resume when ready to continue the culture response."
                if trial.paused
                else trial.running_hint
            )
            ui_state.request_revert_strain = False
            ui_state.request_randomize_mutations = False
            self._update_objective_status(trial)
            return

        if not trial_running:
            ui_state.request_revert_strain = False
            ui_state.request_randomize_mutations = False
            return

        if trial.paused:
            ui_state.request_revert_strain = False
            ui_state.request_randomize_mutations = False
            return

        if ui_state.request_revert_strain and trial.revert_unlocked:
            if trial.revert_ready:
                trial.revert_charges -= 1
                trial.preserved_strain_available = False
                trial.revert_uses += 1
                trial.current_tool = "Revert Strain"
                trial.tool_feedback = "Archived strain restored."
                trial.tool_feedback_seconds = 2.5
                self._update_guidance(trial)
            else:
                ui_state.request_revert_strain = False
                if trial.revert_charges <= 0:
                    trial.tool_feedback = "Revert charge has been spent."
                else:
                    trial.tool_feedback = "No archived strain is available."
                trial.tool_feedback_seconds = 1.8
                self._update_guidance(trial)

        if ui_state.request_randomize_mutations and trial.irradiation_unlocked:
            if trial.irradiation_ready:
                trial.irradiation_charges -= 1
                trial.irradiation_uses += 1
                trial.preserved_strain_available = trial.revert_unlocked
                trial.irradiation_cooldown_remaining = trial.irradiation_cooldown_seconds
                trial.current_tool = "Irradiate Strain"
                trial.tool_feedback = "Strain archived. Irradiation pulse applied."
                trial.tool_feedback_seconds = 2.5
                self._update_guidance(trial)
            else:
                ui_state.request_randomize_mutations = False
                if trial.irradiation_charges <= 0:
                    trial.tool_feedback = "Irradiation cells depleted."
                else:
                    trial.tool_feedback = "Irradiation array is recharging."
                trial.tool_feedback_seconds = 1.8
                self._update_guidance(trial)

    def update(self, trial: TrialState, ui_state, frame_count: int, dt: float,
               activity_texture=None) -> None:
        if not trial.game_mode:
            return

        if trial.briefing_active or trial.won or trial.failed or trial.paused:
            return

        trial.elapsed_seconds += max(0.0, dt)
        self._sample_accumulator += max(0.0, dt)
        trial.primer_remaining = max(0.0, trial.primer_remaining - max(0.0, dt))
        trial.tool_feedback_seconds = max(0.0, trial.tool_feedback_seconds - max(0.0, dt))
        trial.irradiation_cooldown_remaining = max(
            0.0, trial.irradiation_cooldown_remaining - max(0.0, dt)
        )

        if activity_texture is not None and (
            self._sample_accumulator >= self._sample_interval or frame_count <= 2
        ):
            self._sample_accumulator = 0.0
            self._sample_zones(trial, activity_texture)

        self._update_zone_control_counts(trial)
        self._update_objective_status(trial)
        self._update_guidance(trial)

        if trial.win_condition == "territory_at_timeout":
            trial.progress = min(1.0, trial.elapsed_seconds / max(trial.failure_seconds, 0.001))
            self._update_objective_status(trial)
            if trial.elapsed_seconds >= trial.failure_seconds:
                self._settle_territory_trial(trial)
            return

        all_zones_active = all(zone.active for zone in trial.zones)
        if all_zones_active:
            trial.progress = min(1.0, trial.progress + dt / trial.hold_seconds)
        else:
            trial.progress = max(0.0, trial.progress - dt / (trial.hold_seconds * 1.5))
        self._update_objective_status(trial)

        if trial.progress >= 1.0:
            trial.status = "won"
            self._set_success_result(trial)
            self._update_objective_status(trial)
            self._update_guidance(trial)
        elif trial.elapsed_seconds >= trial.failure_seconds:
            trial.status = "failed"
            self._set_failure_result(trial)
            self._update_objective_status(trial)
            self._update_guidance(trial)

    def _sample_zones(self, trial: TrialState, texture) -> None:
        width, height = texture.size
        raw = texture.read()
        if not raw:
            return

        canvas = np.frombuffer(raw, dtype=np.float32)
        expected = width * height * 4
        if canvas.size < expected:
            return
        canvas = canvas[:expected].reshape((height, width, 4))

        # Trails use RG as flow/velocity and B as density. Either visible motion
        # or density should count as biological activity in the V1 dish.
        activity = (
            np.linalg.norm(canvas[:, :, 0:2], axis=2)
            + np.abs(canvas[:, :, 2])
        )

        for zone in trial.zones:
            mask = self._zone_mask(width, height, zone.center, zone.radius)
            if not np.any(mask):
                zone.activity = 0.0
                zone.active = False
                zone.rival_activity = 0.0
                zone.rival_controlled = False
                continue
            zone.activity = float(activity[mask].mean())
            zone.rival_activity = self._rival_influence(trial, zone.center)
            zone.rival_controlled = zone.rival_activity >= trial.rival_activity_threshold
            zone.active = (
                zone.activity >= trial.activity_threshold
                and not (trial.rival_enabled and zone.rival_controlled)
            )

        self._update_zone_control_counts(trial)

    def _update_zone_control_counts(self, trial: TrialState) -> None:
        trial.player_controlled_zones = sum(1 for zone in trial.zones if zone.active)
        trial.rival_controlled_zones = sum(1 for zone in trial.zones if zone.rival_controlled)

    def _update_objective_status(self, trial: TrialState) -> None:
        if trial.briefing_active:
            trial.objective_status = "Awaiting protocol."
            return

        if trial.paused:
            trial.objective_status = "Assay paused."
            return

        if trial.won:
            trial.objective_status = "Assay complete."
            return

        if trial.failed:
            trial.objective_status = "Assay failed."
            return

        if trial.win_condition == "territory_at_timeout":
            remaining = max(0.0, trial.failure_seconds - trial.elapsed_seconds)
            trial.objective_status = (
                f"Culture {trial.player_controlled_zones} sites; "
                f"rival {trial.rival_controlled_zones}; "
                f"closes in {remaining:0.1f}s."
            )
            return

        active_count = trial.player_controlled_zones
        total_zones = len(trial.zones)
        hold_remaining = max(0.0, trial.hold_seconds * (1.0 - trial.progress))
        if trial.trial_id == "bloom":
            if active_count == total_zones:
                trial.objective_status = (
                    f"Specimen responding; hold {hold_remaining:0.1f}s."
                )
            else:
                trial.objective_status = "Specimen dormant; feed the marked circle."
            return

        if trial.trial_id == "antibiotic_band":
            if active_count == total_zones:
                trial.objective_status = (
                    f"All culture sites awake; hold {hold_remaining:0.1f}s."
                )
            else:
                trial.objective_status = (
                    f"Stable sites: {active_count}/{total_zones}; bridge the red scar."
                )
            return

        if active_count == total_zones:
            trial.objective_status = (
                f"Zones active: {active_count}/{total_zones}; "
                f"hold {hold_remaining:0.1f}s."
            )
        else:
            trial.objective_status = (
                f"Zones active: {active_count}/{total_zones}; "
                "wake every marked zone."
            )

    def _update_guidance(self, trial: TrialState) -> None:
        """Show one current instruction so the first game path stays readable."""
        if trial.briefing_active:
            trial.guidance_title = "Station Guidance"
            trial.guidance_message = "Read the protocol, then start the experiment."
            return

        if trial.paused:
            trial.guidance_title = "Station Stasis"
            trial.guidance_message = "Assay paused. Resume when ready to continue the culture response."
            return

        if trial.won or trial.failed:
            trial.guidance_title = "Assay Result"
            trial.guidance_message = trial.result_summary
            return

        active_count = trial.player_controlled_zones
        total_zones = max(1, len(trial.zones))

        if trial.trial_id == "bloom":
            trial.guidance_title = "First Contact"
            if active_count == 0:
                trial.guidance_message = "Paint nutrient gel inside the marked circle until the specimen brightens."
            elif trial.progress < 0.35:
                trial.guidance_message = "The specimen is responding. Keep feeding the same zone."
            else:
                trial.guidance_message = "Hold steady. Stability rises while the marked zone stays active."
            return

        if trial.trial_id == "antibiotic_band":
            trial.guidance_title = "Antibiotic Band"
            if active_count == 0:
                trial.guidance_message = "Start from the near-side culture. The red scar erases weak trails."
            elif active_count < total_zones:
                trial.guidance_message = "A route is forming. Reinforce quiet sites until growth crosses the scar."
            else:
                trial.guidance_message = "All sites are awake. Keep the route alive until stabilization completes."
            return

        if trial.trial_id == "rival_bloom":
            trial.guidance_title = "Containment Race"
            if trial.rival_controlled_zones >= active_count and trial.elapsed_seconds > 10.0:
                trial.guidance_message = "The rival is matching your culture. Reclaim the center before the assay closes."
            elif trial.preserved_strain_available:
                trial.guidance_message = "A strain archive is loaded. Revert if the irradiated behavior collapses."
            elif trial.irradiation_ready and trial.irradiation_uses == 0:
                trial.guidance_message = "Irradiation is ready. Use it only if the current strain stops spreading."
            elif trial.irradiation_cooldown_remaining > 0.0:
                trial.guidance_message = "Irradiation is recharging. Feed stable routes while the mutation settles."
            else:
                trial.guidance_message = "Hold more marked sites than the rival bloom when the assay closes."
            return

        trial.guidance_title = "Station Guidance"
        trial.guidance_message = trial.running_hint

    def _settle_territory_trial(self, trial: TrialState) -> None:
        self._update_zone_control_counts(trial)
        if trial.player_controlled_zones > trial.rival_controlled_zones:
            trial.status = "won"
            self._set_success_result(trial)
        else:
            trial.status = "failed"
            self._set_failure_result(trial)
        self._update_objective_status(trial)
        self._update_guidance(trial)

    def _set_success_result(self, trial: TrialState) -> None:
        if trial.win_condition == "territory_at_timeout":
            margin = trial.player_controlled_zones - trial.rival_controlled_zones
            if margin >= 2 and trial.irradiation_uses <= 1 and trial.revert_uses == 0:
                grade = "Clean Dominance"
                diagnosis = "The culture held territory with minimal mutation pressure."
            elif margin >= 2:
                grade = "Dominant"
                diagnosis = "The culture won decisively, though mutation support was needed."
            else:
                grade = "Contained"
                diagnosis = "The culture beat the contaminant by a narrow site margin."
            trial.result_title = "Rival Contained"
            trial.result_grade = grade
            trial.result_summary = (
                f"Culture held {trial.player_controlled_zones} sites; "
                f"{trial.rival_name} held {trial.rival_controlled_zones}. "
                f"Irradiation pulses used: {trial.irradiation_uses}; "
                f"reverts used: {trial.revert_uses}. "
                f"{diagnosis}"
            )
            trial.result_next_step = (
                "Sequence complete. Repeat the assay to test a different mutation path."
            )
            return

        ratio = trial.elapsed_seconds / max(trial.failure_seconds, 0.001)
        if ratio <= 0.35:
            grade = "Rapid"
            summary = "The culture stabilized quickly. Nutrient routes were clear and easy to sustain."
        elif ratio <= 0.65:
            grade = "Stable"
            summary = "The culture stabilized. Response was slower, but the route stayed alive."
        else:
            grade = "Fragile"
            summary = "The culture survived late. Start feeding earlier or reinforce the route sooner."

        trial.result_title = "Culture Stabilized"
        trial.result_grade = grade
        trial.result_summary = summary
        if trial.trial_index + 1 < len(TRIAL_DEFINITIONS):
            next_trial = TRIAL_DEFINITIONS[trial.trial_index + 1]
            trial.result_next_step = (
                f"Next assay unlocked: {next_trial['title']}."
            )
        else:
            trial.result_next_step = "Sequence complete."

    def _set_failure_result(self, trial: TrialState) -> None:
        active_count = sum(1 for zone in trial.zones if zone.active)
        if trial.win_condition == "territory_at_timeout":
            if trial.player_controlled_zones == trial.rival_controlled_zones:
                grade = "Stalemate"
                diagnosis = "The assay tied. One more culture site would contain the bloom."
            elif trial.player_controlled_zones == 0:
                grade = "Overgrown"
                diagnosis = "The contaminant denied every marked zone."
            else:
                grade = "Outcompeted"
                diagnosis = "The contaminant held more culture sites at timeout."
            trial.result_title = "Rival Overgrowth"
            trial.result_grade = grade
            trial.result_summary = (
                f"Culture held {trial.player_controlled_zones} sites; "
                f"{trial.rival_name} held {trial.rival_controlled_zones}. "
                f"Irradiation pulses used: {trial.irradiation_uses}; "
                f"reverts used: {trial.revert_uses}. "
                f"{diagnosis} Seed stronger routes earlier, then mutate only when the current strain stalls."
            )
            trial.result_next_step = (
                "Retry with earlier nutrient routes and save irradiation for stalled growth."
            )
            return

        trial.result_title = "Culture Failed"
        trial.result_grade = "Unstable"
        total_zones = len(trial.zones)
        if active_count == total_zones:
            trial.result_summary = (
                f"All {total_zones} culture sites woke, but stabilization began too late."
            )
            trial.result_next_step = (
                "Retry with earlier routes across the scar so stabilization starts sooner."
            )
        else:
            trial.result_summary = (
                f"{active_count}/{total_zones} culture sites were stable at timeout. "
                "Adjust nutrient placement and retry the experiment."
            )
            trial.result_next_step = "Retry the dish and keep every marked culture site active before timeout."

    def _rival_influence(self, trial: TrialState, point: tuple[float, float]) -> float:
        if not trial.rival_enabled:
            return 0.0

        dx = point[0] - trial.rival_center[0]
        dy = point[1] - trial.rival_center[1]
        distance = float(np.sqrt(dx * dx + dy * dy))
        radius = trial.rival_radius + trial.elapsed_seconds * trial.rival_growth
        feather = max(radius * 0.35, 0.001)
        return float(np.clip(1.0 - ((distance - radius) / feather), 0.0, 1.0))

    def _zone_mask(self, width: int, height: int, center: tuple[float, float],
                   radius: float) -> np.ndarray:
        key = (width, height, center, radius)
        cached = self._mask_cache.get(key)
        if cached is not None:
            return cached

        xs = (np.arange(width, dtype=np.float32) + 0.5) / width
        ys = (np.arange(height, dtype=np.float32) + 0.5) / height
        xx, yy = np.meshgrid(xs, ys)
        aspect = width / height if height > 0 else 1.0
        dx = (xx - center[0]) * np.sqrt(aspect)
        dy = (yy - center[1]) / np.sqrt(aspect)
        mask = (dx * dx + dy * dy) <= radius * radius
        self._mask_cache[key] = mask
        return mask
