"""Smoke-check the V1 umbrella smoke interpreter dependency guard."""
from __future__ import annotations

import sys

import smoke_game_v1


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    original_imports = smoke_game_v1.DEPENDENCY_IMPORTS
    try:
        smoke_game_v1.DEPENDENCY_IMPORTS = [
            ("MissingProbePackage", "fluoddity_missing_dependency_probe"),
        ]
        try:
            smoke_game_v1.check_python_dependencies(sys.executable)
        except SystemExit as exc:
            message = str(exc)
        else:
            raise AssertionError("dependency guard should exit for a missing probe module")
    finally:
        smoke_game_v1.DEPENDENCY_IMPORTS = original_imports

    require("Selected smoke interpreter is missing MissingProbePackage" in message, "missing dependency should be named")
    require(sys.executable in message, "selected interpreter path should be reported")
    require("smoke_game_v1.py --python" in message or "pip install -r requirements.txt" in message, "message should include recovery hint")
    print("game_v1_dependency_guard_smoke=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
