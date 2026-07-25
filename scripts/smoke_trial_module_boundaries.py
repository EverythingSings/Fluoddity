"""Smoke-check Trial Dish module ownership boundaries."""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICES_INIT = ROOT / "services" / "__init__.py"
TRIAL_SERVICE = ROOT / "services" / "trial_service.py"
TRIAL_DEFINITIONS = ROOT / "services" / "trial_definitions.py"

EAGER_SERVICE_IMPORT_ALLOWLIST = {
    "__future__",
    "game_identity",
    "trial_definitions",
}

AUTHORING_CONSUMERS = [
    ROOT / "scripts" / "smoke_trial_definitions.py",
    ROOT / "scripts" / "smoke_trial_dishes.py",
    ROOT / "scripts" / "smoke_trial_dish_tuning_reference.py",
    ROOT / "scripts" / "write_trial_dish_tuning_reference.py",
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def imports_from(path: Path) -> list[tuple[str, list[str]]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[tuple[str, list[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imports.append((module, [alias.name for alias in node.names]))
    return imports


def has_assignment(path: Path, name: str) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return True
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            return True
    return False


def has_function(path: Path, name: str) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return any(isinstance(node, ast.FunctionDef) and node.name == name for node in ast.walk(tree))


def main() -> int:
    require(TRIAL_DEFINITIONS.exists(), "authored Trial Dish data should live in services/trial_definitions.py")
    require(has_assignment(TRIAL_DEFINITIONS, "TRIAL_DEFINITIONS"), "trial_definitions should define TRIAL_DEFINITIONS")
    require(not has_assignment(TRIAL_SERVICE, "TRIAL_DEFINITIONS"), "trial_service should not define authored trial data")
    require(has_function(SERVICES_INIT, "__getattr__"), "services package exports should lazy-load heavy services")

    eager_service_imports = [
        module
        for module, _ in imports_from(SERVICES_INIT)
        if module not in EAGER_SERVICE_IMPORT_ALLOWLIST
    ]
    require(
        not eager_service_imports,
        f"services/__init__.py should not eagerly import heavy services: {', '.join(eager_service_imports)}",
    )

    service_imports = imports_from(TRIAL_SERVICE)
    require(
        any(module == "trial_definitions" and "TRIAL_DEFINITIONS" in names for module, names in service_imports),
        "trial_service should import definitions from .trial_definitions",
    )

    for path in AUTHORING_CONSUMERS:
        imports = imports_from(path)
        require(
            any(
                module in {"services.trial_definitions", "trial_definitions"}
                and "TRIAL_DEFINITIONS" in names
                for module, names in imports
            ),
            f"{path.relative_to(ROOT).as_posix()} should import TRIAL_DEFINITIONS from services.trial_definitions",
        )
        require(
            not any(module == "services.trial_service" and "TRIAL_DEFINITIONS" in names for module, names in imports),
            f"{path.relative_to(ROOT).as_posix()} should not import authored data from trial_service",
        )

    print("trial_module_boundary_smoke=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
