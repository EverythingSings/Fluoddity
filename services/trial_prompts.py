"""Game-facing Trial Dish input prompt labels.

The public string helper is intentionally backed by structured prompt data so
future Steam Input glyph rendering can use action ids instead of parsing text.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_KEYBOARD_LABELS = {
    "game_confirm": "Enter",
    "game_retry": "Backspace",
    "game_next": "N",
    "game_tool": "G",
    "game_revert": "C",
    "game_pause": "Esc",
    "game_exit": "Q",
}

CONTROLLER_LABELS = {
    "game_confirm": "A",
    "game_retry": "B",
    "game_tool": "Y",
    "game_revert": "L1",
    "game_pause": "Menu",
    "game_exit": "View",
}

STEAM_INPUT_ACTIONS = {
    "game_confirm": "StartExperiment",
    "game_retry": "RetryTrial",
    "game_next": "NextTrial",
    "game_tool": "IrradiateStrain",
    "game_revert": "RevertStrain",
    "game_pause": "PauseExperiment",
    "game_exit": "ExitExperiment",
    "nutrient_aim": "AimNutrientGel",
    "nutrient_apply": "ApplyNutrientGel",
}


GLYPH_MAP_PATH = Path(__file__).resolve().parents[1] / "steam_input" / "trial_prompt_glyph_map.json"


@dataclass(frozen=True)
class PromptGlyph:
    """Fallback controller label plus future Steam Input glyph asset id."""

    action: str
    fallback_label: str
    glyph_asset: str


@dataclass(frozen=True)
class TrialPrompt:
    """Structured prompt data for both text labels and future glyph rendering."""

    label: str
    input_scheme: str
    controller_labels: tuple[str, ...] = ()
    keyboard_labels: tuple[str, ...] = ()
    steam_input_actions: tuple[str, ...] = field(default_factory=tuple)
    glyph_assets: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_controller_glyphs(self) -> bool:
        return bool(self.controller_labels and self.glyph_assets)

    def render_controller_glyph_text(self) -> str:
        if not self.has_controller_glyphs:
            return ""
        return " + ".join(f"[{label}]" for label in self.controller_labels)

    def render_input_text(self) -> str:
        if self.input_scheme == "controller":
            return " + ".join(self.controller_labels)
        if self.input_scheme == "keyboard_mouse":
            return " + ".join(self.keyboard_labels)
        if self.controller_labels and self.keyboard_labels:
            return (
                f"{' + '.join(self.controller_labels)} / "
                f"{' + '.join(self.keyboard_labels)}"
            )
        if self.controller_labels:
            return " + ".join(self.controller_labels)
        return " + ".join(self.keyboard_labels)

    def render_text(self) -> str:
        input_text = self.render_input_text()
        if input_text:
            return f"{input_text}: {self.label}"
        return self.label

    def render_display_text(self) -> str:
        """Return text matching the HUD's glyph-chip fallback presentation."""
        if self.input_scheme == "keyboard_mouse" or not self.has_controller_glyphs:
            return self.render_text()

        input_text = self.render_controller_glyph_text()
        if self.input_scheme == "hybrid" and self.keyboard_labels:
            input_text = f"{input_text} / {' + '.join(self.keyboard_labels)}"
        if input_text:
            return f"{input_text}: {self.label}"
        return self.label


def _keyboard_label(keybindings, action: str) -> str:
    if keybindings is None:
        return DEFAULT_KEYBOARD_LABELS.get(action, "?")

    label = keybindings.get_key_display_name(action)
    if not label or label == "?":
        return DEFAULT_KEYBOARD_LABELS.get(action, "?")

    return label.title() if len(label) > 1 else label.upper()


def load_trial_prompt_glyphs(path: Path = GLYPH_MAP_PATH) -> dict[str, PromptGlyph]:
    """Load prompt glyph metadata from the packaged Steam Input glyph map."""
    if not path.exists():
        return {}

    data = json.loads(path.read_text(encoding="utf-8"))
    actions = data.get("actions", {})
    glyphs: dict[str, PromptGlyph] = {}
    for action, entry in actions.items():
        fallback = str(entry.get("fallback_label", "")).strip()
        asset = str(entry.get("glyph_asset", "")).strip()
        if not fallback or not asset:
            continue
        glyphs[action] = PromptGlyph(action, fallback, asset)
    return glyphs


