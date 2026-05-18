"""CMBS adapters (core boundary implementations)."""

from .itbench import ITBenchAdapter, ITBenchKit, ITBenchOracle
from .legacy import LegacyEliminationEvent, LegacyReplayAdapter, submit_legacy_elimination
from .twenty_questions import TwentyQAdapter, TwentyQKit, TwentyQOracle
from .types import Action, AdapterActionContext, BeliefAdapter, BeliefMessage, EliminateMessage

__all__ = [
    "Action",
    "AdapterActionContext",
    "BeliefAdapter",
    "BeliefMessage",
    "EliminateMessage",
    "LegacyEliminationEvent",
    "LegacyReplayAdapter",
    "submit_legacy_elimination",
    "TwentyQAdapter",
    "TwentyQKit",
    "TwentyQOracle",
    "ITBenchAdapter",
    "ITBenchKit",
    "ITBenchOracle",
]
