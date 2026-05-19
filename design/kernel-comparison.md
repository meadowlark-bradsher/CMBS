# Kernel comparison: v0 vs v2

## Purpose

CMBS currently ships two parallel kernels with no shared code:

- **v0** — `cmbs.core.CMBSCore` (the imperative kernel) plus
  `cmbs.belief_server.BeliefServer` (session manager) and the
  `cmbs.spi.EliminationStore` SPI.
- **v2** — `cmbs.oplog_server.OplogServer` (transcript-conditioned)
  plus `cmbs.op_models.*` and `cmbs.reducers.*`.

The "v0/v2" naming is residue of development caution, not a real
version progression. There is no v1. This document compares the
design choices on each side, picks a winner per choice with reasoning,
and sketches what a unified kernel looks like if we ship the
best-of-each. It is **not yet a decided proposal** — it's a working
artifact to help the decision happen.

The repo has not been seen externally, so published-surface changes
are fair game.

## Verdict at a glance

| Dimension | v0 chose | v2 chose | Winner | Why |
|---|---|---|---|---|
| State representation | Mutable kernel object | Derived from op log via reducer | **v2** | Replay/branch require it; cost is mostly cognitive |
| Audit model | Side log of `AuditEntry` with before/after hashes (in `BeliefServer`) | Op log itself; `state_hash_after` per envelope | **v2** | One source of truth; tamper-evidence already covered |
| Public API style | Imperative methods (`submit_probe_result(...)`) | Envelope append (`append_op(spec)`) | **Mixed — keep imperative facade over v2 substrate** | Best of both is achievable |
| Operation representation | Free-form positional args | Typed envelope (op_type + payload + source_id + …) | **v2** | Extensible; provenance built-in |
| Provenance | `observable_id` (single string) | `source_id` + opaque `payload` dict | **v2** | Domain-isolated, kernel-opaque |
| Empty-elimination recording | Silently dropped | Always appended | **v2** | Already-agreed direction |
| Idempotency | None at kernel | `idempotency_key` on envelopes | **v2** | INV-3 is a subset of this |
| Branching | None | First-class | **v2** | No equivalent in v0 |
| Concurrency / merge | No notion | Explicit merge with `409 NON_COMMUTATIVE_CONFLICT` | **v2** | Required for branching |
| Reducer versioning | Implicit (code IS the semantics) | Explicit registry with version strings | **v2** | Required for verifiable replay |
| Persistence SPI | `EliminationStore` (Protocol) with `InMemoryStore` | None | **v0 (shape) — adapt to log** | Real interface worth keeping |
| Obligations | `enter_obligation` / `request_obligation_exit` enforcing INV-6 | Not in kernel | **v0** | Real guardrail; not domain-specific |
| Termination / stability | `request_termination` + `stability_window` enforcing INV-2 | Not in kernel | **v0** | Real guardrail; ditto |
| Conclusion stability tracking | `declare_conclusion` + history | Not in kernel | **v0** | Required input to INV-2 |
| Entropy | Property on kernel | Computable but not exposed | **Either — port to v2 as derived property** | Cheap; matches B-NONGATE |
| Test coverage today | 49 invariant tests on the kernel | 8 tests on the oplog server | **v0** | Big maturity gap |

Bottom line: **v2's substrate wins most dimensions; v0's workflow
primitives (obligations, termination, conclusion tracking) and its
persistence SPI shape are worth preserving on top of that substrate.**

## Dimension-by-dimension

### 1. State representation

**v0**: state lives as private attributes on `CMBSCore` (`_survivors`,
`_consumed_probes`, `_obligations`, etc.). Each call mutates them.
`serialize()` / `deserialize()` give checkpointing.

**v2**: state is `reduce(reducer_version, op_log_prefix(branch, seq))`.
The kernel doesn't store state directly — only the log. State is
computed on demand.

**Pros of v0's choice**

- Trivial mental model — Python objects with methods.
- Cheap reads (no replay).
- Easy to embed in tight loops.

**Cons of v0's choice**

- State and log can diverge if anything mishandles either.
- Replay requires reconstructing from the audit log, which means
  building a second pathway anyway.
- Branching is structurally impossible — only one timeline exists.

**Pros of v2's choice**

