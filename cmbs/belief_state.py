"""
SPI-based belief state.

CMBS never imports domain code; it depends only on HypothesisProvider.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .spi.hypothesis_provider import HypothesisProvider


@dataclass
class BeliefState:
    provider: HypothesisProvider
    _active: dict[str, bool]
    _total: int

    def __init__(self, provider: HypothesisProvider) -> None:
        self.provider = provider
        self._active = {hid: True for hid in provider.hypothesis_ids()}
        self._total = len(self._active)

    @property
    def survivors(self) -> set[str]:
        return {hid for hid, active in self._active.items() if active}

    def apply_probe(self, probe_id: str, response) -> set[str]:
        eliminations = self.provider.apply_probe(probe_id, response)
        eliminated: set[str] = set()
        for hid, is_eliminated in eliminations.items():
            if hid not in self._active:
                raise ValueError(f"Unknown hypothesis id '{hid}' from provider.")
            if is_eliminated and self._active[hid]:
                self._active[hid] = False
                eliminated.add(hid)
        return eliminated

    def remaining_mass(self) -> float:
        if self._total == 0:
            return 0.0
        return len(self.survivors) / self._total

    def remaining_entropy(self) -> float:
        n = len(self.survivors)
        return 0.0 if n <= 1 else math.log2(n)

    def is_singleton(self) -> bool:
        return len(self.survivors) == 1

    def is_empty(self) -> bool:
        return len(self.survivors) == 0

    def active_map(self) -> dict[str, bool]:
        return dict(self._active)
