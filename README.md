# CMBS — Constraint Mask Belief System

**Externalized belief state for long-horizon agents.** CMBS keeps "what's
been ruled out and why" *out* of your LLM prompt and *in* an inspectable,
monotone, replay-auditable state machine. Prompts stay constant-token even
as investigations run for hundreds of steps; non-repetition is structurally
enforced; every elimination is hash-chained for verifiable replay.

## LLM context management

A debugging agent runs 80 tool calls to narrow a customer issue. With raw
conversation history, the prompt has bloated to 40k tokens, the model has
forgotten which hypotheses it already ruled out, and "we already tried X"
gets repeated. With CMBS:

```python
from cmbs import CMBSCore

core = CMBSCore(hypothesis_ids=set(your_hypothesis_registry))
core.enter_obligation("investigate", min_eliminations=3)

while not core.is_terminated:
    proposal = llm(render_prompt(
        survivors=sorted(core.survivors),         # current frontier
        entropy=core.entropy,                     # bits remaining
        recent=core.get_elimination_history()[-3:],  # last 3 events
    ))
    observation = run_probe(proposal)
    eliminated = adapter.interpret(observation, core.survivors)
    core.submit_probe_result(
        probe_id=proposal["probe_id"],
        observable_id=proposal["observable_id"],
        eliminated=eliminated,
    )
```

The prompt size is `O(|survivors| + k)`, not `O(turns)`. The kernel rejects
duplicate `probe_id`s; obligations gate premature conclusions; the audit
trail is hash-chained for after-the-fact replay. See
[docs/use-cases.md](docs/use-cases.md) for the full pattern and other
applications (auditable diagnosis, multi-agent belief sharing, counterfactual
exploration).

## What CMBS does and doesn't do

CMBS is mechanism, not policy. It tracks hypotheses, records eliminations,
computes entropy, enforces obligation discipline, and maintains a replayable
audit log. It does *not* execute probes, choose actions, interpret
observables, or maintain probabilistic beliefs — those belong to adapters
and to the surrounding agent.

It's intended to sit alongside frozen or learning agents, not inside them.

## Quick Start

```python
from cmbs.core import CMBSCore

core = CMBSCore(hypothesis_ids={"H1", "H2", "H3"})
result = core.submit_probe_result(
    probe_id="P1",
    observable_id="O1",
    eliminated={"H1"},
)
assert result.accepted
```

## Legacy Replay Shim

For audit continuity with legacy logs, use the thin adapter in `cmbs.adapters.legacy`:

```python
from cmbs.core import CMBSCore
from cmbs.adapters.legacy import LegacyReplayAdapter, LegacyEliminationEvent

core = CMBSCore(hypothesis_ids={"H1", "H2"})
adapter = LegacyReplayAdapter(core)

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
- [API Reference](docs/reference/api.md) — public surface
- [Repository Layout](docs/reference/repository.md) — what lives where
- [Invariant Test Matrix](docs/reference/invariant-test-matrix.md) — what's tested

Published at <https://meadowlark-bradsher.github.io/CMBS/> via mkdocs (CI in
`.github/workflows/deploy-pages.yml`).