- State is provably a function of the log. No divergence possible.
- Replay is free (just re-reduce).
- Branching is natural (different prefixes → different states).
- Reducer can be versioned, so "we replayed the log under reducer
  v1.2 and got state S" is a verifiable claim.

**Cons of v2's choice**

- Reads cost more (must reduce). Mitigable with memoization on `seq`.
- More moving parts: log + reducer + branch records.

**Pick:** v2. The replay/branch story is the whole point of an
auditable belief system. The simplicity of v0 is real but recoverable
via an imperative facade (see §3).

### 2. Audit model

**v0 (via `BeliefServer`)**: separate `AuditEntry` records carrying
`verb`, `payload`, `survivors_before_hash`, `survivors_after_hash`,
`delta`. Hash-chained for tamper evidence.

**v2**: the op log itself is the audit. `OpAppendResult` already
carries `state_hash_after`; the envelope carries
`op_type`/`payload`/`source_id`/`accepted`/`rejected_reason`.

**Pros of v0's choice**

- Per-entry structure is richer (explicit verb, delta).
- Hash chain is an explicit feature.

**Cons of v0's choice**

- The audit log is *redundant* — derived from the state changes that
  happened. Could diverge from reality if buggy.
- Two representations of "what happened" (state + audit log) is one
  too many.

**Pros of v2's choice**

- Single source of truth.
- The log *causes* state, so the audit can't lie about state.
- `state_hash_after` per envelope gives equivalent tamper-evidence.

**Cons of v2's choice**

- Per-entry "delta" isn't intrinsic — must be computed by diffing
  states at adjacent seqs (cheap, but a step).
- No explicit verb taxonomy at the audit layer; verbs live as
  `op_type` strings.

**Pick:** v2. Move v0's `verb`/`delta` semantics into a thin
view-over-log helper. The hash-chain idea is already present in v2
as `state_hash_after`.

### 3. Public API style

**v0**: imperative methods that read clearly at call sites:

```python
core.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})
core.enter_obligation("investigate", min_eliminations=3)
result = core.request_termination()
```

**v2**: append-only envelopes:

```python
server.append_op(sid, branch_id="main", spec=OperationSpec(
    op_id=None,
    op_type="oracle_answer",
    payload={"eliminate": ["H1"], "observable": "O1"},
    source_id="adapter://demo",
))
```

**Pros of v0's API**

- Reads like code, not data manipulation.
- Argument types catch shape errors at the call site.
- Method name documents intent.

**Cons of v0's API**

- Extending requires adding kernel methods (and new tests, and new
  invariants).
- Composing operations (e.g. "submit five eliminations atomically")
  needs another layer.

**Pros of v2's API**

- Extending is just "add a new op_type and have the reducer handle
  it." No kernel change.
- Operations are first-class data — easy to log, serialize, replay,
  re-route.

**Cons of v2's API**

- Stringly typed (`op_type: str`, `payload: dict[str, Any]`).
- Verbose at call sites; intent is in the payload not the signature.

**Pick:** **Both — typed envelopes as the substrate, imperative
methods as a convenience facade.** Concretely:

```python
class Kernel:
    def submit_probe_result(self, probe_id, observable_id, eliminated):
        return self._append(OperationSpec(
            op_type="probe_result",
            payload={"observable_id": observable_id, "eliminate": list(eliminated)},
            idempotency_key=probe_id,
            source_id="...",
        ))
```

Call sites stay clean; the substrate stays uniform. This is option 3
from the earlier discussion.

### 4. Operation representation

**v0**: each kernel method takes its own positional args. No
provenance metadata beyond `observable_id`.

**v2**: `OperationSpec` envelope: `op_id`, `op_type`, `payload`,
`source_id`, `preconditions`, `commutativity_key`, `idempotency_key`.

**Pick:** v2's envelope. It's a strictly richer model and accepting
extra metadata at the kernel level (`source_id`, `idempotency_key`)
gives you opaque-provenance and idempotency for free.

### 5. Provenance

**v0**: `observable_id: str` is the only metadata attached to an
elimination. Audit records track `verb`/`payload` but the payload
shape is fixed per verb.

**v2**: `source_id: str` (kernel-opaque) and `payload: dict[str,
Any]` for whatever the policy wants to attach (kernel-opaque except
for the small set of keys the reducer reads, like `"eliminate"` and
`"set"`).

