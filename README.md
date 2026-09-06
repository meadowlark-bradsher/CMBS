# CMBS — Constraint Mask Belief System

**Externalized belief state for long-horizon agents.** CMBS keeps "what's
been ruled out and why" *out* of your LLM prompt and *in* an inspectable,
monotone, replay-auditable state machine. Prompts stay constant-token even
as investigations run for hundreds of steps; non-repetition is structurally
enforced; every step of the op log carries a state hash for verifiable replay.

## LLM context management

A debugging agent runs 80 tool calls to narrow a customer issue. With raw
conversation history, the prompt has bloated to 40k tokens, the model has
forgotten which hypotheses it already ruled out, and "we already tried X"
gets repeated. With CMBS:

```python
from cmbs import Session

session = Session(hypothesis_ids=your_hypothesis_registry)
session.enter_obligation("investigate", min_eliminations=3)

while not session.is_terminated:
    proposal = llm(render_prompt(
        survivors=sorted(session.survivors),      # current frontier
        entropy=session.entropy,                  # bits remaining
        recent=session.operations()[-3:],         # last 3 ops from the log
    ))
    observation = run_probe(proposal)
    eliminated = adapter.interpret(observation, session.survivors)
    session.submit_probe_result(
        probe_id=proposal["probe_id"],
        observable_id=proposal["observable_id"],
        eliminated=eliminated,
    )
```

The prompt size is `O(|survivors| + k)`, not `O(turns)`. The kernel rejects
duplicate `probe_id`s; obligations gate premature conclusions; the op log
carries a state hash per step for after-the-fact replay. See
[docs/use-cases.md](docs/use-cases.md) for the full pattern and other
applications (auditable diagnosis, multi-agent belief sharing, counterfactual
exploration).

## What CMBS does and doesn't do

CMBS is mechanism, not policy. It tracks hypotheses, records eliminations,
computes entropy, enforces obligation discipline, and keeps the op log that
is its own replayable audit trail. It does *not* execute probes, choose actions, interpret
observables, or maintain probabilistic beliefs — those belong to adapters
and to the surrounding agent.

It's intended to sit alongside frozen or learning agents, not inside them.

## Quick Start

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

State is derived from an append-only op log: every call above is an
`OperationEnvelope` you can read back with `session.operations()`, and a
session can be rebuilt from its `OpLogStore` with `Session.recover`.

## Legacy Replay Shim

For audit continuity with legacy logs, use the thin adapter in `cmbs.adapters.legacy`:

```python
from cmbs import Session
from cmbs.adapters.legacy import LegacyReplayAdapter, LegacyEliminationEvent

session = Session(hypothesis_ids={"H1", "H2"})
adapter = LegacyReplayAdapter(session)

adapter.submit_elimination_event(
    LegacyEliminationEvent(
        probe_id="legacy:probe:001",
        observable_id="legacy:obs:alpha",
        eliminated_hypotheses={"H2"},
    )
)
```

## Docs

- [Home](docs/index.md) — install, quickstart, and pointers
- [Use Cases](docs/use-cases.md) — LLM context management and other applications
- [Architecture](docs/architecture.md) — mechanism vs policy, invariants, layers
- [Tutorials](docs/tutorials.md) — six runnable scripts, three of them live against Claude
- [API Reference](docs/reference/api.md) — public surface
- [Repository Layout](docs/reference/repository.md) — what lives where
- [Invariant Test Matrix](docs/reference/invariant-test-matrix.md) — what's tested

Published at <https://meadowlark-bradsher.github.io/CMBS/> via mkdocs (CI in
`.github/workflows/deploy-pages.yml`).
