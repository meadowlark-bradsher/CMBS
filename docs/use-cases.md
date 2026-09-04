# Use Cases

CMBS is for situations where a system needs to **track and narrow a set of
possibilities over many steps**, where that belief state should be inspectable
and auditable, and where ad-hoc tracking (in prompts, hidden state, scattered
logs) starts to break down. This page walks through where CMBS fits, with
worked patterns.

## Context management for long-horizon LLM agents

The problem with long-horizon LLM agents is that "what we already know" tends
to live inside the prompt. After 50 tool calls, the conversation history is
bloated with redundant context, the model forgets what's already been ruled
out, and "we already tried X" gets repeated or contradicted. Summarization
loses fidelity; full history is expensive and lossy in different ways.

CMBS externalizes the **epistemic-state slice** of agent memory: the set of
surviving hypotheses, the operation log of what was eliminated by which probe,
and the obligations that gate progress. The prompt only ever has to carry
the current frontier plus a small recent-events window — regardless of how
long the investigation has been running.

### What you gain

- **Constant-token prompts** for arbitrarily long investigations. A 100-turn
  session with 47 ruled-out hypotheses is the same prompt size as turn 1.
- **Structural non-repetition.** [INV-3](architecture.md#enforced-invariants)
  rejects duplicate probe IDs. You don't need a "don't repeat questions"
  instruction in the prompt — the kernel returns `accepted=False`, logs the
  attempt, and your loop handles it.
- **Progress guardrails.** Obligations let you require that *N* hypotheses be
  eliminated within a scope before the agent is allowed to declare a
  conclusion. Catches confidently-wrong-and-done failure modes.
- **Verifiable replay.** Every envelope in the log has a state hash for the
  position after it. When a user asks "why did you conclude X?", you replay
  the log programmatically — not by asking the LLM to reconstruct its
  reasoning from a stale transcript.

### The loop, concretely

```python
from cmbs import Session

session = Session(hypothesis_ids=your_hypothesis_registry)
session.enter_obligation("investigate", min_eliminations=3)

while not session.is_terminated:
    prompt = render_prompt(
        survivors=sorted(session.survivors),
        entropy=session.entropy,
        recent=session.operations()[-3:],
        instructions=(
            "Propose next probe as JSON: "
            '{"probe_id": "...", "observable_id": "...", "target_hypotheses": [...]}'
        ),
    )
    proposal = llm(prompt)

    # You run the probe — tool call, user query, web search, whatever.
    observation = run_probe(proposal)

    # Your adapter interprets observation → set of eliminated hypothesis IDs.
    eliminated = adapter.interpret(observation, survivors=session.survivors)

    result = session.submit_probe_result(
        probe_id=proposal["probe_id"],
        observable_id=proposal["observable_id"],
        eliminated=eliminated,
        provenance={"raw": observation},
    )
    # result.accepted is False if the LLM tried to repeat itself —
    # the attempt is already in the log; continue without rewriting the prompt.

    if len(session.survivors) == 1:
        if session.request_obligation_exit("investigate").permitted:
            session.declare_conclusion(next(iter(session.survivors)))
            session.request_termination()
```

The prompt size is `O(|survivors| + k)`, not `O(turns)`. The LLM's job becomes
much narrower — *given this frontier, propose the next discriminating probe*
— which is a task it's actually good at. "Remember everything you've ever
ruled out across 100 turns" is not.

[examples/run_20q.py](https://github.com/meadowlark-bradsher/CMBS/blob/main/examples/run_20q.py)
is a worked end-to-end version of this pattern using the twenty-questions
adapter.

## Other use cases

### Auditable diagnosis (medical, legal, compliance, incident response)

When the output of a system is going to be questioned — by a regulator, by
opposing counsel, by an oncall postmortem — "the LLM said so" is not a
defensible answer. CMBS gives you a structured record of which hypotheses
were considered, which were eliminated, by what evidence, in what order.
Replay is reproducible; the audit trail isn't bolted on after the fact, it
*is* the state.

Hand the reviewing party the initial hypothesis set and the log from
`session.operations()`. They rebuild the state with the same reducer and
compare hashes:

```python
from cmbs import MaskMeetTombstoneReducer

replayed = MaskMeetTombstoneReducer().reduce(
    session.initial_hypotheses,
    session.operations(),
    session_id=session.session_id,
    stability_window=session.stability_window,
)
assert replayed.state_hash == session.snapshot().state_hash
```

### Multi-agent verifiable belief sharing

When two agents need to share "what's been ruled out so far," passing
transcripts is fragile (the receiving agent has to re-interpret) and passing
summaries is lossy. CMBS gives them a shared structured object: the
`survivors` set, the operation log, the obligations. Each agent reads the
same truth and produces eliminations the other can verify.

The `OpLogStore` SPI is the integration point. Agents in one process share a
store and recover the same session from it; each envelope's `source_id`
records who contributed it. A network layer on top of the same log is
additive work that the kernel does not need to know about.

### Crash recovery and migration between processes

Because the state is the log, resuming after a crash is a replay:

```python
from cmbs import InMemoryOpLogStore, Session

store = InMemoryOpLogStore()          # or your own OpLogStore implementation
session = Session(hypothesis_ids={"H1", "H2", "H3"}, store=store)
session.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})

resumed = Session.recover(store, session.session_id)
assert resumed.snapshot() == session.snapshot()
```

The recovered session continues the same log: a probe ID consumed before
the crash is still rejected after it.

### Replacing ad-hoc "ruled out" tracking in pipelines and scripts

Plenty of scientific workflows, debugging scripts, and benchmark harnesses
already maintain "list of things we've checked and discarded" in ad-hoc
ways — Python dicts, comments in code, scattered log lines. CMBS gives that
pattern a proper home: monotone, queryable, replayable, with a built-in
non-repetition guarantee. The `LegacyReplayAdapter` exists specifically to
port pre-existing elimination logs in.

## Where CMBS fits

| If your system… | CMBS is probably a fit |
|---|---|
| Tracks a **finite, enumerable** set of hypotheses | ✓ |
| Updates by **eliminating** options as evidence arrives | ✓ |
| Needs an **inspectable, auditable** record of why | ✓ |
| Runs over **many steps**, with state to preserve across them | ✓ |
| Needs **non-repetition** of probes/questions as a hard rule | ✓ |
| Needs **crash recovery** of belief state | ✓ (persist to an `OpLogStore`) |
| Needs **independent verification** of a conclusion | ✓ (replay the log, compare hashes) |

## Where CMBS does *not* fit

| If your system… | Look elsewhere |
|---|---|
| Maintains **probability distributions** over hypotheses | Bayesian frameworks (pymc, pyro) |
| Uses **soft constraints** that combine continuously | Constraint solvers (z3, OR-Tools) |
| **Discovers new hypotheses mid-run** (open-world) | CMBS is closed-world — you'd bolt on a hypothesis-expansion step yourself |
| Models **arc-consistent constraint graphs** | Constraint propagation libraries |
| Needs **undo / un-elimination** | CMBS is monotone by design — by construction this isn't supported |
| Wants to **fork and compare alternate orderings** | Not in the package today. The log makes it possible to build on top; nothing ships for it yet |
| Only needs **last-turn memory** | A plain dict is simpler |

## What you have to bring

CMBS provides mechanism, not policy. To use it, you supply:

1. **A hypothesis registry.** A finite set of opaque IDs the kernel will
   track. You also typically keep a separate mapping from ID to
   human-readable description (CMBS doesn't store this — it would violate
   the opaque-ID discipline). `OntologyBundle` lets you record *which*
   registry and version a session was built against, for audit.
2. **An adapter that interprets observations.** When a probe returns a
   result, *something* has to decide which hypothesis IDs to eliminate.
   That's adapter logic — CMBS won't do it for you. The shipped adapters
   ([twenty-questions](https://github.com/meadowlark-bradsher/CMBS/tree/main/cmbs/adapters/twenty_questions),
   [itbench](https://github.com/meadowlark-bradsher/CMBS/tree/main/cmbs/adapters/itbench),
   [legacy replay](https://github.com/meadowlark-bradsher/CMBS/tree/main/cmbs/adapters/legacy))
   are reference shapes.
3. **A probe-selection policy.** What to investigate next. For LLM agents
   this is the LLM itself; for scripted workflows it's your code; for
   benchmarks it's the benchmark's scenario definition.
4. **A termination policy.** When is the agent done? CMBS gives you
   primitives (`request_termination`, optional stability window, obligation
   discipline) but the call is yours.
5. **A store, if you need durability.** The in-memory store is the default.
   Anything longer-lived than the process is an `OpLogStore` you implement
   or install.

## Where to look next

- [Architecture](architecture.md) — the mechanism/policy boundary, the op
  log, and the four enforced invariants
- [API Reference](reference/api.md) — full public surface
- [examples/run_20q.py](https://github.com/meadowlark-bradsher/CMBS/blob/main/examples/run_20q.py)
  — runnable end-to-end loop
