# Architecture

CMBS draws a strict line between **mechanism** and **policy**.

The kernel ([`cmbs.core.CMBSCore`](reference/api.md#cmbscore)) provides
mechanism: tracking surviving hypotheses, recording eliminations, computing
entropy, and enforcing a small set of invariants. It is domain-agnostic and
treats every identifier as opaque.

Everything else — when to probe, what an observation means, which hypotheses
to eliminate, when to stop — is policy and belongs in adapters.

## Core responsibilities

- Track the current set of surviving hypotheses
- Apply eliminations submitted by adapters (monotone — survivors only shrink)
- Compute entropy as `log₂(|survivors|)`
- Reject duplicate probe submissions
- Track epistemic obligations and gate their exit on substantive change
- Optionally enforce a stability window before termination
- Maintain a serializable audit trail of elimination events

## What core does not do

- Execute or schedule probes
- Choose actions or manage control loops
- Interpret observables, hypotheses, or conclusions
- Define obligation types, repair workflows, or compatibility tables
- Provide domain-specific thresholds (callers pass them in)
- Maintain probabilistic beliefs or confidence scores
- Auto-terminate based on entropy or singleton survivors

All of the above are adapter concerns.

## Enforced invariants

| ID      | Name                  | Where enforced                                |
| ------- | --------------------- | --------------------------------------------- |
| INV-3   | Probe non-repetition  | `submit_probe_result` rejects duplicate IDs   |
| INV-5a  | Entropy quantification | `entropy` property returns `log₂(\|survivors\|)` |
| INV-6   | Non-trivial exit      | `request_obligation_exit` requires `min_eliminations` within scope |
| INV-2*  | Stability window      | `request_termination` (optional, off by default) |

\* INV-2 is opt-in via the `stability_window` constructor argument. See the
[invariant test matrix](reference/invariant-test-matrix.md) for which tests
exercise each invariant.

## Layers

CMBS is built in layers, with the kernel at the bottom and progressively more
ambitious wrappers above:

1. **`CMBSCore`** — the kernel. Pure Python, no I/O, no persistence. Most
   users interact with this directly.
2. **`BeliefState`** — a lightweight container that hands the kernel to
   adapters with a cleaner surface.
3. **`BeliefServer`** — adds session management, ontology bundles, structured
   audit entries with before/after hashes, and a hypothesis-provider plugin
   point. Suitable for serving multiple sessions in-process.
4. **`OplogServer`** (v2) — an alternative session model where state is always
   derived from `reduce(reducer_version, op_log_prefix(branch, seq))`. Adds
   explicit branching, idempotency keys, and a `409 NON_COMMUTATIVE_CONFLICT`
   for non-commutative merges. Use this when you need to explore alternative
   operation orderings or replay sessions deterministically.
5. **`EliminationStore`** SPI — a protocol for pluggable elimination
   persistence. An `InMemoryStore` implementation ships in the box; external
   stores can be added without modifying the kernel.

## Boundary properties

These follow from the invariants above and from the kernel design:

- **Opaque identifiers**: hypothesis, probe, observable, and conclusion IDs
  are strings the kernel never parses.
- **Non-singleton termination**: termination is permitted at any survivor
  cardinality. CMBS does not assume the goal is to converge to one answer.
- **Non-binary conclusions**: any number of distinct conclusion IDs is
  supported.
- **Observation-only API**: probes are observations submitted to the kernel;
  there are no `attempt`/`success` states. Execution semantics belong to
  adapters.
- **Adapter-controlled lifecycle**: obligations and termination are
  initiated by adapter calls, never self-triggered.
- **Entropy is diagnostic**: it is queryable but does not gate termination
  or obligation exit.