**Pick:** v2. We already converged on this in the 0-IG discussion —
opaque provenance per envelope, meaningful only to the domain that
wrote it.

### 6. Empty-elimination / 0-IG recording

**v0**: `submit_probe_result(..., eliminated=set())` is accepted,
consumes the `probe_id`, but no `EliminationEvent` is appended. The
audit silently elides it.

**v2**: every envelope is appended unconditionally; a `refine` op
with `payload["eliminate"] == []` is in the log.

**Pick:** v2. Already-agreed direction.

### 7. Idempotency

**v0**: INV-3 (probe non-repetition) is special-cased — duplicate
`probe_id`s are rejected. No general mechanism for other operations.

**v2**: `idempotency_key` on every envelope; re-submission returns
the original `OpAppendResult` rather than mutating state again.

**Pick:** v2. INV-3 becomes `idempotency_key=probe_id` on the
imperative facade. The mechanism generalizes — useful for any
operation that might be retried.

### 8. Branching

**v0**: not modeled.

**v2**: branches are first-class — `create_branch(from_branch,
from_seq)`. Each branch has its own op_log forked at a sequence
number.

**Pick:** v2. Even if many use cases don't need it, having it as a
capability costs little (the model already supports it). It's the
counterfactual primitive — without it, "what if we'd asked Q5 first"
becomes a re-implementation chore.

### 9. Concurrency / merge

**v0**: no notion. The kernel is single-threaded by design.

**v2**: `merge()` with `policy="refuse_non_commutative"` raises
`409 NON_COMMUTATIVE_CONFLICT` with witness. Commutative merges
succeed.

**Pick:** v2. Required if you have branching at all.

### 10. Reducer versioning

**v0**: there are no reducers — the kernel logic IS the semantics.
Changing semantics is changing code.

**v2**: reducer registry; ops carry `op_type`/`payload`; a reducer
maps the op log to state. Reducers are versioned (`"v1_mask_meet_tombstone"`).

**Pick:** v2. The version string lets you say "this log under
reducer v1.2 produces state S" — a stronger replay claim than v0
can make.

### 11. Persistence SPI

**v0**: `EliminationStore` Protocol with five methods
(`create_session`, `eliminate`, `get_survivors`, `get_eliminated`,
`recover`); `InMemoryStore` implementation.

**v2**: nothing — `OplogServer` holds everything in-memory.

**Pros of v0's choice**

- Real `typing.Protocol`-shaped SPI.
- Implementations are obvious (Redis, Postgres, file, etc.).
- Recovery path returns `RecoveredState` — clean shape.

**Cons of v0's choice**

- Models *tombstones*, not the full op stream. Doesn't fit the v2
  reducer-derived model.

**Pick:** **v0's SPI shape, adapted to the log.** What we want is an
`OpLogStore` Protocol with methods like `append_op(sid, branch_id,
envelope)`, `read_ops(sid, branch_id, from_seq, to_seq)`,
`create_session(sid, …)`, `recover(sid) -> SessionRecord`. Same
spirit as `EliminationStore` but the unit of persistence is the
envelope, not the tombstone.

### 12. Obligations

**v0**: `enter_obligation(obligation_id, min_eliminations)` /
`request_obligation_exit(obligation_id)`. INV-6 enforces non-trivial
exit.

**v2**: no equivalent.

**Pros of v0's choice**

- Encodes a real, general workflow rule: you cannot exit an
  obligation without paying for it in eliminations.
- Catches "premature done" bugs structurally.
- Domain-independent — applies to any monotone-elimination
  workflow.

**Cons of v0's choice**

- Adds kernel surface area (state + methods).
- The "what does an obligation mean to the user" mapping is policy.

**Pick:** **Keep obligations.** Implement as op_types
(`enter_obligation`, `exit_obligation`) plus reducer logic that
gates exit on eliminations-within-scope. The invariant lives in the
reducer; the policy-facing API stays imperative.

### 13. Termination & stability

**v0**: `request_termination()` + `declare_conclusion(id)` +
`stability_window` constructor arg. INV-2 enforces N consecutive
identical conclusions before termination is permitted.

**v2**: no equivalent. There is no "terminated" state in the kernel.

**Pick:** **Keep termination + stability.** Same shape as
obligations — op_types + reducer-enforced invariant. Stability
window stays opt-in (0 disables, matching v0).

