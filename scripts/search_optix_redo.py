"""Run a coarse Optix-Redo physics/geometry search and build a contact sheet."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import shutil
import time

from PIL import Image, ImageDraw, ImageOps

from optix_redo_operator import operator_root, queue_command


@dataclass(frozen=True)
class Candidate:
    label: str
    config: str
    cohorts: int
    mutation: float
    seed: float
    initialization: int
    gravity_force: float
    gravity_strafe: float
    curve_length: float
    curve_r0: float
    curve_r1: float


CANDIDATES = (
    Candidate("dragon-lattice", "00Dragon", 12, 0.010, 0.73, 0, 0.00, 0.00, 1.5, 0.45, 0.06),
    Candidate("dragon-vortex", "00Dragon", 20, 0.018, 0.31, 2, 0.16, -0.10, 2.2, 0.32, 0.035),
    Candidate("brain-reef", "00Brain3", 16, 0.012, 0.61, 3, -0.08, 0.12, 1.1, 0.58, 0.09),
    Candidate("bowl-tree", "00Bowl-Tree", 18, 0.008, 0.47, 0, 0.12, 0.00, 1.8, 0.42, 0.045),
    Candidate("coral-crown", "00Coral4", 24, 0.014, 0.83, 2, 0.10, 0.08, 1.4, 0.52, 0.055),
    Candidate("jelly-forest", "00JellySeaweed", 24, 0.016, 0.19, 3, -0.06, 0.16, 2.4, 0.28, 0.025),
    Candidate("octo-loom", "00Octoswirl3", 14, 0.009, 0.67, 2, 0.08, -0.14, 2.0, 0.38, 0.04),
    Candidate("shroom-cloud", "00Shroom2", 18, 0.012, 0.37, 1, -0.12, 0.06, 1.2, 0.62, 0.12),
    Candidate("spine-orbit", "00Spines", 20, 0.011, 0.79, 2, 0.18, 0.05, 2.6, 0.26, 0.02),
    Candidate("sunflower-dish", "00SunflowerBowl", 16, 0.010, 0.53, 0, 0.10, -0.06, 1.7, 0.46, 0.05),
    Candidate("web-current", "00Web", 28, 0.015, 0.29, 3, -0.05, 0.18, 2.8, 0.24, 0.018),
    Candidate("yarn-storm", "00Yarn", 22, 0.020, 0.71, 1, 0.14, -0.12, 3.0, 0.22, 0.015),
    Candidate("mitosis-ring", "00Mitosis", 18, 0.014, 0.43, 2, 0.05, 0.10, 1.0, 0.64, 0.11),
    Candidate("vacuole-tide", "00Vacuoles", 26, 0.013, 0.89, 3, -0.10, -0.08, 1.6, 0.48, 0.07),
    Candidate("worm-bloom", "00Worms2", 20, 0.017, 0.23, 0, 0.12, 0.14, 2.3, 0.30, 0.03),
    Candidate("tendril-saddle", "00Tenta", 24, 0.012, 0.59, 2, 0.06, -0.16, 2.5, 0.27, 0.022),
)


def command(*, settings: dict | None = None, actions: list | None = None,
            label: str = "", timeout: float = 30.0) -> None:
    payload: dict = {"version": 1}
    if settings:
        payload["set"] = settings
    if actions:
        payload["actions"] = actions
    if label:
        payload["label"] = label
    receipt = queue_command(payload, wait_seconds=timeout)
    if not receipt or receipt.get("status") != "applied":
        raise RuntimeError(f"operator rejected {label or payload}: {receipt}")


def wait_for_screenshot(prefix: str, started_at: float, timeout: float = 30.0) -> Path:
    status_path = operator_root() / "status.json"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if status_path.exists():
            status = json.loads(status_path.read_text(encoding="utf-8"))
            latest = status.get("artifacts", {}).get("latest_screenshot", "")
            if latest:
                path = Path(latest)
                if (path.exists() and path.stat().st_mtime >= started_at
                        and path.name.startswith(prefix)):
                    return path
        time.sleep(0.1)
    raise TimeoutError(f"screenshot for {prefix!r} did not finish")


def make_contact_sheet(results: list[dict], output: Path, columns: int = 4) -> None:
    thumb_w, thumb_h, label_h = 480, 270, 34
    rows = (len(results) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * thumb_w, rows * (thumb_h + label_h)), "#080b12")
    draw = ImageDraw.Draw(sheet)
    for index, result in enumerate(results):
        row, col = divmod(index, columns)
        x, y = col * thumb_w, row * (thumb_h + label_h)
        with Image.open(result["image"]) as source:
            thumb = ImageOps.fit(source.convert("RGB"), (thumb_w, thumb_h))
        sheet.paste(thumb, (x, y))
        candidate = result["candidate"]
        text = (f"{candidate['label']} | c{candidate['cohorts']} "
                f"m{candidate['mutation']:.3f} s{candidate['seed']:.2f}")
        draw.text((x + 8, y + thumb_h + 9), text, fill="#eef4ff")
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settle", type=float, default=4.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    for index, candidate in enumerate(CANDIDATES, 1):
        print(f"\n[{index}/{len(CANDIDATES)}] {candidate.label}", flush=True)
        command(
            actions=[
                {"name": "load_config", "filename": candidate.config,
                 "category": "Advanced"},
                "pause",
            ],
            label=f"load {candidate.label}",
        )
        time.sleep(0.25)
        command(
            settings={
                "sim": {
                    "num_cohorts": candidate.cohorts,
                    "MUTATION_SCALE": candidate.mutation,
                    "rule_seed": candidate.seed,
                    "initial_conditions": candidate.initialization,
                    "GRAVITY_FORCE": candidate.gravity_force,
                    "GRAVITY_STRAFE": candidate.gravity_strafe,
                },
                "preferences": {
                    "optix": {
                        "use_curves": True,
                        "curve_length": candidate.curve_length,
                        "curve_r0": candidate.curve_r0,
                        "curve_r1": candidate.curve_r1,
                    }
                },
            },
            actions=["reset", "resume"],
            label=f"evolve {candidate.label}",
        )
        time.sleep(args.settle)
        command(actions=["pause"], label=f"pause {candidate.label}")
        time.sleep(0.2)
        started_at = time.time() - 0.1
        command(
            actions=[{"name": "screenshot", "label": candidate.label,
                      "note": "Optix-Redo coarse parameter search"}],
            label=f"capture {candidate.label}",
        )
        source = wait_for_screenshot(candidate.label, started_at)
        destination = args.output / f"{candidate.label}.png"
        shutil.copy2(source, destination)
        result = {"candidate": asdict(candidate), "image": str(destination),
                  "source": str(source)}
        results.append(result)
        print(destination, flush=True)

    index_path = args.output / "index.json"
    index_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    contact_sheet = args.output / "contact-sheet.png"
    make_contact_sheet(results, contact_sheet)
    print(f"\nIndex: {index_path}")
    print(f"Contact sheet: {contact_sheet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
