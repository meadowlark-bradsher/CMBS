from collections.abc import Iterable, Mapping
from typing import Any

from cmbs.belief_server import BeliefServer, OntologyBundle


class DummyProvider:
    def id(self) -> str:
        return "dummy.v1"

    def version(self) -> str:
        return "1.0"

    def hypothesis_ids(self) -> Iterable[str]:
        return ["a", "b", "c"]

    def probe_ids(self) -> Iterable[str]:
        return ["p"]

    def apply_probe(self, probe_id: str, response: Any) -> Mapping[str, bool]:
        return {"a": False, "b": True, "c": False}


def test_belief_server_spi_smoke():
    server = BeliefServer(belief_provider=DummyProvider())
    session_id, before = server.declare_session(
        ontology=OntologyBundle(
            hypothesis_space_id="dummy",
            hypothesis_version="v1",
            causal_graph_ref="none",
            causal_graph_version="v0",
        ),
        hypotheses=[],
    )

    applied, _, after, _ = server.apply_probe(
        session_id=session_id,
        probe_id="p",
        response="anything",
    )

    assert "b" not in after.survivors
    assert "b" in before.survivors
    assert applied == ["b"]
    assert after.entropy_proxy < before.entropy_proxy

    before_mass = len(before.survivors) / len(before.survivors)
    after_mass = len(after.survivors) / len(before.survivors)
    assert after_mass < before_mass

    approved, reason, _, _ = server.request_termination(session_id=session_id)
    assert approved is False
    assert "singleton" in reason
