# Game V1 Prototype

This document defines the first game-shaped prototype for the Fluoddity fork. It is intentionally small. The goal is to prove that the existing simulation can support a satisfying game loop before renaming everything, rewriting the engine, or building a full progression system.

## Readiness

We are ready to build V1 if we treat it as a playable shell around the current engine, not a new engine project.

The current repo already has:

- high-agency generative visuals;
- rule selection and mutation;
- mouse drawing / trail editing;
- save and load for physics plus behavior;
- parameter sweeps;
- multi-load mixing;
- video and screenshot capture;
- controller and Steam Deck groundwork.

The current repo does not yet have:

- a game-mode shell separate from the editor;
- explicit objectives;
- win, fail, and scoring conditions;
- diegetic tool names for sliders and engine operations;
- a slow tutorial path;
- opponent or hazard systems;
- a run structure.

V1 should add only the missing game layer needed to prove the loop.

For now, V1 stays on the existing Python / ModernGL stack. The porting decision is tracked separately in `docs/tech_stack_strategy.md`; the short version is that the game loop should prove itself before the runtime is replaced.

## Design Contract

The imported research in `docs/research/foundations-of-fun.md` sets the bar:

- easy to learn, hard to master;
- fun comes from learning patterns;
- clear goals and immediate feedback;
- meaningful decisions where no option is always best;
- a 10-to-60-second action-feedback-reward loop before larger systems.

For this project, the prototype loop is:

1. The dish presents a visible biological or xenotech problem.
2. The player applies one simple lab tool.
3. The colony responds immediately.
4. The player selects, mutates, feeds, suppresses, or redirects the colony.
5. The dish reports progress, survival, contamination, or failure.

If that loop is not compelling with only one or two tools, more tools will not fix it.

## Onboarding Contract

The simulation is visually dense, so the game introduction must reveal one new idea at a time:

1. Trial 1: one zone, one tool, no hazard.
2. Trial 2: multiple zones plus one passive hazard.
3. Trial 3: culture-site control, one rival pressure source, and the first mutation tool.

Briefings should establish the alien-space-lab fiction before presenting mechanics. Running HUD text should use readable protocol language, not raw engine diagnostics. Detailed activity values can return later as an optional lab-instrument view, but they should not be part of the first playable path.

The first briefing should stay visually quiet: no objective marker, no counterforce band, no rival overlay. Starting the assay reveals the first marked culture zone. Later briefings may show route context, but hazards and rivals should appear only when their assays start.

Game mode must also override noisy editor state at launch. A player entering `--game` should start in a centered camera view with parameter sweeps, debug arrows, watercolor, emboss, advanced drawing, and editor windows off by default. These changes are runtime game-shell defaults, not persistent editor preference changes.

The top menu in game mode should also be game-first. The default bar should expose experiment actions and a deliberately tucked-away editor panel toggle, not the full configuration browser, reset tools, and experimental engine menus.

Unlocked active tools should appear as actual lab controls in the Trial Dish HUD, not just menu items or keyboard-only actions. Passive tools such as Nutrient Gel can remain labeled when their control is the direct mouse/touch brush.

## Theme

Working theme: alien petri-dish xenotech.

The player is not directly piloting units. They are conducting experiments on living synthetic swarms: part alien microorganism, part programmable nanobot culture. This lets the game use biological language for visuals and engineering language for objectives.

Use this fiction to rename engine actions:

| Engine action | Game-facing tool |
| --- | --- |
| Randomize mutation | Irradiate strain |
| Select particle rule | Sample organism |
| Push/pop rule history | Preserve / revert strain |
| Mouse drawing trails | Apply nutrient gel |
| Parameter sweep | Environmental gradient |
| Multi-load | Mixed culture |
| Reset | Sterilize dish |
| Save config | Archive specimen |

The UI should feel like a lab instrument panel, not a raw engine editor.

## Counterforce

The game needs friction. Pretty emergence is not enough.

V1 counterforces should be simple, visible, and compatible with the existing 2D simulation:

- nutrient starvation;
- toxic bands;
- contaminant colonies;
- decay fields;
- rival strains;
- containment boundaries;
- unstable mutation pressure.

Avoid full combat systems in V1. The first opponent can be a passive hazard or a competing field, not an AI enemy.

## First Playable Mode: Trial Dishes

Trial Dishes are short experimental challenges. Each dish gives the player:

- one starting strain;
- one or two lab tools;
- one clear objective;
- one pressure source;
- one short result screen.

The first three Trial Dishes:

### Trial 1: Bloom

