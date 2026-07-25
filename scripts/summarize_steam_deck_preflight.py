"""Summarize a filled Steam Deck preflight report into release-gate evidence."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "artifacts" / "steam_deck_preflight.md"
DEFAULT_OUTPUT = ROOT / "artifacts" / "steam_deck_preflight_summary.md"

REQUIRED_SECTIONS = {
    "Automated Gate Coverage",
    "Remaining External Gates",
    "Manual Deck Checks",
}

REQUIRED_NOTE_FIELDS = [
    "Hardware tester",
    "Device / OS build",
    "Steam launch target",
    "Average FPS observed over five minutes",
    "Lowest legibility issue found",
    "Input or suspend/resume defects",
]

NONE_ALLOWED_NOTE_FIELDS = {
    "Lowest legibility issue found",
    "Input or suspend/resume defects",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize a filled Steam Deck preflight report.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Filled preflight report path.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Summary output path.")
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Exit 2 unless the filled report proves the Deck preflight is release-ready.",
    )
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def section_name(line: str) -> str | None:
    if not line.startswith("## "):
        return None
    return line.removeprefix("## ").strip()


def parse_checkboxes(text: str) -> dict[str, list[tuple[bool, str]]]:
    sections: dict[str, list[tuple[bool, str]]] = {}
    current = ""
    for line in text.splitlines():
        maybe_section = section_name(line)
        if maybe_section is not None:
            current = maybe_section
            sections.setdefault(current, [])
            continue

        match = re.match(r"- \[([ xX])\] (.+)$", line)
        if not match or not current:
            continue
        checked = match.group(1).lower() == "x"
        label = match.group(2).strip()
        sections.setdefault(current, []).append((checked, label))
    return sections


def metadata_value(text: str, label: str) -> str:
    match = re.search(rf"^- {re.escape(label)}: (.*)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def note_field_ready(label: str, value: str) -> bool:
    if not value:
        return False
    if label in NONE_ALLOWED_NOTE_FIELDS:
        return bool(value.strip())
    return value.strip().lower() not in {"none", "n/a", "na"}


def summarize(text: str) -> tuple[str, list[str], dict[str, tuple[int, int]], str, dict[str, str]]:
    automated_status = metadata_value(text, "Automated status")
    checkboxes = parse_checkboxes(text)
    missing: list[str] = []
    counts: dict[str, tuple[int, int]] = {}
    notes = {label: metadata_value(text, label) for label in REQUIRED_NOTE_FIELDS}

    if automated_status != "passed":
        missing.append(f"Automated status is `{automated_status or 'missing'}`, not `passed`.")

    for label, value in notes.items():
        if not note_field_ready(label, value):
            missing.append(f"Notes: `{label}` is missing hardware-pass evidence.")

    for section in sorted(REQUIRED_SECTIONS):
        items = checkboxes.get(section, [])
        checked_count = sum(1 for checked, _ in items if checked)
        counts[section] = (checked_count, len(items))
        if not items:
            missing.append(f"`{section}` has no checkbox evidence.")
            continue
        for checked, label in items:
            if not checked:
                missing.append(f"{section}: {label}")

    status = "ready" if not missing else "not-ready"
    return status, missing, counts, automated_status, notes


def write_summary(output: Path, input_path: Path, text: str) -> tuple[Path, str]:
    output = resolve_path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    status, missing, counts, automated_status, notes = summarize(text)

    lines = [
        "# Steam Deck Preflight Summary",
        "",
        f"- Source: {input_path.relative_to(ROOT).as_posix() if input_path.is_relative_to(ROOT) else input_path}",
        f"- Status: {status}",
        f"- Automated status: {automated_status or 'missing'}",
        "",
        "## Coverage",
        "",
    ]
    for section in sorted(REQUIRED_SECTIONS):
        checked_count, total = counts.get(section, (0, 0))
        lines.append(f"- {section}: {checked_count}/{total}")
    lines.extend(["", "## Required Notes", ""])
    for label in REQUIRED_NOTE_FIELDS:
        value = notes.get(label, "")
        lines.append(f"- {label}: {value or '(missing)'}")
    lines.extend(["", "## Missing Evidence", ""])
    if missing:
        lines.extend(f"- {item}" for item in missing)
    else:
        lines.append("- None. All required preflight evidence is checked.")
    lines.append("")

    output.write_text("\n".join(lines), encoding="utf-8")
    return output, status


def main() -> int:
    args = parse_args()
    input_path = resolve_path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    output, status = write_summary(args.output, input_path, input_path.read_text(encoding="utf-8"))
    print(f"steam_deck_preflight_summary={output}")
    print(f"steam_deck_preflight_status={status}")
    if args.require_ready and status != "ready":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
