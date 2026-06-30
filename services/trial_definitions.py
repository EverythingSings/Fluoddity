from __future__ import annotations


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
        "onboarding_focus": "single_culture",
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
        "onboarding_focus": "counterforce",
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
        "onboarding_focus": "rival_pressure",
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
