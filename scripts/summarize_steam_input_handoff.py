"""Summarize a filled Steam Input handoff report into release-gate evidence."""
from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "artifacts" / "steam_input_handoff.md"
DEFAULT_OUTPUT = ROOT / "artifacts" / "steam_input_handoff_summary.md"

REQUIRED_SECTIONS = {
    "Manual Verification",
    "Known External Gates",
}

REQUIRED_NOTE_FIELDS = [
    "Steamworks app / branch",
    "Imported manifest version",
    "Default configuration name",
    "Glyph rendering path",
    "Tester / device",
    "Defects or remaps",
]

NONE_ALLOWED_NOTE_FIELDS = {
    "Defects or remaps",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize a filled Steam Input handoff report.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Filled Steam Input handoff path.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Summary output path.")
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Exit 2 unless the filled handoff proves Steam Input is ready.",
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
        sections.setdefault(current, []).append((match.group(1).lower() == "x", match.group(2).strip()))
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


def summarize(text: str) -> tuple[str, list[str], dict[str, tuple[int, int]], dict[str, str]]:
    checkboxes = parse_checkboxes(text)
    missing: list[str] = []
    counts: dict[str, tuple[int, int]] = {}
    notes = {label: metadata_value(text, label) for label in REQUIRED_NOTE_FIELDS}

    for label, value in notes.items():
        if not note_field_ready(label, value):
            missing.append(f"Import Notes: `{label}` is missing Steam Input evidence.")

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
    return status, missing, counts, notes


def write_summary(output: Path, input_path: Path, text: str) -> tuple[Path, str]:
    output = resolve_path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    status, missing, counts, notes = summarize(text)
    source = input_path.relative_to(ROOT).as_posix() if input_path.is_relative_to(ROOT) else str(input_path)

    lines = [
        "# Steam Input Handoff Summary",
        "",
        f"- Source: {source}",
        f"- Status: {status}",
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
        lines.append("- None. Steam Input handoff evidence is complete.")
    lines.append("")

    output.write_text("\n".join(lines), encoding="utf-8")
    return output, status


def main() -> int:
    args = parse_args()
    input_path = resolve_path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    output, status = write_summary(args.output, input_path, input_path.read_text(encoding="utf-8"))
    print(f"steam_input_handoff_summary={output}")
    print(f"steam_input_handoff_status={status}")
    if args.require_ready and status != "ready":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