Goal: wake a colony and sustain it in one nutrient zone.

Player tools:

- nutrient gel brush.

Pressure:

- no explicit hazard; this teaches the story frame, one visible zone, nutrient gel, and the objective meter without visual overload.

Win condition:

- the first zone remains active for a short hold duration.

Why this first:

- teaches observation and feeding before the player has to parse the full simulation.

### Trial 2: Antibiotic Band

Goal: cross a toxic strip and establish a colony on the far side.

Player tools:

- nutrient gel brush.

Pressure:

- organisms entering the band lose coherence or die off.

Win condition:

- far-side zone remains active for a short hold duration.

Why this second:

- creates the first real adaptation problem without adding mutation controls yet.

### Trial 3: Rival Bloom

Goal: outcompete a rival culture for territory.

Player tools:

- nutrient gel brush;
- irradiate strain;
- preserve / revert strain.

Pressure:

- rival culture grows from a fixed source and overwrites or disrupts trails.

Win condition:

- player culture holds more marked dish sites than the rival when the timer ends.

Why this third:

- introduces a counterpoint and the first deliberate mutation/revert decision without requiring a complex enemy AI.

## Tool Unlock Order

Introduce tools slowly:

1. Observe, pause, reset.
2. Nutrient gel brush.
3. Irradiate strain.
4. Preserve / revert strain.
5. Sample organism.
6. Inhibitor brush.
7. Mixed culture.
8. Environmental gradient.

The first playable build should use only the first four or five.

## V1 Implementation Boundary

Build the smallest vertical slice:

- add a game mode flag or launch option;
- add a Trial Dish state container;
- add objective tracking for one trial;
- add a minimal game HUD;
- map one existing interaction to a diegetic lab tool;
- provide one hand-authored trial config;
- show win/fail feedback;
- keep the existing editor accessible.

Do not rewrite `sim.py` for V1. Use the existing orchestrator and one-shot command pattern.

## First Engineering Slice

Recommended first code slice:

1. Add `state/trial_state.py` with current trial id, timer, progress, status, and objective zones.
2. Add `services/trial_service.py` to evaluate objective zones from simulation readback or a cheap proxy.
3. Add a game HUD mixin/window that shows objective, timer, progress, and current tool.
4. Add a `--game` launch option that starts in Trial 1 with editor panels hidden by default.
5. Bind the existing mouse drawing mode as "nutrient gel" in game mode.

The technical risk is objective measurement. If GPU readback is expensive or awkward, V1 can start with approximate screen-space zone sampling or a simplified proxy. The important part is to close the loop: player action changes the dish, the objective meter responds, and the player can win or fail.

Implementation status:

