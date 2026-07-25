"""Queue commands for a running Fluoddity stream workstation."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
import uuid


def operator_root() -> Path:
    return Path.home() / "Documents" / "Fluoddity" / "Operator"


def parse_value(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def queue_command(command: dict, wait_seconds: float = 0.0) -> dict | None:
    root = operator_root()
    inbox = root / "inbox"
    receipts = root / "receipts"
    inbox.mkdir(parents=True, exist_ok=True)
    receipts.mkdir(parents=True, exist_ok=True)
    command_id = command.setdefault("id", uuid.uuid4().hex)
    command.setdefault("version", 1)
    command.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    destination = inbox / f"{command_id}.json"
    temporary = inbox / f".{command_id}.{os.getpid()}.tmp"
    temporary.write_text(json.dumps(command, indent=2), encoding="utf-8")
    os.replace(temporary, destination)
    print(f"queued {command_id}: {destination}")

    if wait_seconds <= 0:
        return None
    receipt_path = receipts / f"{command_id}.json"
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if receipt_path.exists():
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            print(json.dumps(receipt, indent=2))
            return receipt
        time.sleep(0.1)
    raise TimeoutError(f"no receipt after {wait_seconds:g}s; is Fluoddity running?")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wait", type=float, default=0.0, help="wait for an application receipt")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="print the latest runtime heartbeat")
    sub.add_parser("schema", help="print the machine-readable control schema")

    action = sub.add_parser("action", help="queue a named action")
    action.add_argument("name")

    setting = sub.add_parser("set", help="set one dataclass field")
    setting.add_argument("section", choices=("sim", "camera", "preferences", "controller"))
    setting.add_argument("field")
    setting.add_argument("value", help="JSON value or plain string")

    capture = sub.add_parser("capture", help="request a labeled high-quality screenshot")
    capture.add_argument("label")
    capture.add_argument("--note", default="")

    marker = sub.add_parser("mark", help="mark an interesting stream moment")
    marker.add_argument("label")
    marker.add_argument("--note", default="")

    load = sub.add_parser("load", help="load a saved physics configuration")
    load.add_argument("filename")
    load.add_argument("--category", choices=("Core", "Advanced", "Custom"), default="")

    experiment = sub.add_parser("experiment", help="queue a complete JSON command document")
    experiment.add_argument("path", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command in ("status", "schema"):
        path = operator_root() / f"{args.command}.json"
        if not path.exists():
            print(f"no status heartbeat at {path}")
            return 1
        print(path.read_text(encoding="utf-8"))
        return 0

    if args.command == "action":
        command = {"actions": [args.name]}
    elif args.command == "set":
        command = {"set": {args.section: {args.field: parse_value(args.value)}}}
    elif args.command == "capture":
        command = {"actions": [{"name": "screenshot", "label": args.label, "note": args.note}]}
    elif args.command == "mark":
        command = {"actions": [{"name": "mark", "label": args.label, "note": args.note}]}
    elif args.command == "load":
        command = {"actions": [{"name": "load_config", "filename": args.filename, "category": args.category}]}
    else:
        command = json.loads(args.path.read_text(encoding="utf-8"))

    receipt = queue_command(command, args.wait)
    return 0 if receipt is None or receipt.get("status") == "applied" else 1


if __name__ == "__main__":
    raise SystemExit(main())
