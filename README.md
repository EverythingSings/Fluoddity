# Fluoddity
Fluoddity is an interactive 2D particle system with evolvable behavior. It has an imgui interface with realtime physics and visuals handled by opengl shaders.
I struggle to describe Fluoddity. Think somewhere between interactive lava lamp and evolvable ant farm. 
There is a well considered algorithm that runs the actual physics, with an extensively Claude-Coded user interface built around it. The physics engine itself is a generalization of this excellent Sage Jenson page about physarum transport models: https://cargocollective.com/sagejenson/physarum
I strongly recommend reading at least the first few paragraphs if you want to understand how this project works. 
Any advice or criticism is welcome. This is a toy I made for myself and I am more artist than engineer.
 
## Design
Particles in Fluoddity have no direct interactions. Instead, they leave trails as they move. These trails decay and diffuse over time. Particles respond to the density and direction of trails around them.
There is no fixed rule that determines how particles respond to their sensors. Instead, each particle has a simple neural-net like brain with 80 parameters. These parameters are randomized on startup, and then mutated as the user selects which lineages to explore.

## Screenshots

<img width="1920" height="1129" alt="lavalamp_20260120_152448" src="https://github.com/user-attachments/assets/e8eda829-40d1-4add-afd6-80548a34cf5c" />
<img width="1920" height="1129" alt="lavalamp_20260120_152543" src="https://github.com/user-attachments/assets/6bf3ce1c-8a7f-487f-ad9e-1da67f73686c" />
<img width="1920" height="1129" alt="lavalamp_20260120_152527" src="https://github.com/user-attachments/assets/f1c1b933-f5fd-4802-b2b6-7887d483b71d" />

## Implementation
Fluoddity generalizes the traditional physarum model in a couple ways.
1. Particle trails have a vector velocity/flow component which records the net "current" of particles. Thus, particle trails can interfere, and the trails from an equal number of particles flowing in opposite directions will cancel out.
2. Particle behavior is governed by a 
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
