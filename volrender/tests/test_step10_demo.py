"""Tests for volrender Step 10 — Example harness & integration (capstone).

This step is an end-to-end acceptance test run manually via the interactive
demo.  There is no automated test runner.  The human operator follows the
checklist below.

Run the demo:
    python -m volrender.example.demo

==========================================================================
ACCEPTANCE CHECKLIST
==========================================================================

(a) Window opens, initial render completes
    - A GLFW window appears (1280x720) titled "Volrender Demo".
    - The terminal prints "Rendering 64 spp..." then "Render complete."
    - The viewport shows a self-shadowed volumetric cloud (two overlapping
      gaussian blobs) lit by a directional sun with visible scattering and
      colored absorption.  The sky is visible around the cloud.
    - PASS if: a recognizable 3D cloud is displayed with shading & shadows.
    - FAIL if: black screen, NaN artifacts (white/magenta pixels), or crash.

(b) Camera orbit
    - Left-click and drag in the viewport (outside imgui panels) to orbit.
    - Scroll to zoom in/out.
    - The tonemapped image does NOT update during orbit (stale view).
    - Click "Re-render" → the new viewpoint renders correctly.
    - PASS if: orbit is smooth, re-render matches new camera angle.

(c) Sun direction tracks shadows
    - In the Sun section, drag the Direction sliders to change the sun angle
      (e.g., set to (-1, 0.5, 0) then (1, 0.5, 0)).
    - Click "Re-render" after each change.
    - PASS if: the lit side and shadow side of the cloud clearly shift with
      the sun direction.

(d) Colored extinction / smoke look
    - Set Extinction RGB to a reddish-orange (e.g. R≈1.5, G≈0.4, B≈0.2 via
      the color picker or by direct input).
    - Set Albedo RGB to low values (e.g. 0.3, 0.3, 0.3).
    - Click "Re-render".
    - PASS if: the cloud takes on a saturated smoky look with warm tones and
      colored self-shadowing.

(e) Points overlay alignment
    - Check "Show Points Overlay".
    - The GL_POINTS rendering of the entity buffer appears overlaid on the
      path-traced image.
    - PASS if: the point cloud silhouette aligns with the volume silhouette
      under the same camera (both use the same view_proj).

(f) Convergence with more samples
    - Set Samples (SPP) to 4, click "Re-render" → noisy image.
    - Set Samples (SPP) to 256, click "Re-render" → much cleaner image.
    - PASS if: noise visibly decreases with more samples, no fireflies or
      systematic bias.

(g) Medium/sun edits without re-splat
    - After the initial render, change medium or sun params and re-render.
    - The terminal should NOT print "Splatting entities..." (only on startup).
    - Confirm different params produce visually different images.
    - PASS if: re-renders with different params succeed without re-splatting.

(h) Save PNG
    - Click "Save PNG".
    - A file "volrender_output.png" appears in the project root.
    - Open it — it should match the tonemapped viewport.
    - PASS if: PNG is a valid, correctly tonemapped image (not all black,
      not all white, no obvious artifacts).

(i) No NaN / no crash
    - Throughout all the above tests, observe:
      - No NaN artifacts (bright white/magenta pixels that don't converge).
      - No GPU crash or TDR timeout.
      - No Python exceptions in the terminal.
    - PASS if: stable throughout.

==========================================================================
"""
