"""
Twenty Questions adapter.
"""

from __future__ import annotations

from typing import Any

from ..types import Action, AdapterActionContext, BeliefMessage, EliminateMessage
from .kit import TwentyQKit


class TwentyQAdapter:
    def __init__(self, kit: TwentyQKit, source_id: str = "adapter://twenty_questions"):
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
            if _is_noop(spec.keep, survivors):
                continue
            actions.append(
                Action(
                    action_id=action_id,
                    prompt=spec.question,
                    metadata={"question": spec.question},
                )
            )
        return actions

    def apply_action(self, action_id: str, snapshot) -> AdapterActionContext:
        spec = self._kit.actions[action_id]
        self._asked.add(action_id)
        return AdapterActionContext(
            action_id=action_id,
            snapshot=snapshot,
            payload={"question": spec.question},
        )

    def observe(
        self,
        action_ctx: AdapterActionContext,
        raw_observation: Any,
    ) -> list[BeliefMessage]:
        outcome = _normalize_outcome(raw_observation)
        spec = self._kit.actions[action_ctx.action_id]
        survivors = set(action_ctx.snapshot.survivors)
        keep = set(spec.keep[outcome])
        eliminated = sorted(list(survivors - keep))
        observation_id = f"{action_ctx.action_id}:{outcome}"
        justification = {
            "action_id": action_ctx.action_id,
            "question": spec.question,
            "outcome": outcome,
        }
        return [
            EliminateMessage.create(
                source_id=self._source_id,
                observation_id=observation_id,
                eliminated=eliminated,
                justification=justification,
            )
        ]


def _normalize_outcome(raw_observation: Any) -> str:
    if isinstance(raw_observation, str):
        value = raw_observation.strip().lower()
        if value in {"yes", "no"}:
            return value
    raise ValueError("TwentyQAdapter expects raw_observation to be 'yes' or 'no'.")


def _is_noop(keep: dict[str, list[str]], survivors: set[str]) -> bool:
    for outcome in ("yes", "no"):  # noqa: SIM110 — pending rewrite, see issue
        if survivors - set(keep[outcome]):
            return False
    return True