- Done: `--game` launch option.
- Done: Trial Dish state container.
- Done: a three-trial sequence with retry and next-trial HUD controls.
- Done: lab briefing phase before each trial with a Start Experiment gate.
- Done: Trial Dish service with throttled activity sampling from the simulation canvas.
- Done: minimal game HUD with objective, tool, timer, zone state, progress, win, and fail text.
- Done: end-of-trial result feedback with elapsed-performance grades and lab diagnosis text.
- Done: objective zones are drawn over the dish with active/dormant colors.
- Done: first counterforce, an antibiotic band that visibly suppresses trail activity.
- Done: Trial 2 copy and HUD frame the counterforce as an antibiotic scar/route problem instead of raw hazard diagnostics.
- Done: game mode starts with the editor sidebar hidden and mouse drawing framed as nutrient gel.
- Done: keyboard and controller navigation for the briefing, retry, and next-trial flow.
- Done: second counterforce, a rival bloom source that grows into zone-control pressure.
- Done: first-play ramp reduced to one zone before hazards and rivals are introduced.
- Done: Trial 1 uses shorter protocol copy and simplified running HUD language, emphasizing specimen stability instead of timer and zone diagnostics.
- Done: Trial definitions now carry `onboarding_focus`, and launch-contract smoke verifies the first briefing suppresses objective overlays before revealing the first marked culture zone.
- Done: visual smoke now emits overlay counts/flags and can assert the onboarding reveal order through the actual launch/render path.
- Done: starter specimen primer so early trials begin with a visible culture response.
- Done: Irradiate Strain and Revert Strain unlock in Trial 3, mapped to existing rule history commands.
- Done: Irradiate Strain has limited charges and cooldown, making mutation a deliberate trial tool rather than a spam action.
- Done: Irradiate Strain automatically preserves the pre-mutation strain; Revert Strain can restore that archive once.
- Done: Trial 3 result summaries report irradiation/revert use so the player can connect tool choices to outcome.
- Done: result screens use lab readouts and learning-oriented summaries instead of raw letter grades for early stabilization trials.
- Done: Trial 3 briefing and running status now introduce rival pressure plus mutation economy with compact culture/rival language instead of raw territory math.
- Done: final Trial 3 win can restart the Trial Dish sequence cleanly from Trial 1.
- Done: station guidance updates during each trial so tutorial text introduces one current problem at a time.
- Done: Trial Dish HUD shows compact controller/keyboard prompts for start, retry, next, irradiate, and revert states.
- Done: Trial Dish tool labels distinguish ready, recharge, depleted, archive-ready, no-archive, and spent states.
- Done: progress bars now include semantic objective status such as active sites, hold time, and rival pressure.
- Done: result screens now include a next-step line for unlocked assays, retry focus, or final sequence completion.
- Done: Trial 3 readouts now reflect site margin and mutation economy instead of always reporting the same result.
- Done: each Trial Dish briefing now separates an alien-space-lab story beat from the protocol instructions.
- Done: game-mode runtime startup has a repeatable smoke script.
- Done: V1 prototype checks have a single smoke-suite entry point.
- Done: Sterilize Dish is treated as a visible lab action with station feedback, not a silent editor reset.
- Done: Trial Dish logic smoke now includes a deterministic full-sequence playthrough covering Trial 1 success, Trial 2 failure/retry/success, Trial 3 tool use, final territory resolution, and sequence restart.
- Done: game-mode visual smoke can capture a rendered framebuffer and reject blank startup frames.
- Done: visual smoke can capture Trial 1 briefing, Trial 2 running, and Trial 3 running states for HUD/overlay inspection.
- Done: first briefing protocol copy wraps cleanly in the Trial Dish HUD at the default `800x600` smoke size.
- Done: running Trial Dish controls stack cleanly, and multi-zone markers are positioned clear of the default HUD panel.
- Done: game mode uses a calmer runtime visual profile than the editor, with reduced world size, dimmer brightness, no bloom, and canvas-first rendering for the introductory Trial Dish path.
- Done: visual smoke captures the early active Trial 1 response so objective activation can be inspected, not only dormant overlays.
- Done: visual smoke can apply smoke-only nutrient pulses across objective zones, proving Trial 2 and Trial 3 active-zone HUD/overlay feedback without manual input.
- Done: visual smoke now emits and asserts trial gameplay state, so active-zone captures fail if objective status or progress does not respond.
- Done: fed visual smoke can carry Trial 1 and Trial 2 to `won` states through the normal runtime path.
- Done: game mode has a controller lab cursor: right stick aims nutrient gel, R2 applies it, and the HUD surfaces the control path.
- Done: visual smoke can capture and assert the controller lab cursor plus controller-held Nutrient Gel path.
- Done: visual smoke now emits and asserts the active prompt input scheme, so controller cursor/paused captures prove controller-only HUD prompts instead of only checking glyph-capable text.
- Done: focused controller smoke now drives Trial Dish state transitions through the app controller-action mapper and trial service: start, pause, paused exit, resume, retry, advance, irradiation, revert, and final restart.
- Done: game mode has a timed performance smoke that records average FPS, average frame time, and worst frame time for the Deck-sized profile.
- Done: Trial Dish control prompts are centralized and use configured keyboard labels instead of hard-coded HUD strings.
- Done: Trial Dish control prompts now adapt to recent controller or keyboard/mouse input instead of always showing hybrid labels.
- Done: Trial Dish control prompts now carry structured controller labels, Steam Input action ids, and checked glyph asset paths, so official glyph rendering can be added without parsing HUD text.
- Done: a checked Trial Dish glyph map artifact exists under `steam_input/`, tying prompt action ids to fallback labels and placeholder SVG glyph assets that are parsed and portability-checked by packaging smoke.
- Done: the Trial Dish HUD renders controls from structured prompt specs, not preformatted strings, preserving a direct insertion point for glyph textures.
- Done: visual smoke now serializes the displayed prompt text and checks chip-style controller fallbacks such as `[A]`, `[Right Stick] + [R2]`, `[Menu]`, `[View]`, `[Y]`, and `[L1]`.
- Done: Steam Input handoff generation writes a validated recommended `TrialDish` default binding checklist for the later Steamworks import/configuration pass.
- Done: default `--game` launch now hides raw editor panels and text-entry save/config tools unless `--allow-editor-in-game` is passed.
- Done: the packaged Steam Deck wrapper now launches with `--steam-deck --game`, making the Trial Dish player shell the default Steam target.
- Done: launch contract smoke now verifies `--steam-deck --game` enables Deck resolution, fullscreen, performance defaults, larger UI scale, and editor-gated player-shell mode.
- Done: controller Menu pauses/resumes active Trial Dishes, freezing trial time, simulation, and Nutrient Gel application.
- Done: controller View exits from paused Trial Dishes, giving the player shell a controller-only quit path without exposing editor panels.
- Done: visual smoke captures and asserts the paused Trial Dish HUD state, including suppressed controller Nutrient Gel input while paused.
- Done: initial Steam Input action manifest artifact exists for Trial Dish and editor action sets, with smoke validation for required actions and localization tokens.
- Done: Trial 3 rival pressure now claims a visible far-side zone early enough that the player sees an actual territory problem, and visual smoke asserts that rival-zone pressure.
- Done: visual smoke can fast-forward Trial 3 into a rendered result screen and assert a won Rival Bloom resolution with culture 2 / rival 1 site control.
- Done: visual smoke can fast-forward Trial 2 into a rendered failure result and assert an incomplete hold, with failure copy that distinguishes late stabilization from missing zones.
- Done: default `--game` now gates raw editor shortcuts and persisted help/field-loader windows behind `--allow-editor-in-game`, keeping the first player shell focused on Trial Dishes.
- Done: the orchestrator defensively filters editor-only one-shot commands in default `--game`, while preserving Trial Dish actions such as Start, Retry, Pause, Sterilize Dish, Irradiate, Revert, and Exit.
- Done: the Steam Deck preflight report now summarizes automated evidence, including controller-mode visual prompt captures, so hardware testers see what local gates already proved.
- Done: `scripts/write_trial_dish_playtest_report.py` writes a focused manual playtest report for onboarding, readability, controller confidence, friction, and threshold tuning.
- Done: `scripts/prepare_steam_deck_packet.py` generates the hardware-pass packet in one command.
- Done: `scripts/summarize_trial_dish_playtest.py` turns a filled playtest report into tuning-ready evidence and rejects blank templates when `--require-ready` is used.
- Done: `scripts/write_trial_dish_tuning_reference.py` generates the current Trial Dish thresholds and mechanics values so playtest findings can map directly to tuning changes.
- Done: `scripts/write_trial_dish_tuning_plan.py` combines the playtest summary with the tuning reference into a post-playtest action plan and blocks on incomplete evidence.
- Done: `scripts/smoke_trial_definitions.py` validates Trial Dish schema, onboarding order, zone bounds, timing ranges, hazards, rival pressure, and tuning-reference coverage.
- Done: `scripts/smoke_trial_dish_tuning_reference.py` verifies the generated tuning reference includes every declared Trial Dish tunable with readable labels.
- Done: Trial Dish authored data is separated into `services/trial_definitions.py`, keeping tuning/report tools away from service implementation details.
- Done: `scripts/smoke_trial_module_boundaries.py` keeps authored Trial Dish data owned by `services/trial_definitions.py` instead of drifting back into `TrialService`.
- Done: `scripts/export_trial_definitions.py` generates `artifacts/trial_definitions.json` as a normalized runtime contract, and `scripts/smoke_trial_definitions_export.py` verifies the export is ordered, schema-tagged, JSON-native, and complete enough for runtime defaults.
- Done: `schemas/trial_definitions.schema.json` documents the exported Trial Dish contract, and `scripts/smoke_trial_definitions_schema.py` validates the generated export against it.
- Done: `scripts/smoke_trial_runtime_contract.py` verifies each exported trial matches the `TrialService.load_trial()` runtime state for tools, timers, hazards, rival pressure, primer settings, win condition, and zones.
- Done: `scripts/prepare_steam_deck_packet.py` copies the checked Trial Dish schema into `artifacts/trial_definitions.schema.json` so the hardware packet carries the data contract beside the export.
- Next: use the manual playtest report on real hardware and tune thresholds against that evidence.

## Not V1

Defer these until the first loop works:

- globe surface rendering;
- full campaign progression;
- narrative cutscenes;
- complex enemy AI;
- economy or crafting;
- large rename sweep;
- broad engine rewrite;
- Steam store materials.

## Prototype Done Definition

V1 is done when a fresh player can launch game mode and complete one Trial Dish without opening the raw editor.

Minimum bar:

- the objective is visible;
- the tool is visible;
- player input changes colony behavior;
- progress feedback is immediate;
- success and failure are possible;
- the result makes the player want to retry with a different experimental choice.
