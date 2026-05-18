"""
Deterministic oracle for Twenty Questions kits.
"""

from __future__ import annotations

from .kit import TwentyQKit


class TwentyQOracle:
    def __init__(self, kit: TwentyQKit):
        self._keep: dict[str, dict[str, list[str]]] = {
            action_id: spec.keep for action_id, spec in kit.actions.items()
        }

    def answer(self, secret: str, action_id: str) -> str:
        keep = self._keep[action_id]
        return "yes" if secret in keep["yes"] else "no"
