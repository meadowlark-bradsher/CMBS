# CMBS — Constraint Mask Belief System

CMBS is a belief-state accounting library for long-horizon agents. It tracks
hypotheses, records eliminations, computes entropy, and enforces obligation
discipline using opaque identifiers — and **only** that. The core is
domain-agnostic, monotone (hypotheses can be eliminated but never reintroduced),
and replay-auditable.

The intended use is to externalize belief out of prompts, hidden agent state,
or ad-hoc logs into an explicit, inspectable state machine that policy and
learning layers can plug into.

## Install

```bash
pip install cmbs
```

## Quickstart

```python
from cmbs import CMBSCore

core = CMBSCore(hypothesis_ids={"H1", "H2", "H3"})

result = core.submit_probe_result(
    probe_id="P1",
    observable_id="O1",
    eliminated={"H1"},
)

assert result.accepted
assert core.survivors == {"H2", "H3"}
```

CMBS does not execute probes, choose actions, or interpret observables. All
of those live in adapters; the kernel only books the consequences.

## Next steps

- [Use Cases](use-cases.md) — when CMBS fits, including LLM context management
- [Architecture](architecture.md) — mechanism vs policy, invariants, layers
- [API Reference](reference/api.md) — the public surface
- [Repository Layout](reference/repository.md) — what lives where
- [Invariant Test Matrix](reference/invariant-test-matrix.md) — what's tested

## Local docs preview

```bash
pip install mkdocs
mkdocs serve
```

Then open `http://127.0.0.1:8000`.
