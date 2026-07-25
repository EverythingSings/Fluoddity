"""Summarize a filled package/runtime validation report into release-gate evidence."""
from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "artifacts" / "package_validation.md"
DEFAULT_OUTPUT = ROOT / "artifacts" / "package_validation_summary.md"

REQUIRED_SECTIONS = {
    "Package Build",
    "Launch Validation",
    "Native Video Export",
    "Native wgpu Package",
    "Runtime Compatibility",
}

REQUIRED_NOTE_FIELDS = [
    "Tester",
    "Device / OS build",
    "Build / commit",
    "Package path",
    "Runtime path",
    "Steam launch target",
    "Package build host",
    "Package target",
    "GPU adapter",
    "wgpu backend",
    "Video evidence host",
    "Actual Steam Deck hardware used (yes/no)",
    "Average FPS observed over five minutes",
    "Runtime defects",
]

NONE_ALLOWED_NOTE_FIELDS = {
    "Runtime defects",
}

VALID_RUNTIME_VALUES = {
    "native linux",
    "linux",
    "windows-through-proton",
    "windows through proton",
    "proton",
}

VALID_PACKAGE_TARGET_VALUES = {
    "native linux",
    "linux",
    "windows",
    "windows/proton",
    "windows-through-proton",
    "windows through proton",
    "proton",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize a filled package/runtime validation report.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Filled package validation report path.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Summary output path.")
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Exit 2 unless package/runtime validation evidence is complete.",
    )
    parser.add_argument("--expected-build", default="", help="Expected packet build identity.")
    parser.add_argument("--expected-tester", default="", help="Expected tester when supplied by the packet.")
    parser.add_argument("--expected-device", default="", help="Expected device when supplied by the packet.")
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


def runtime_path_ready(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized in VALID_RUNTIME_VALUES


def package_target_ready(value: str) -> bool:
    return value.strip().lower() in VALID_PACKAGE_TARGET_VALUES


def summarize(
    text: str,
    *,
    expected_build: str = "",
    expected_tester: str = "",
    expected_device: str = "",
) -> tuple[str, list[str], dict[str, tuple[int, int]], dict[str, str]]:
    checkboxes = parse_checkboxes(text)
    missing: list[str] = []
    counts: dict[str, tuple[int, int]] = {}
    notes = {label: metadata_value(text, label) for label in REQUIRED_NOTE_FIELDS}

    for label, value in notes.items():
        if not note_field_ready(label, value):
            missing.append(f"Notes: `{label}` is missing package/runtime evidence.")
    for label, expected in (
        ("Build / commit", expected_build),
        ("Tester", expected_tester),
        ("Device / OS build", expected_device),
    ):
        if expected and notes.get(label, "") != expected:
            missing.append(
                f"Notes: `{label}` does not match this packet "
                f"(expected `{expected}`, found `{notes.get(label) or '(missing)'}`)."
            )

    runtime_path = notes.get("Runtime path", "")
    if runtime_path and not runtime_path_ready(runtime_path):
        missing.append("Notes: `Runtime path` must be `native Linux` or `Windows-through-Proton`.")

    package_target = notes.get("Package target", "")
    if package_target and not package_target_ready(package_target):
        missing.append(
            "Notes: `Package target` must identify Windows, native Linux, or Windows-through-Proton."
        )

    deck_hardware = notes.get("Actual Steam Deck hardware used (yes/no)", "").strip().lower()
    if deck_hardware and deck_hardware not in {"yes", "no"}:
        missing.append("Notes: `Actual Steam Deck hardware used (yes/no)` must be `yes` or `no`.")

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


def write_summary(
    output: Path,
    input_path: Path,
    text: str,
    *,
    expected_build: str = "",
    expected_tester: str = "",
    expected_device: str = "",
) -> tuple[Path, str]:
    output = resolve_path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    status, missing, counts, notes = summarize(
        text,
        expected_build=expected_build,
        expected_tester=expected_tester,
        expected_device=expected_device,
    )
    source = input_path.relative_to(ROOT).as_posix() if input_path.is_relative_to(ROOT) else str(input_path)

    lines = [
        "# Package Runtime Validation Summary",
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
        lines.append("- None. Package/runtime validation evidence is complete.")
    lines.append("")

    output.write_text("\n".join(lines), encoding="utf-8")
    return output, status


def main() -> int:
    args = parse_args()
    input_path = resolve_path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    output, status = write_summary(
        args.output,
        input_path,
        input_path.read_text(encoding="utf-8"),
        expected_build=args.expected_build,
        expected_tester=args.expected_tester,
        expected_device=args.expected_device,
    )
    print(f"package_validation_summary={output}")
    print(f"package_validation_status={status}")
    if args.require_ready and status != "ready":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
