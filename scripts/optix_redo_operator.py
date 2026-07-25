"""Queue local commands for a running Optix-Redo Fluoddity process."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
import uuid


def operator_root() -> Path:
    configured = os.environ.get("FLUODDITY_OPERATOR_DIR")
    if configured:
        return Path(configured)
    return Path.home() / "Documents" / "Fluoddity" / "OperatorRedo"


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
    parser.add_argument("--wait", type=float, default=0.0)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")

    action = sub.add_parser("action")
    action.add_argument("name")

    experiment = sub.add_parser("experiment")
    experiment.add_argument("path", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "status":
        path = operator_root() / "status.json"
        if not path.exists():
            print(f"no status heartbeat at {path}")
            return 1
        print(path.read_text(encoding="utf-8"))
        return 0

    if args.command == "action":
        command = {"actions": [args.name]}
    else:
        command = json.loads(args.path.read_text(encoding="utf-8"))
    receipt = queue_command(command, args.wait)
    return 0 if receipt is None or receipt.get("status") == "applied" else 1


if __name__ == "__main__":
    raise SystemExit(main())
