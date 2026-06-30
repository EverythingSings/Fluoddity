
![bubbles 12 46 01 (1)](https://github.com/user-attachments/assets/ecd4a0dc-a11f-45b3-b603-b4e27e8e576b)
# Fluoddity
I struggle to describe Fluoddity. Think somewhere between interactive lava lamp and evolvable ant farm. 
Sometimes I'll see a meandering river, a candle flame, or branching lightning. Sometimes it's more like looking under a microscope as little amoebas devour each other and break apart. And sometimes, it's stranger than all that.

## WebGL Demo: https://aphid91.github.io/Fluoddity-Core/
<img width="1920" height="1129" alt="lavalamp_20260120_152448" src="https://github.com/user-attachments/assets/e8eda829-40d1-4add-afd6-80548a34cf5c" />
<img width="1920" height="1129" alt="lavalamp_20260120_152543" src="https://github.com/user-attachments/assets/6bf3ce1c-8a7f-487f-ad9e-1da67f73686c" />
<img width="1920" height="1129" alt="lavalamp_20260120_152527" src="https://github.com/user-attachments/assets/f1c1b933-f5fd-4802-b2b6-7887d483b71d" />

Fluoddity is a 2d particle system designed for realtime exploration. I've been tinkering with this idea for years, and it still feels like there's an ocean of possibilities I have yet to fully explore (3d generalization chief among them). There is a well considered algorithm that runs the actual physics, with an extensively Claude-Coded user interface built around it. 
The physics engine itself is a generalization of this excellent Sage Jenson page about physarum transport models: 
https://cargocollective.com/sagejenson/physarum

I strongly recommend reading at least the first few paragraphs if you want to understand how this project works. 
## Fluoddity-Core: https://github.com/aphid91/Fluoddity-Core
The algorithm that drives the Fluoddity particle system is pretty simple, but Fluoddity itself has a lot of bells and whistles. Fluoddity-Core exists as a minimal shell that is easier to understand and tinker with. It has just enough machinery to load and run a basic Fluoddity config with no UI fluff. Fluoddity-Core also hosts a Claude-Code port of the core engine to webgl that runs on github pages (This is the demo linked above).
Any advice or criticism is welcome. This is a toy I made for myself and I am more artist than engineer. 

## Features
 - "physics sliders" to customize simulation parameters.
 - particle selection/mutation to customize particle behavior
 - mouse drawing mode for making trails
 - Save/load system for physics + behavior
 - save strings with copy/paste from clipboard
 - parameter sweeps mode allows varying physics sliders across the canvas. X and Y sweeps for exploring 2d parameter space.
 - variable physics frequency with motion blur
 - ffmpeg based video recording
 - Emboss visual effect (currently the only use for traditional density trails)
 - Experimental system for mixing different saved configs.
## Design
Particles in Fluoddity have no direct interactions with each-other. Instead, they leave trails as they move. These trails decay and diffuse over time. Particles respond to the density and direction of trails around them.
There is no fixed rule that determines how particles respond to their senses. Instead, each particle has a simple neural-net like brain with just 80 parameters. These parameters are randomized on startup, and then mutated as the user selects which lineages to explore.

## Screenshots
<img width="797" height="595" alt="image" src="https://github.com/user-attachments/assets/343b2f6a-c09b-41c1-a370-247c223c33a7" />
<img width="797" height="597" alt="image" src="https://github.com/user-attachments/assets/c70ce389-fe63-4635-bb5f-bbd62bd7a317" />


## Model
Fluoddity generalizes the traditional physarum model in a couple ways.
### Trail interference
Particle trails have a velocity/flow vector which records the net "current" of particles. Thus, particle trails can interfere, and the trails from an equal number of particles flowing in opposite directions will cancel out.
### Behavior - Rules
Particle behavior is governed by a somewhat arbitrary black box function called a 'Rule'. I use a simple sum of sin waves because i wanted smooth, periodic noise. Trail sensor values are fed into this noise function, and the outputs are used to accelerate and reposition the particle.
### "Strafe"
In addition to forces causing acceleration, each paricle has a limited ability to "strafe", changing position independently from velocity. This is the least "principled" of my generalizations, but it is incredibly simple and enables some really beautiful patterns. Strafe allows particles to leave velocity trails which disagree with their direction of travel, enabling things like "swimming upstream" without turning around or "sidle to the left" without losing track of which way is "forward". 
### Symmetry
The traditional physarum model has some important symmetries that we would like to impose on our otherwise arbitrary noise functions. These symmetries can be toggled (or dialed down) in additional settings.

- Rotational: 
Rotate the whole world by 90°, and nothing should change: the dynamics are independent of global orientation. Particles should never favor the bottom left corner of the screen, for example. Achieving this symmetry is as simple as calculating all sensors/forces in a local coordinate system where "up" == particle velocity.

- Chiral:
Reflect the world across the X axis and nothing should change: the dynamics are identical when viewed in a mirror. Particles in the traditional physarum model display bilateral symmetry, they are not "left handed" or "right handed". Without this property, fluoddity particles show clockwise/counterclockwise bias, and the behavior space consists mostly of particles which are always turning left, or always turning right. This symmetry is achieved by calculating physics twice: once in mirrored coordinates, and averaging the results.

Enforcing these symmetries drastically reduces the prevalence of boring and degenerate Rules.

### Future Exploration
- Trail diffusion step replaced with arbitrary continuous cellular automata. wave equation or advection along flow lines could be interesting
- More than just two sensors.
- Disentangle "local orientation" from "particle velocity". Strafe mechanic hints at this being worthwhile.
- Particle internal state/ memory. Current particle behavior is memoryless aside from velocity persistence.
- Trails need not correspond to particle velocity. "Trail vector" could be just another output of the Rule function. Trail dimensionality could be increased.
- A more universal framework for describing these kinds of systems. One could generalize all the way to continuous cellular automata + continuous turmites.
  
### Requirements

- Python 3.x
- OpenGL-compatible graphics card

### Setup

1. Clone this repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage
Either:
pip install requirements, then run main.py
OR
Download a release and run Fluoddity.exe 

## Game Prototype

This fork is starting to grow a game shell around the simulation. The current V1 direction is an alien petri-dish xenotech game mode, documented in [docs/game_v1_prototype.md](docs/game_v1_prototype.md).

Current stack and porting strategy are tracked in [docs/tech_stack_strategy.md](docs/tech_stack_strategy.md).

Run the first Trial Dish shell with:

```bash
python main.py --game
```

The default game shell hides raw editor panels and text-entry save/config tools.
For development work inside a Trial Dish launch, use:

```bash
python main.py --game --allow-editor-in-game
```

In game mode, mouse/touch can apply Nutrient Gel directly. With a controller,
use the right stick to aim the lab cursor and R2 to apply Nutrient Gel.
Press Menu to pause or resume the active assay. Press View from the paused
state to exit the player shell.
The Trial Dish HUD adapts its prompt labels to the most recent controller or
keyboard/mouse input.

Check Trial Dish logic without launching OpenGL:

```bash
python scripts/smoke_trial_dishes.py
python scripts/smoke_game_controller.py
python scripts/smoke_game_shell_contract.py
python scripts/smoke_steam_input_manifest.py
python scripts/smoke_steam_deck_packaging.py
```

Run the V1 prototype smoke suite:

```bash
python scripts/smoke_game_v1.py
```

Run the visual V1 checks, including rendered success and failure result screens:

```bash
python scripts/smoke_game_v1.py --with-visual --with-fed-results
```

Use a specific interpreter when validating a venv or platform install:

```bash
python scripts/smoke_game_v1.py --python .venv/Scripts/python.exe
```

Check that game mode launches and stays alive briefly:

```bash
python scripts/smoke_game_runtime.py
```

Record game-mode frame timing at the Deck-sized profile:

```bash
python scripts/smoke_game_performance.py --extra-arg=--deck-performance
```

Prepare a Steam Deck hardware validation report:

```bash
python scripts/prepare_steam_deck_packet.py
```

This writes a packet index, Trial Dish definitions JSON/schema, Steam Input
handoff, manual playtest sheet, playtest summary, tuning reference, tuning plan,
and Steam Deck preflight report under `artifacts/`.

For a packet that also reruns local automated gates:

```bash
python scripts/prepare_steam_deck_packet.py --run-automated --with-visual --with-fed-results
```

Capture and validate a nonblank game-mode frame:

```bash
python scripts/smoke_game_visual.py
```

Capture later trial states:

```bash
python scripts/smoke_game_visual.py --trial 1 --start --frame 25 --expect-active-zones 1 --expect-progress-min 0.01 --expect-status running
python scripts/smoke_game_visual.py --trial 1 --start --frame 45 --controller-cursor --controller-feed --expect-active-zones 1 --expect-progress-min 0.01 --expect-status running --expect-controller-cursor --expect-controller-draw
python scripts/smoke_game_visual.py --trial 1 --start --pause --frame 45 --controller-cursor --controller-feed --expect-status running --expect-paused --expect-no-controller-cursor --expect-no-controller-draw
python scripts/smoke_game_visual.py --trial 2 --start --feed --frame 90 --expect-active-zones 2 --expect-progress-min 0.05 --expect-status running
python scripts/smoke_game_visual.py --trial 3 --start --feed --frame 90 --expect-active-zones 2 --expect-rival-zones 1 --expect-progress-min 0.01 --expect-status running
python scripts/smoke_game_visual.py --trial 1 --start --feed --frame 240 --expect-active-zones 1 --expect-progress-min 1.0 --expect-status won
python scripts/smoke_game_visual.py --trial 2 --start --resolve --frame 120 --expect-progress-max 0.99 --expect-status failed
python scripts/smoke_game_visual.py --trial 2 --start --feed --frame 450 --expect-active-zones 2 --expect-progress-min 1.0 --expect-status won
python scripts/smoke_game_visual.py --trial 3 --start --feed --resolve --frame 120 --expect-active-zones 2 --expect-rival-zones 1 --expect-progress-min 1.0 --expect-status won
```

Pass launch variants through with repeated `--extra-arg` values:

```bash
python scripts/smoke_game_runtime.py --extra-arg=--deck-performance
python scripts/smoke_game_performance.py --extra-arg=--deck-performance --min-fps 30
```

## Steam Deck / Linux

```bash
git clone https://github.com/EverythingSings/Fluoddity.git
cd Fluoddity
bash scripts/build_linux.sh
./dist/Fluoddity/run_steam_deck.sh
```

The generated Deck wrapper launches the player shell with `--steam-deck --game`.

For source runs without packaging:

```bash
python main.py --steam-deck --game
```

Steam Input artifacts live under `steam_input/` and are copied into `dist/Fluoddity/steam_input/` by `scripts/build_linux.sh`. This includes the initial action manifest, Trial Dish prompt glyph map, checked placeholder SVG glyphs, and a generated handoff report for the Steamworks import pass. Local smokes verify the manifest, localization tokens, prompt action ids, glyph metadata, packaged glyph file presence, active HUD prompt-to-glyph path, and recommended default bindings. A real Steamworks import/default configuration pass and official Steam/Deck glyph rendering pass are still required before this should be treated as final store-package input support.

## Building

For instructions on building a standalone executable, see [BUILD.md](BUILD.md).

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
