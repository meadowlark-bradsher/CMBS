"""
ITBench adapter.
"""

from __future__ import annotations

from typing import Any

from ..types import Action, AdapterActionContext, BeliefMessage, EliminateMessage
from .kit import ITBenchKit


class ITBenchAdapter:
    def __init__(self, kit: ITBenchKit, source_id: str = "adapter://itbench"):
        self._kit = kit
        self._source_id = source_id
        self._asked: set[str] = set()

    def list_actions(self, snapshot) -> list[Action]:
        actions: list[Action] = []
        survivors = set(snapshot.survivors)
        for action_id in self._kit.actions_order:
            if action_id in self._asked:
                continue
            spec = self._kit.actions[action_id]
            if _is_noop(self._kit.oracle_table, action_id, survivors):
                continue
            actions.append(
                Action(
                    action_id=action_id,
                    prompt=spec.description,
                    metadata={"description": spec.description, "outcomes": spec.outcomes},
                )
            )
        return actions

    def apply_action(self, action_id: str, snapshot) -> AdapterActionContext:
        spec = self._kit.actions[action_id]
        self._asked.add(action_id)
        return AdapterActionContext(
            action_id=action_id,
            snapshot=snapshot,
            payload={"description": spec.description, "outcomes": spec.outcomes},
        )

    def observe(
        self,
        action_ctx: AdapterActionContext,
        raw_observation: Any,
    ) -> list[BeliefMessage]:
        outcome = _normalize_outcome(raw_observation)
        spec = self._kit.actions[action_ctx.action_id]
        if outcome not in spec.outcomes:
            raise ValueError(f"Outcome '{outcome}' not valid for action '{action_ctx.action_id}'.")
        eliminates = self._kit.oracle_table[action_ctx.action_id][outcome]["eliminates"]
        observation_id = f"{action_ctx.action_id}:{outcome}"
        justification = {
            "probe": action_ctx.action_id,
            "outcome": outcome,
        }
        return [
            EliminateMessage.create(
                source_id=self._source_id,
                observation_id=observation_id,
                eliminated=list(eliminates),
                justification=justification,
            )
        ]


def _normalize_outcome(raw_observation: Any) -> str:
    if isinstance(raw_observation, str):
        return raw_observation.strip().lower()
    raise ValueError("ITBenchAdapter expects raw_observation to be a string outcome.")


def _is_noop(oracle_table: dict[str, dict[str, dict[str, list[str]]]], action_id: str, survivors: set[str]) -> bool:
    for spec in oracle_table.get(action_id, {}).values():
        if set(spec.get("eliminates", [])) & survivors:
            return False
    return True
