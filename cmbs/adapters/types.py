"""
Shared adapter types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..belief_server import BeliefSnapshot


@dataclass(frozen=True)
class Action:
    action_id: str
    prompt: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AdapterActionContext:
    action_id: str
    snapshot: BeliefSnapshot
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EliminateMessage:
    verb: str
    source_id: str
    observation_id: str
    eliminated: list[str]
    justification: dict[str, Any]

    @staticmethod
    def create(
        source_id: str,
        observation_id: str,
        eliminated: list[str],
        justification: dict[str, Any],
    ) -> EliminateMessage:
        return EliminateMessage(
            verb="ELIMINATE",
            source_id=source_id,
            observation_id=observation_id,
            eliminated=eliminated,
            justification=justification,
        )


BeliefMessage = EliminateMessage


class BeliefAdapter(Protocol):
    def list_actions(self, snapshot: BeliefSnapshot) -> list[Action]:
        """Return available probes/actions given current belief."""

    def apply_action(self, action_id: str, snapshot: BeliefSnapshot) -> AdapterActionContext:
        """Prepare to execute the action (prompt, query, probe)."""

    def observe(
        self,
        action_ctx: AdapterActionContext,
        raw_observation: Any,
    ) -> list[BeliefMessage]:
        """Translate observation into belief-protocol messages."""
