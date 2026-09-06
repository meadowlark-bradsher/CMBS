# Architecture

CMBS draws a strict line between **mechanism** and **policy**.

The kernel ([`cmbs.Session`](reference/api.md#session)) provides mechanism:
tracking surviving hypotheses, recording eliminations, computing entropy, and
enforcing a small set of invariants. It is domain-agnostic and treats every
identifier as opaque.

Everything else — when to probe, what an observation means, which hypotheses
to eliminate, when to stop — is policy and belongs in adapters.

## State is the reduction of a log

A session holds no mutable belief state of its own. Its state is always

```
snapshot = reduce(initial_hypotheses, op_log)
```

where the op log is an append-only sequence of `OperationEnvelope` records
and `reduce` is a versioned, deterministic function supplied by a `Reducer`.
The consequences:

- **The log is the audit trail.** There is no separate audit structure that
  can drift from the state. Every submitted operation, accepted or rejected,
  is in the log with its verdict and reason.
- **Every position has a hash.** `Snapshot.state_hash` covers the canonical
  belief content, the reducer version, the session ID, and the log position.
  Two parties holding the same log under the same reducer compute the same
  hash at every step.
- **Recovery is replay.** `Session.recover(store, session_id)` reads the log
  back from an `OpLogStore` and folds it through the reducer. It refuses to
  replay under a reducer version other than the one that wrote the log.

The `Session` keeps its current snapshot cached and advances it one step per
append; the cached value is always equal to a full reduction of the log.

## Kernel responsibilities

- Track the current set of surviving hypotheses
- Apply eliminations submitted by adapters (monotone — survivors only shrink)
- Compute entropy as `log₂(|survivors|)`
- Reject duplicate probe submissions, and log the rejected attempt
- Track epistemic obligations and gate their exit on substantive change
- Optionally enforce a stability window before termination
- Persist every operation to an `OpLogStore` and rebuild from it on demand

## What the kernel does not do

- Execute or schedule probes
- Choose actions or manage control loops
- Interpret observables, hypotheses, or conclusions
- Define obligation types, repair workflows, or compatibility tables
- Provide domain-specific thresholds (callers pass them in)
- Maintain probabilistic beliefs or confidence scores
- Auto-terminate based on entropy or singleton survivors
- Freeze the session after termination (later operations still apply)

All of the above are adapter concerns.

## Enforced invariants

Invariants are enforced by the reducer at append time. The reducer's
`check` step decides whether an operation is accepted; the verdict is
persisted on the envelope, and only accepted operations change belief.

| ID      | Name                   | Where enforced                                                                 |
| ------- | ---------------------- | ------------------------------------------------------------------------------ |
| INV-3   | Probe non-repetition   | Any op whose `idempotency_key` was already consumed is rejected. The facade uses `probe_id` as the key of `probe_result` ops. |
| INV-5a  | Entropy quantification | `Snapshot.entropy` and `Session.entropy` return `log₂(\|survivors\|)`; never used as a gate |
| INV-6   | Non-trivial exit       | `exit_obligation` is accepted only once `min_eliminations` have been recorded *after* the matching `enter_obligation` |
| INV-2*  | Stability window       | `request_termination` is accepted only if the last N declared conclusions are identical |

\* INV-2 is opt-in via the `stability_window` constructor argument; `0`
(the default) disables the gate. See the
[invariant test matrix](reference/invariant-test-matrix.md) for which tests
exercise each invariant.

Any newly eliminated hypothesis, whatever operation removed it, counts toward
every obligation open at the time.

## Layers

CMBS is one kernel with a persistence interface underneath and adapters on
top:

1. **`Session`** — the kernel. One instance is one investigation. Exposes an
   imperative facade (`submit_probe_result`, `enter_obligation`,
   `request_obligation_exit`, `declare_conclusion`, `request_termination`)
   and a lower-level `append(OperationSpec)` for callers who construct
   operations directly.
2. **`Reducer`** — the versioned fold from log to `Snapshot`. The shipped
   `MaskMeetTombstoneReducer` (`"v1_mask_meet_tombstone"`) implements
   monotone set elimination plus the invariant gates above. A replacement
   reducer changes the meaning of a log, which is why the version is stored
   with the session and checked on recovery.
3. **`OpLogStore`** — the persistence SPI. `InMemoryOpLogStore` ships in the
   box; file, database, or network stores can be added without modifying
   the kernel. The store holds envelopes and session metadata only; it never
   interprets them.
4. **Adapters** — domain translation. They turn observations into
   elimination sets and drive the facade. `HypothesisProvider` is the plugin
   point for external hypothesis spaces; the twenty-questions and ITBench
   adapters are reference shapes; `LegacyReplayAdapter` ports pre-existing
   elimination logs in.

Multiple sessions can share one store. There is no multi-session manager or
network layer in the package; both are additive on top of the same kernel if
a use case needs them.

## Two identities

A snapshot carries two hashes that answer different questions.

- **`state_hash`** answers "which position in *this* log?" It covers the
  full belief content, the reducer version, the session ID, and `seq`. It
  changes on every append, including rejected ones, and differs across
  sessions by construction. It is the audit identity.
- **`position_digest`** answers "which point in the belief lattice?" It
  covers the sorted survivor set and nothing else. Two sessions with the
  same survivors share it whatever their history, and an op that eliminates
  nothing leaves it unchanged. It is the convergence identity.

The lattice reading is deliberate: the belief part of a snapshot is a subset
of the universe, every elimination is a meet against a mask, and the
universe is the top element. Obligations, conclusion history, and `attrs`
are workflow state layered on that lattice, which is why they are in the
state hash and not the digest.

## Two kinds of repeat

The `append` API distinguishes two ways an operation can be "the same as
one already seen":

- A caller-supplied **`op_id`** that is already in the log is a
  transport-level retry. Nothing is appended; the original envelope and the
  state hash at its position are returned.
- An **`idempotency_key`** already consumed by an accepted operation is a
  domain-level repeat (INV-3). A new, *rejected* envelope is appended so the
  attempt is auditable.

## Boundary properties

These follow from the invariants above and from the kernel design:

- **Opaque identifiers**: hypothesis, probe, observable, conclusion,
  obligation, and source IDs are strings the kernel never parses.
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
- **Provenance is opaque**: `source_id` and any `provenance` payload are
  stored on the envelope for the caller's benefit and never read by the
  kernel.

## Provisional semantics

ADR-001 flagged that termination policy is unresolved across the earlier
kernels. The current reducer takes the least restrictive option on purpose:
termination is gated only by the stability window, does not require closed
obligations or a singleton survivor, does not freeze the session, and can be
re-requested. A follow-up ADR will lock the policy in; until then, callers
who need stricter gating enforce it in their own loop.
