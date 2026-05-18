from collections.abc import Iterable, Mapping
from typing import Any

from cmbs.belief_state import BeliefState
from cmbs.spi import discover_providers


class ToyProvider:
    def __init__(self) -> None:
        self._hypotheses = ["H1", "H2", "H3"]

    def id(self) -> str:
        return "toy"

    def version(self) -> str:
        return "1.0"

    def hypothesis_ids(self) -> Iterable[str]:
        return list(self._hypotheses)

    def probe_ids(self) -> Iterable[str]:
        return ["p1", "p2"]

    def apply_probe(self, probe_id: str, response: Any) -> Mapping[str, bool]:
        if probe_id == "p1":
            return {"H1": response == "no"}
        if probe_id == "p2":
            return {"H2": True, "H3": False}
        return {}


def test_belief_state_applies_elimination():
    belief = BeliefState(ToyProvider())
    eliminated = belief.apply_probe("p1", "no")
    assert eliminated == {"H1"}
    assert "H1" not in belief.survivors
    assert belief.remaining_mass() == 2 / 3
    assert belief.is_singleton() is False


def test_belief_state_idempotent():
    belief = BeliefState(ToyProvider())
    belief.apply_probe("p2", "anything")
    eliminated_again = belief.apply_probe("p2", "anything")
    assert eliminated_again == set()
    assert "H2" not in belief.survivors


def test_discover_providers_returns_dict():
    providers = discover_providers()
    assert isinstance(providers, dict)
