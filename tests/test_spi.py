"""HypothesisProvider SPI: providers feed a Session; the kernel stays opaque."""

from collections.abc import Iterable, Mapping
from typing import Any

from cmbs import HypothesisProvider, Session, discover_providers


class ToyProvider:
    def id(self) -> str:
        return "toy"

    def version(self) -> str:
        return "1.0"

    def hypothesis_ids(self) -> Iterable[str]:
        return ["H1", "H2", "H3"]

    def probe_ids(self) -> Iterable[str]:
        return ["p1", "p2"]

    def apply_probe(self, probe_id: str, response: Any) -> Mapping[str, bool]:
        if probe_id == "p1":
            return {"H1": response == "no"}
        if probe_id == "p2":
            return {"H2": True, "H3": False}
        return {}


def _submit(session: Session, provider: HypothesisProvider, probe_id: str, response: Any):
    mask = provider.apply_probe(probe_id, response)
    return session.submit_probe_result(
        probe_id=probe_id,
        observable_id=f"{probe_id}:{response}",
        eliminated={hid for hid, gone in mask.items() if gone},
        source_id=f"provider://{provider.id()}@{provider.version()}",
    )


def test_provider_seeds_a_session():
    provider = ToyProvider()
    session = Session(hypothesis_ids=provider.hypothesis_ids())
    assert session.survivors == {"H1", "H2", "H3"}


def test_provider_mask_drives_elimination():
    provider = ToyProvider()
    session = Session(hypothesis_ids=provider.hypothesis_ids())

    r = _submit(session, provider, "p1", "no")
    assert r.accepted is True
    assert r.eliminated == {"H1"}
    assert session.survivors == {"H2", "H3"}
    assert session.operations()[0].source_id == "provider://toy@1.0"


def test_repeated_probe_is_rejected_not_reapplied():
    provider = ToyProvider()
    session = Session(hypothesis_ids=provider.hypothesis_ids())

    assert _submit(session, provider, "p2", "x").accepted is True
    assert _submit(session, provider, "p2", "x").accepted is False
    assert session.survivors == {"H1", "H3"}
    assert session.head_seq == 2


def test_discover_providers_returns_dict():
    providers = discover_providers()
    assert isinstance(providers, dict)
