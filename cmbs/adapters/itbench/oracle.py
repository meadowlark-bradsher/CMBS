"""
Deterministic oracle for ITBench kits.
"""

from __future__ import annotations

from .kit import ITBenchKit


class ITBenchOracle:
    def __init__(self, kit: ITBenchKit, scenario: dict[str, str]):
        self._kit = kit
        self._scenario = dict(scenario)

    def answer(self, action_id: str) -> str:
        if action_id not in self._scenario:
            raise KeyError(f"No outcome specified for action '{action_id}'.")
        outcome = self._scenario[action_id]
        if outcome not in self._kit.actions[action_id].outcomes:
            raise ValueError(f"Invalid outcome '{outcome}' for action '{action_id}'.")
        return outcome
