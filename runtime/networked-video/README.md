# Self-contained video artifact

`scripts/export_networked_html.py` packages a rendered video and poster into a
single HTML artwork without network requests. It is a fallback/presentation
surface for prerecorded work, separate from the live WebGPU simulation in
`runtime/webgpu/`.

The standalone artifact supports pointer or touch scrubbing, vertical playback
speed control, tap/Space pause, arrow-key stepping, and restart with `R` or `0`.
The optional fragment form is intended for embedding into a page that already
provides shared button and screen-reader utility styles.

```powershell
python scripts/export_networked_html.py `
  --video artifacts/example.mp4 `
  --poster artifacts/example.png `
  --output artifacts/example.html `
  --manifest artifacts/example.manifest.json `
  --title "Fluoddity"
```

The exporter rejects output above its byte limit (95 MB by default), writes
atomically, and records source/output hashes in the optional manifest. It does
not convert or validate video codecs; prepare a browser-compatible source
before packaging.

Run its contract smoke with:

```powershell
python scripts/smoke_networked_video_artifact.py
```