The unresolved policy disagreement
([REVIEW_FOR_DELETION.md](../REVIEW_FOR_DELETION.md): spec vs
belief_server vs core disagree three ways) is a separate question
about *what termination should mean*. It's adjacent to this
unification but not blocked by it.

### 14. Entropy

**v0**: `entropy` property on `CMBSCore`, computed as
`log₂(|survivors|)`. INV-5a tests assert it's queryable but
never gating.

**v2**: not exposed; survivors count is available from the reducer
output (`n_survivors`).

**Pick:** add `entropy` as a derived property on the state
projection returned by the reducer (or as a helper). Cheap, matches
v0's B-NONGATE guarantee.

### 15. Test coverage

**v0**: 49 invariant tests in `tests/test_v0_core.py` plus dependent
tests in other files.

**v2**: 8 tests in `tests/test_oplog_server_v2.py`.

**Pick:** before any unification ships, port v0's 49 invariant tests
to the unified model. The invariants don't change; the assertions
just operate on the new surface. This is the test work that will
catch any semantic regression during the rewrite.

## What "best of each" actually looks like

A unified kernel keeps the v2 substrate (envelopes, op log, reducer,
branches, idempotency, hash chain) and adds:

- An imperative facade exposing v0-style methods
  (`submit_probe_result`, `enter_obligation`, `declare_conclusion`,
  `request_termination`) that internally `append_op` with the right
  envelope shape.
- New op_types for the workflow primitives: `enter_obligation`,
  `exit_obligation`, `declare_conclusion`, `request_termination`.
- A reducer that enforces INV-3, INV-6, INV-2 as it consumes the log
  (rejecting the op rather than mutating state when violated).
- An `OpLogStore` Protocol shaped after `EliminationStore`, with an
  in-memory implementation.
- A `BeliefSnapshot`-like view derived from the reducer state, with
  an `entropy` property.

Conceptually: one kernel, two API styles (imperative facade and raw
envelope append), one substrate.

## What to call it

"v0"/"v2" goes away. The replacement names matter less than dropping
the false versioning. Candidates:

- `cmbs.kernel` (the unified kernel) + `cmbs.session` (session
  manager) + `cmbs.store` (persistence SPIs).
- Keep `cmbs.core` but document it as "the kernel" without a v0
  label.
- Drop "BeliefServer" / "OplogServer" entirely in favor of a single
  `Session` or `KernelServer` class.

HTTP routes: `/v1/*` and `/v2/*` should become `/sessions/*` and
`/sessions/.../ops/*` — REST-ish, no version theater. We'd lose
backward compatibility, which is fine because the API isn't
published yet.

## Open questions

1. **Single-session vs multi-session.** v0's `CMBSCore` is
   single-session; sessions live in `BeliefServer`. v2's
   `OplogServer` is multi-session. Should the unified kernel be
   multi-session at the bottom (simpler total surface) or
   single-session with a session-manager above (matching v0)?
2. **Reducer pluggability scope.** v2 supports multiple reducers
   per server (`default_reducer` per session). Do we need that, or
   is one reducer enough for a v1 unified release?
3. **HTTP API.** Do we ship one? If yes, what's the route shape now
   that we've dropped v1/v2 prefixes? If no, what's the simplest
   in-process API surface?
4. **Persistence at launch.** Ship only `InMemoryOpLogStore` and
   document the SPI for external implementations? Or also ship a
   file-backed reference store?
5. **Migration story for already-merged v0/v2 callers.** The
   answer is "none — nobody's seen this yet, break freely." Worth
   confirming.

## Recommended next steps

1. Confirm direction with a short ADR-style decision: "We will
   unify v0 and v2 into a single kernel with v2 substrate + v0
   workflow primitives + imperative facade." Land it in
   `design/` and reference it from `CHANGELOG.md`.
2. Port v0's 49 invariant tests to the unified surface *first* —
   pin the desired behavior before any implementation moves.
3. Implement the unified kernel on a fresh branch. Keep the
   existing v0 and v2 modules in place until the new one is at
   parity.
4. Switch `examples/` and `cmbs/belief_api.py` to the unified
   surface. Delete v0 and v2 modules in the same PR or a
   follow-up.
5. Rewrite `docs/architecture.md`, `docs/use-cases.md`,
   `docs/reference/api.md` against the unified surface.
