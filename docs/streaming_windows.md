# Long-running 3D stream workstation

This branch is a desktop RTX installation for long-running generative broadcasts. It
is intentionally separate from the Steam Deck product work.

## Current validated baseline

- Windows 11
- Python 3.12
- NVIDIA GeForce RTX 5070 Ti with 16 GB VRAM
- CUDA 13 environment-local component packages
- PyOptiX 9.1
- Upstream `Optix` branch at `29adab5`
- 4,000,000 particles and a 256-cubed 3D canvas at the current defaults
- OpenGL 3D point rendering and OptiX sphere rendering both launch

The first visible render is extremely bright with the saved user preferences. Exposure,
brightness, bloom, camera placement, and the default Rule need a stream-specific visual
preset before this should be broadcast.

## Setup

From PowerShell in the Optix worktree:

```powershell
.\scripts\setup_optix_windows.ps1
```

The setup is isolated under `venv/`. It installs the Python dependencies, CUDA component
packages, builds official PyOptiX with MSVC, downloads NVIDIA's public OptiX headers, and
precompiles Fluoddity's sphere-renderer PTX.

WSL is not required. Keeping the simulation, OpenGL context, CUDA interop, OptiX, OBS,
and hardware encoder in one native Windows session removes an unnecessary interop layer.

## Launch

```powershell
.\scripts\run_optix_windows.ps1
```

In Fluoddity:

1. Open **Extras** and enable **3D Controls** and **OptiX Controls**.
2. In **3D Controls**, enable **OptiX Spheres (RTX)**.
3. Press `H` to hide the tutorial and `X` to hide editor windows for a clean viewport.

## Broadcast and clip-capture direction

Use a single OBS scene that captures the Fluoddity window without editor panels. Stream
and record locally at the same time. Local recording should be treated as the source for
vertical shorts; do not cut shorts from a bandwidth-limited social-stream archive.

The next implementation layer is a stream mode that owns:

- a clean fixed-resolution viewport;
- slow camera motion;
- gradual parameter and Rule evolution;
- dead/saturated-state recovery;
- interesting-state markers for later clip extraction;
- periodic health logging and automatic renderer recovery.

Before unattended broadcasting, run a multi-hour soak while recording GPU memory,
render time, frame pacing, and process liveness. The current successful launch is a
functional baseline, not yet an unattended-production certification.

## Local operator interface

The running application polls an atomic command queue under:

```text
%USERPROFILE%\Documents\Fluoddity\Operator\
```

It writes `status.json` once per second, command receipts under `receipts\`, and
interesting-moment/capture markers to `events.jsonl`. `schema.json` describes every
settable field and action for programmatic clients. The heartbeat includes the newest
screenshot and video paths. No network port is opened.

Examples:

```powershell
# Inspect the live heartbeat.
.\venv\Scripts\python.exe .\scripts\stream_operator.py status
.\venv\Scripts\python.exe .\scripts\stream_operator.py schema

# Enable OptiX, hide the editor, and start a slow orbit.
.\venv\Scripts\python.exe .\scripts\stream_operator.py --wait 10 action optix_on
.\venv\Scripts\python.exe .\scripts\stream_operator.py --wait 10 action hide_ui
.\venv\Scripts\python.exe .\scripts\stream_operator.py --wait 10 set camera orbit_rate 0.0005

# Change physics, start a new simulation, and request a labeled still.
.\venv\Scripts\python.exe .\scripts\stream_operator.py set sim MUTATION_SCALE 0.08
.\venv\Scripts\python.exe .\scripts\stream_operator.py action new_simulation
.\venv\Scripts\python.exe .\scripts\stream_operator.py capture branching-coral --note "Candidate short"

# Mark a moment without interrupting the simulation.
.\venv\Scripts\python.exe .\scripts\stream_operator.py mark river-network --note "Review frame in local recording"

# Stop the application cleanly without foreground input.
.\venv\Scripts\python.exe .\scripts\stream_operator.py --wait 10 action quit
```

A complete experiment can be queued as one JSON document:

```json
{
  "version": 1,
  "label": "slow branching orbit",
  "set": {
    "sim": {
      "MUTATION_SCALE": 0.04,
      "TRAIL_PERSISTENCE": 0.96,
      "TRAIL_DIFFUSION": 0.8
    },
    "camera": {
      "orbit_rate": 0.0004,
      "fov": 42.0
    },
    "preferences": {
      "brightness": 0.8,
      "bloom_intensity": 0.08
    }
  },
  "actions": ["optix_on", "hide_ui", "new_simulation", "resume"]
}
```

Queue it with:

```powershell
.\venv\Scripts\python.exe .\scripts\stream_operator.py --wait 10 experiment .\experiment.json
```
