"""Prove Trial Dish resets restore the actual pre-irradiation strain."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from command_handler import CommandHandler
from services.rule_manager import RuleManager
from services.trial_service import TrialService
from state import TrialState


class FakeSim:
    def __init__(self) -> None:
        self.applied_rules: list[np.ndarray] = []

    def apply_rule(self, rule: np.ndarray) -> None:
        self.applied_rules.append(rule.copy())


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def make_handler(sim: FakeSim, rules: RuleManager) -> CommandHandler:
    inert = SimpleNamespace()
    return CommandHandler(
        sim,
        inert,
        inert,
        rules,
        inert,
        inert,
        inert,
        inert,
        None,
    )


def main() -> int:
    baseline_rule = np.arange(80, dtype=np.float32).reshape(10, 8)
    baseline_seed = 0.125
    rules = RuleManager()
    rules.push_rule(baseline_rule.copy(), baseline_seed)
    sim = FakeSim()
    handler = make_handler(sim, rules)

    trial = TrialState(game_mode=True)
    trials = TrialService()
    trials.load_trial(trial, 2)
    trials.start_trial(trial)
    ui_state = SimpleNamespace(
        trial=trial,
        sim=SimpleNamespace(rule_seed=baseline_seed),
        request_trial_next=False,
        request_trial_restart_sequence=False,
        request_trial_retry=False,
        request_reset=False,
        request_full_reset=False,
        request_trial_start=False,
        request_trial_pause=False,
        request_revert_strain=False,
        request_randomize_mutations=False,
    )

    handler._handle_randomize_mutations(ui_state)
    first_mutated_seed = ui_state.sim.rule_seed
    require(first_mutated_seed != baseline_seed, "irradiation should choose a new seed")
    require(rules.length() == 2, "irradiation should add a reversible history entry")

    handler._handle_randomize_mutations(ui_state)
    require(rules.length() == 3, "a second irradiation should add another history entry")
    trials.retry_trial(trial)
    require(trial.mutation_readout == "Baseline strain", "retry UI should return to baseline")
    require(handler.restore_trial_strain_baseline(ui_state), "retry should restore an archived baseline")
    require(rules.length() == 1, "retry should discard all irradiation history")
    require(ui_state.sim.rule_seed == baseline_seed, "retry should restore the baseline seed")
    require(np.array_equal(rules.get_current_rule(), baseline_rule), "history should end at baseline rule")
    require(np.array_equal(sim.applied_rules[-1], baseline_rule), "GPU rule should be restored to baseline")
    require(not handler.restore_trial_strain_baseline(ui_state), "baseline restore should be one-shot")

    handler._handle_randomize_mutations(ui_state)
    handler._handle_revert_strain(ui_state)
    require(rules.length() == 1, "Revert should restore the prior strain in history")
    trials.restart_sequence(trial)
    require(handler.restore_trial_strain_baseline(ui_state), "sequence restart should close the mutation session")
    require(ui_state.sim.rule_seed == baseline_seed, "restart should preserve the original baseline seed")
    require(np.array_equal(sim.applied_rules[-1], baseline_rule), "restart should keep the baseline GPU rule")

    trial.game_mode = True
    trials.load_trial(trial, 2)
    trials.start_trial(trial)
    ui_state.request_trial_retry = True
    ui_state.request_randomize_mutations = True
    ui_state.request_revert_strain = True
    trials.process_requests(trial, ui_state)
    require(trial.mutation_readout == "Baseline strain", "retry should leave baseline UI state")
    require(not ui_state.request_randomize_mutations, "retry should consume simultaneous irradiation")
    require(not ui_state.request_revert_strain, "retry should consume simultaneous revert")
    require(rules.length() == 1, "consumed retry tools should not change rule history")
    ui_state.request_trial_retry = False

    ui_state.request_reset = True
    ui_state.request_randomize_mutations = True
    trials.process_requests(trial, ui_state)
    require(not ui_state.request_randomize_mutations, "sterilize should consume simultaneous irradiation")
    require(rules.length() == 1, "consumed sterilize tool should not change rule history")

    capped_rules = RuleManager()
    for index in range(200):
        capped_rules.push_rule(np.full((10, 8), index, dtype=np.float32), index / 1000)
    capped_sim = FakeSim()
    capped_handler = make_handler(capped_sim, capped_rules)
    capped_trial = TrialState(game_mode=True)
    trials.load_trial(capped_trial, 2)
    trials.start_trial(capped_trial)
    capped_ui = SimpleNamespace(
        trial=capped_trial,
        sim=SimpleNamespace(rule_seed=capped_rules.get_current_seed()),
    )
    before_history = capped_rules.snapshot_history()
    capped_handler._handle_randomize_mutations(capped_ui)
    capped_handler._handle_randomize_mutations(capped_ui)
    require(capped_rules.length() == 200, "bounded history should remain capped during irradiation")
    require(capped_handler.restore_trial_strain_baseline(capped_ui), "capped history should restore")
    after_history = capped_rules.snapshot_history()
    require(len(after_history) == len(before_history), "restore should recover full capped history")
    require(
        all(
            before_seed == after_seed and np.array_equal(before_rule, after_rule)
            for (before_rule, before_seed), (after_rule, after_seed) in zip(before_history, after_history)
        ),
        "restore should recover the exact pre-irradiation history snapshot",
    )

    print("trial_strain_reset_smoke=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
