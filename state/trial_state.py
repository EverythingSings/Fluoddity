from dataclasses import dataclass, field


@dataclass
class ObjectiveZone:
    """A visible target region for a Trial Dish objective."""
    name: str
    center: tuple[float, float]
    radius: float
    active: bool = False
    activity: float = 0.0
    rival_activity: float = 0.0
    rival_controlled: bool = False


@dataclass
class TrialState:
    """Game-mode state for the first playable Trial Dish prototype."""
    game_mode: bool = False
    trial_index: int = 0
    trial_count: int = 1
    trial_id: str = "bloom"
    title: str = "Trial 1: Bloom"
    objective: str = "Sustain the culture in all three nutrient zones."
    briefing: str = (
        "Specimen XC-01 responds to nutrient gel. Activate all marked zones "
        "and hold the culture stable."
    )
    station_line: str = "K-7 xenobiology station is online."
    story_line: str = "You are the remote operator assigned to the dish."
    running_hint: str = "Apply nutrient gel until the marked culture zone stabilizes."
    guidance_title: str = "Station Guidance"
    guidance_message: str = "Awaiting protocol start."
    transition_message: str = ""
    onboarding_focus: str = "single_culture"
    protocol_steps: list[str] = field(default_factory=lambda: [
        "Observe the marked zone.",
        "Apply nutrient gel.",
        "Hold the culture stable.",
    ])
    unlocked_tools: list[str] = field(default_factory=lambda: ["Nutrient Gel"])
    default_tool: str = "Nutrient Gel"
    current_tool: str = "Nutrient Gel"
    tool_feedback: str = ""
    tool_feedback_seconds: float = 0.0
    first_response_seen: bool = False
    route_forming_seen: bool = False
    route_stable_seen: bool = False
    irradiation_charges: int = 0
    irradiation_max_charges: int = 0
    irradiation_cooldown_seconds: float = 0.0
    irradiation_cooldown_remaining: float = 0.0
    revert_charges: int = 0
    revert_max_charges: int = 0
    preserved_strain_available: bool = False
    irradiation_uses: int = 0
    revert_uses: int = 0
    primer_enabled: bool = False
    primer_center: tuple[float, float] = (0.50, 0.50)
    primer_radius: float = 0.055
    primer_power: float = 1.35
    primer_seconds: float = 1.25
    primer_remaining: float = 0.0
    status: str = "briefing"
    paused: bool = False
    elapsed_seconds: float = 0.0
    progress: float = 0.0
    objective_status: str = "Awaiting protocol."
    specimen_readout: str = ""
    route_readout: str = ""
    mutation_readout: str = ""
    timer_readout: str = ""
    result_title: str = ""
    result_grade: str = ""
    result_summary: str = ""
    result_experiment_hint: str = ""
    result_next_step: str = ""
    visual_smoke_feed: bool = False
    hold_seconds: float = 12.0
    failure_seconds: float = 90.0
    activity_threshold: float = 0.0007
    win_condition: str = "hold_all_zones"
    player_controlled_zones: int = 0
    rival_controlled_zones: int = 0
    containment_margin: int = 0
    containment_readout: str = ""
    hazard_enabled: bool = False
    hazard_name: str = "Antibiotic Band"
    hazard_center_x: float = 0.50
    hazard_width: float = 0.16
    hazard_strength: float = 0.82
    rival_enabled: bool = False
    rival_name: str = "Rival Bloom"
    rival_center: tuple[float, float] = (0.82, 0.52)
    rival_radius: float = 0.10
    rival_growth: float = 0.004
    rival_strength: float = 0.65
    rival_activity_threshold: float = 0.45
    zones: list[ObjectiveZone] = field(default_factory=lambda: [
        ObjectiveZone("A", (0.30, 0.35), 0.08),
        ObjectiveZone("B", (0.70, 0.42), 0.08),
        ObjectiveZone("C", (0.50, 0.70), 0.08),
    ])

    @property
    def won(self) -> bool:
        return self.status == "won"

    @property
    def failed(self) -> bool:
        return self.status == "failed"

    @property
    def briefing_active(self) -> bool:
        return self.status == "briefing"

    @property
    def minimal_onboarding(self) -> bool:
        return self.onboarding_focus == "single_culture"

    @property
    def final_trial(self) -> bool:
        return self.trial_index >= self.trial_count - 1

    @property
    def irradiation_unlocked(self) -> bool:
        return "Irradiate Strain" in self.unlocked_tools

    @property
    def irradiation_ready(self) -> bool:
        return (
            self.irradiation_unlocked
            and self.irradiation_charges > 0
            and self.irradiation_cooldown_remaining <= 0.0
        )

    @property
    def revert_unlocked(self) -> bool:
        return "Revert Strain" in self.unlocked_tools

    @property
    def revert_ready(self) -> bool:
        return (
            self.revert_unlocked
            and self.revert_charges > 0
            and self.preserved_strain_available
        )
