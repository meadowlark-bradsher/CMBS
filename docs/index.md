# CMBS — Constraint Mask Belief System

CMBS is a belief-state accounting library for long-horizon agents. It tracks
hypotheses, records eliminations, computes entropy, and enforces obligation
discipline using opaque identifiers — and **only** that. The kernel is
domain-agnostic, monotone (hypotheses can be eliminated but never
reintroduced), and replay-auditable: state is derived from an append-only
operation log, and every step of that log carries a verifiable state hash.

The intended use is to externalize belief out of prompts, hidden agent state,
or ad-hoc logs into an explicit, inspectable state machine that policy and
learning layers can plug into.

## Install

```bash
pip install cmbs
```

The only runtime dependency is `pyyaml`, used by the reference adapters to
load their kit files.

## Quickstart

```python
from cmbs import Session

session = Session(hypothesis_ids={"H1", "H2", "H3"})

result = session.submit_probe_result(
    probe_id="P1",
    observable_id="O1",
    eliminated={"H1"},
)

assert result.accepted
assert session.survivors == {"H2", "H3"}
```

One `Session` is one investigation. Every call above appends an
`OperationEnvelope` to the session's log; `session.operations()` reads the
log back, and `Session.recover(store, session_id)` rebuilds a session from
it.

CMBS does not execute probes, choose actions, or interpret observables. All
of those live in adapters; the kernel only books the consequences.

## Next steps

- [Use Cases](use-cases.md) — when CMBS fits, including LLM context management
- [Architecture](architecture.md) — mechanism vs policy, invariants, the op log
- [API Reference](reference/api.md) — the public surface
- [Repository Layout](reference/repository.md) — what lives where
- [Invariant Test Matrix](reference/invariant-test-matrix.md) — what's tested

The design decisions behind the current shape are recorded in
[ADR-001](https://github.com/meadowlark-bradsher/CMBS/blob/main/design/adr-001-unify-kernels.md)
(one kernel instead of two) and
[ADR-002](https://github.com/meadowlark-bradsher/CMBS/blob/main/design/adr-002-naming.md)
(names).

## Local docs preview

```bash
pip install mkdocs
mkdocs serve
```

Then open `http://127.0.0.1:8000`.
