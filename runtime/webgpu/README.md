# networked.art/everything HTML artifacts

This runtime packages the generative particle engine as one self-contained
HTML file under the `networked.art/everything` identity. All JavaScript, CSS,
preset data, and WGSL are inline, and the finished document does not load
anything from the network or persist anything in the browser.

The Python/ModernGL runtime and the shaders in `shaders/` remain this artifact's
particle-dynamics reference. The Rust/wgpu runtime is the active native shipping
track; it is a sibling implementation rather than the source for this browser
artifact.

## Build an artifact

From the repository root:

```powershell
python scripts/build_webgpu_artifact.py
python scripts/smoke_webgpu_artifact.py
python scripts/smoke_webgpu_responsive.py --skip-build
python scripts/audit_webgpu_artifact_parity.py --require-complete
```

The default build uses `physics_configs/Core/Curls.json`, 120,000 particles,
and a 512 x 512 simulation surface. It writes:

- `artifacts/networked-art/everything.html`
- `artifacts/networked-art/everything.manifest.json`

Use any saved version-7 preset with an 80-float rule:

```powershell
python scripts/build_webgpu_artifact.py `
  --config physics_configs/Core/Butterflies.json `
  --title "Butterflies" `
  --particle-count 180000 `
  --resolution 640 `
  --output artifacts/networked-art/butterflies.html `
  --manifest artifacts/networked-art/butterflies.manifest.json

python scripts/smoke_webgpu_artifact.py `
  artifacts/networked-art/butterflies.html `
  --manifest artifacts/networked-art/butterflies.manifest.json
```

The builder validates the config contract, inlines every WGSL file, writes
atomically, records SHA-256 hashes in the manifest, and refuses an artifact
larger than networked.art's current 95,000,000-byte client limit.

The parity audit checks the load-bearing source contract against the canonical
GLSL/Python runtime and every saved v7 preset. Its reports land in
`artifacts/webgpu/source-contract-audit.{json,md}`. This is structural evidence,
not a claim of cross-API numeric or pixel identity.

The responsive smoke launches the generated file in a real headless Chrome or
Edge iframe-sized viewport matrix. It requires all four sliders to remain
rendered, scroll-reachable, hit-testable, and focusable, and it exercises their
bound input handlers. Set
`FLUODDITY_BROWSER` or pass `--browser` when the browser is not on `PATH`.

WebGPU requires a secure context. Test through localhost rather than opening
the generated file directly:

```powershell
python -m http.server 8765
```

Then open:

```text
http://127.0.0.1:8765/artifacts/networked-art/everything.html
```

Localhost is treated as a secure context by current browsers. A deployed
artifact should be served over HTTPS.

The committed harness reproduces networked.art's script-only iframe sandbox:

```text
http://127.0.0.1:8765/runtime/webgpu/sandbox-harness.html
```

## Interaction contract

The artifact is deliberately small enough to behave like a tiny artwork app:

- Drag or touch the canvas to bend the flow field.
- Right-drag to erase locally.
- Pause/resume, reset, or create a seeded variation.
- Adjust motion, trail persistence, drawing force, and brightness.
- Use Space, R, N, and H for the same common actions.

The controls remain present at compact iframe sizes. When vertical space is
exceptionally tight, the glass control panel scrolls internally instead of
hiding sliders or requiring browser zoom.

State exists only in memory for the current view. The artifact does not use
cookies, browser storage, service workers, downloads, popup windows, wallet
objects, or parent-frame access.

## Authoring tiny artwork apps

`artifact.template.html` is intentionally ordinary HTML rather than a framework
bundle. Add artwork-specific panels, text, gestures, or timed behavior there,
then rebuild; the result remains one file.

Inline code can drive the live engine through `window.EverythingArtifact`:

```javascript
EverythingArtifact.pause();
EverythingArtifact.setPhysics("sensor_angle", 0.62);
EverythingArtifact.setVisual("exposure", 0.88);
EverythingArtifact.variation();
EverythingArtifact.resume();
```

The API also exposes `reset()`, `toggle()`, and `snapshot()`. It is an in-page
authoring surface; it does not depend on access to the parent site and remains
available in a script-only opaque-origin iframe.

## GPU pass graph

Each simulation step preserves the canonical desktop order:

```text
pre-update particle brush
        |
        v
entity compute, sampling the current trail
        |
        v
five-tap trail resolve -> ping-pong trail target
        |
        v
current particle color render
        |
        v
temporal accumulation -> ping-pong accumulation target
        |
        v
brightness + asinh tone map -> canvas
```

The implementation keeps the 48-byte entity layout, the 320-byte ten-center
Fourier rule, saved-rule mutation, sensor behavior, parameter sweeps and
jitter, initialization modes, boundary modes, Gaussian deposition, diffusion,
coloring, and watercolor rendering.

The browser uses `rgba16float` intermediate targets for portable filtering and
blending. Trail and accumulation feedback are always explicit ping-pong passes;
this makes the browser behavior legal and deterministic instead of relying on
the same-texture OpenGL feedback used by parts of the desktop fast path.

The requested particle count is clamped against the adapter's actual storage
buffer limits. The normal artifact path does not allocate the desktop
per-particle rule readback buffer, which would exceed WebGPU's guaranteed
portable storage-binding limit at the full desktop count.

## Deliberate first-release boundary

This is the live art kernel, not a browser clone of the desktop editor. It
currently omits multi-load editing, advanced force/strafe field layers, camera
pan and zoom, tiling, emboss, bloom, desktop recording, shader hot reload,
filesystem operations, and Trial Dish game systems. Raw-linear temporal
accumulation is also used before final tone mapping, rather than reproducing
the desktop shader's tone-map/undo-tone-map feedback loop.

Those exclusions are explicit so future parity work can be measured instead
of hidden behind a broad "WebGPU port" label.

## networked.art publishing

The current networked.art flow accepts the generated `.html` as the artwork
and requires a separate static image thumbnail. Capture the square simulation
after it has evolved to the desired state. Append `?thumbnail=1` to align the
square simulation at the top-left and hide the interface for capture:

```text
http://127.0.0.1:8765/artifacts/networked-art/everything.html?thumbnail=1
```

Before upload:

1. Run `python scripts/smoke_webgpu_artifact.py --require-thumbnail`.
2. Run `python scripts/smoke_webgpu_responsive.py --skip-build`.
3. Serve the HTML through localhost and verify it starts without a GPU error.
4. Verify it inside an iframe with `sandbox="allow-scripts"`.
5. Test drag/touch, pause, reset, and a variation at the default site zoom.
6. Upload the HTML plus the separate thumbnail through the networked.art
   creation flow.

The artifact intentionally needs only `allow-scripts`. It does not rely on
same-origin privileges or any additional iframe permission.

Relevant current platform references:

- [networked.art creation guide](https://networked.art/help/creating-and-managing)
- [GPUWeb implementation status](https://github.com/gpuweb/gpuweb/wiki/Implementation-Status)
