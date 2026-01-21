# Fluoddity
Fluoddity is an interactive 2D particle system with evolvable behavior. It has an imgui interface with gpu physics and rendering in opengl.
I struggle to describe Fluoddity. Think somewhere between interactive lava lamp and evolvable ant farm. 
There is a well considered algorithm that runs the actual physics, with an extensively Claude-Coded user interface built around it. The physics engine itself is a generalization of this excellent Sage Jenson page about physarum transport models: https://cargocollective.com/sagejenson/physarum
I strongly recommend reading at least the first few paragraphs if you want to understand how this project works. I've been tinkering with this idea for years, and it still feels like there's an ocean of possibilities i have yet to explore (3d generalization chief among them)
Any advice or criticism is welcome. This is a toy I made for myself and I am more artist than engineer. 

## Features
 - "physics sliders" to customize simulation parameters.
 - particle selection/mutation to customize particle behavior
 - mouse drawing mode for making trails
 - Save/load system for physics + behavior
 - save strings with copy/paste from clipboard
 - parameter sweeps mode allows varying physics sliders across the canvas. X and Y sweeps for exploring 2d parameter space.
 - variable physics frequency with motion blur
 - ffmpeg video recording
 - Emboss visual effect (currently the only use for traditional density trails)

## Design
Particles in Fluoddity have no direct interactions. Instead, they leave trails as they move. These trails decay and diffuse over time. Particles respond to the density and direction of trails around them.
There is no fixed rule that determines how particles respond to their sensors. Instead, each particle has a simple neural-net like brain with 80 parameters. These parameters are randomized on startup, and then mutated as the user selects which lineages to explore.

## Screenshots

<img width="1920" height="1129" alt="lavalamp_20260120_152448" src="https://github.com/user-attachments/assets/e8eda829-40d1-4add-afd6-80548a34cf5c" />
<img width="1920" height="1129" alt="lavalamp_20260120_152543" src="https://github.com/user-attachments/assets/6bf3ce1c-8a7f-487f-ad9e-1da67f73686c" />
<img width="1920" height="1129" alt="lavalamp_20260120_152527" src="https://github.com/user-attachments/assets/f1c1b933-f5fd-4802-b2b6-7887d483b71d" />

## Model
Fluoddity generalizes the traditional physarum model in a couple ways.
###Trail interference
Particle trails have a vector velocity/flow component which records the net "current" of particles. Thus, particle trails can interfere, and the trails from an equal number of particles flowing in opposite directions will cancel out.
###Behavior
Particle behavior is governed by a somewhat arbitrary black box function. I use a simple sum of sin waves because I wanted smooth, periodic noise. Trail sensor values are fed into this noise function, and the outputs are used to accelerate and reposition the particle.
###"Strafe"
In addition to forces causing acceleration, each paricle has a limited ability to "strafe", changing position independently from velocity. This is the least "principled" of my generalizations, but it is incredibly simple and enables some really beautiful patterns. Strafe allows particles to leave velocity trails which disagree with their direction of travel, enabling things like "swimming upstream" without turning around or "shifting to the left" without losing track of which way is "forward". 
## Installation

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

Run main.py

## Building

For instructions on building a standalone executable, see [BUILD.md](BUILD.md).

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