TRIAL_PROMPT_GLYPHS = load_trial_prompt_glyphs()


def _glyph_assets(actions: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        TRIAL_PROMPT_GLYPHS[action].glyph_asset
        for action in actions
        if action in TRIAL_PROMPT_GLYPHS
    )


def _button_prompt(controller_label: str, keybindings, action: str, text: str, input_scheme: str) -> TrialPrompt:
    keyboard = _keyboard_label(keybindings, action)
    steam_actions = (STEAM_INPUT_ACTIONS[action],)
    return TrialPrompt(
        label=text,
        input_scheme=input_scheme,
        controller_labels=(controller_label,),
        keyboard_labels=(keyboard,),
        steam_input_actions=steam_actions,
        glyph_assets=_glyph_assets(steam_actions),
    )


def nutrient_prompt(input_scheme: str) -> TrialPrompt:
    steam_actions = (
        STEAM_INPUT_ACTIONS["nutrient_aim"],
        STEAM_INPUT_ACTIONS["nutrient_apply"],
    )
    if input_scheme == "controller":
        return TrialPrompt(
            label="Nutrient Gel",
            input_scheme=input_scheme,
            controller_labels=("Right Stick", "R2"),
            steam_input_actions=steam_actions,
            glyph_assets=_glyph_assets(steam_actions),
        )
    if input_scheme == "keyboard_mouse":
        return TrialPrompt(
            label="Nutrient Gel",
            input_scheme=input_scheme,
            keyboard_labels=("Mouse / Touch",),
        )
    return TrialPrompt(
        label="Nutrient Gel",
        input_scheme=input_scheme,
        controller_labels=("Right Stick", "R2"),
        keyboard_labels=("Mouse / Touch",),
        steam_input_actions=steam_actions,
        glyph_assets=_glyph_assets(steam_actions),
    )


def trial_action_prompt_specs(trial, keybindings=None, input_scheme: str = "hybrid") -> list[TrialPrompt]:
    """Return structured prompts for the current game state and active input scheme."""
    if input_scheme not in {"hybrid", "controller", "keyboard_mouse"}:
        input_scheme = "hybrid"

    confirm = lambda text: _button_prompt("A", keybindings, "game_confirm", text, input_scheme)
    retry = lambda text: _button_prompt("B", keybindings, "game_retry", text, input_scheme)
    tool = lambda text: _button_prompt("Y", keybindings, "game_tool", text, input_scheme)
    revert = lambda text: _button_prompt("L1", keybindings, "game_revert", text, input_scheme)
    pause = lambda text: _button_prompt("Menu", keybindings, "game_pause", text, input_scheme)
    exit_ = lambda text: _button_prompt("View", keybindings, "game_exit", text, input_scheme)

    if trial.briefing_active:
        return [confirm("Start")]

    if trial.won:
        primary = confirm("Restart" if trial.final_trial else "Next")
        return [primary, retry("Retry")]

    if trial.failed:
        return [confirm("Retry")]

    if trial.paused:
        return [pause("Resume"), retry("Retry"), exit_("Exit")]

    hints = [nutrient_prompt(input_scheme)]
    if trial.irradiation_unlocked:
        if trial.irradiation_ready:
            hints.append(tool("Irradiate"))
        elif trial.irradiation_charges <= 0:
            hints.append(tool("Depleted"))
        elif trial.irradiation_cooldown_remaining > 0.0:
            hints.append(tool(f"Recharge {trial.irradiation_cooldown_remaining:.0f}s"))
    if trial.revert_unlocked:
        if trial.revert_ready:
            hints.append(revert("Revert"))
        elif trial.revert_charges <= 0:
            hints.append(revert("Spent"))
        else:
            hints.append(revert("No Archive"))
    hints.append(retry("Retry"))
    hints.append(pause("Pause"))
    return hints


def trial_action_hints(trial, keybindings=None, input_scheme: str = "hybrid") -> list[str]:
    """Return compact text prompts for the current game state and active input scheme."""
    return [
        prompt.render_text()
        for prompt in trial_action_prompt_specs(trial, keybindings, input_scheme)
    ]
