# 3D gravity iteration evidence

This directory preserves the durable review record for the native 3D gravity
experiments captured on July 19, 2026. The disposable MP4 renders were removed
after review; they are not required to inspect or build Fluoddity.

- `catalog.json` records all 48 reviewed capture attempts, including byte
  counts, preset names, deterministic gravity values, quality decisions, visual
  notes, and the sanitized membership of the full, curated, and stretched
  review lists. It retains 46 reviewed captures and marks the near-empty
  Beholder and Inky attempts as rejected.
- `contact-sheet.png` visually preserves the first 17-capture series. It is a
  review artifact, not a runtime asset.
- `scripts/build_3d_iteration_catalog.py` can scan a new capture directory or
  normalize an older v1 catalog. CLI paths may be absolute when supplied by the
  caller, but defaults and stored provenance paths are repository-relative.
- `scripts/render_unique_iterations.ps1` performs fresh, seeded native launches,
  varies gravity through the documented seven-value sequence, and restores the
  default physics config, preferences, and `sim.py` bytes when it exits.

The catalog's `path_before_archive` fields are provenance identifiers for the
deleted MP4s. They intentionally do not point to files retained in Git.

To build a catalog from fresh captures:

```powershell
python scripts/build_3d_iteration_catalog.py `
  --capture-dir artifacts/unique_iterations
```

To normalize an earlier catalog without retaining machine-specific paths:

```powershell
python scripts/build_3d_iteration_catalog.py `
  --source-catalog path/to/3d_iteration_catalog.json `
  --capture-list full_reviewed=path/to/full-reviewed-list.txt
```
