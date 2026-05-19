# ADR-002: Names for the unified kernel

**Status:** Accepted (2026-05-18).

**Builds on:** [ADR-001 — Unify v0 and v2 into a single kernel](adr-001-unify-kernels.md).

## Context

ADR-001 decided that the v0 and v2 kernels would be unified under a v2
substrate with v0's workflow primitives ported on top, exposed via an
imperative facade. Naming was explicitly deferred to a follow-up.

This ADR makes those naming decisions before any implementation moves.
No published consumers exist; breaking changes are free.

## Decision

| Concept | New name | Notes |
|---|---|---|
| The kernel class (one instance = one investigation) | **`Session`** | A "session" *is* an instance of the unified kernel. Users write `from cmbs import Session; s = Session(hypothesis_ids={...})`. |
| The kernel module | **`cmbs/session.py`** | Mirrors the class. |
| Operation envelope (client-submitted) | **`OperationSpec`** | Kept from v2. Established and accurate. |
| Operation envelope (persisted, with seq/timestamps) | **`OperationEnvelope`** | Kept from v2. The spec→envelope distinction is meaningful. |
| The shipped reducer | **`MaskMeetTombstoneReducer`** | `V1` prefix dropped from the class name. The version string `"v1_mask_meet_tombstone"` stays on the envelope for replay tagging. |
| Reducer protocol | **`Reducer`** | Already a `typing.Protocol`. |
| Persistence SPI | **`OpLogStore`** | Persistence unit changes from "tombstones" to "op envelopes." Parallel to v0's `EliminationStore` shape. |
| In-memory persistence impl | **`InMemoryOpLogStore`** | Explicit about what it stores. Replaces the ambiguously-named `InMemoryStore`. |
| Recovery return type | **`RecoveredSession`** | Recovers a session, not a free-floating state. |
| State snapshot type | **`Snapshot`** | One kind; no qualifier needed. Returned by `session.snapshot()`. |
| Ontology container | **`OntologyBundle`** | Kept from v0/v2. Passed to `Session(ontology=...)`. |
| Hypothesis provider SPI | **`HypothesisProvider`** | Kept from v0. Still needed for plugin hypothesis spaces. |
| Append result type | **`AppendResult`** | Shortened from `OpAppendResult` — the `Op` prefix is redundant in module context. |
| Probe result type | **`ProbeResult`** | Kept from v0. Reads well at call sites. |
| Obligation exit result | **`ObligationExitResult`** | Kept from v0. |
| Termination result | **`TerminationResult`** | Kept from v0. |

## Removed concepts

The following v0/v2 types are explicitly *not* part of the unified API.
Their function is subsumed elsewhere:

- **`CMBSCore`, `OplogServer`** → replaced by `Session`.
- **`BeliefServer`** → no longer needed (single-session kernel; users compose multiple sessions themselves).
- **`BeliefState`** → was only a thin wrapper around `CMBSCore`; folded into `Session`.
- **`AuditEntry`** → subsumed by `OperationEnvelope` + per-envelope `state_hash_after`. The op log *is* the audit.
- **`EliminationEvent`** → subsumed by `OperationEnvelope` of the appropriate `op_type`.
- **`EliminationProvenance`, `EliminationResult`, `RecoveredState`** → subsumed by `OperationEnvelope.source_id`/`payload` and by `RecoveredSession`.
- **`BeliefSnapshot`** → renamed to `Snapshot`.
- **`OpAppendResult`** → renamed to `AppendResult`.
- **`BranchRecord`, `SessionRecord`** → internal to `OpLogStore` implementations; not part of the public surface.

`V1MaskNoRefineReducer` is retained as a **test fixture only**, not as a public name. If it's needed for replay-comparison tests it lives under `tests/` or in a designated test-utilities module.

## Consequences

### Positive

- One concept per type. No more parallel v0/v2 versions of the same idea.
- `Session` as the central name reads naturally at every call site: "create a session, submit operations, query its state."
- `OperationSpec` / `OperationEnvelope` / `Reducer` / `OpLogStore` form a coherent event-sourcing vocabulary that the existing v2 code already uses internally.
- Old "Belief Server" language goes away entirely. Project name stays "Constraint Mask Belief System (CMBS)."

### Negative / costs

- Every test, example, doc, and downstream caller (none exist externally yet) must be updated.
- `Session` is a relatively common class name and may collide with `sqlalchemy.orm.Session` etc. if user code imports both unqualified. Recommendation in docs: import as `from cmbs import Session as CMBSSession` when ambiguity exists, or import the module and use `cmbs.Session`.

## Alternatives considered

### For the kernel class

- **`BeliefSession`** — disambiguates from other libraries' `Session`. Rejected as needlessly verbose given that the package qualifier (`cmbs.Session`) is the standard disambiguation tool in Python.
- **`Kernel`** — names the role rather than the instance. Rejected because the instance *is* a session; naming for the role obscures what users actually create and pass around.
- **`CMBSCore`** — keeps the v0 name. Rejected because "core" implies layering ("core of what?") that the unified design doesn't have — there's no surrounding layer anymore.

### For the snapshot type

- **`Projection`** — precise event-sourcing term for "what a reducer produces from a log prefix." Rejected because the term is unfamiliar to users not coming from event-sourcing backgrounds, and CMBS isn't presented as event-sourcing in the user docs.
- **`BeliefSnapshot`** — kept v0's qualifier. Rejected because there is only one kind of snapshot; the qualifier is noise.

### For the reducer class

- **`Reducer`** (plain, with no semantic suffix) — works for v1 since only one ships. Rejected because the precise-semantics name (`MaskMeetTombstoneReducer`) communicates what's being computed and leaves room for siblings to be named honestly later (e.g. `BayesianMixingReducer` is clearly different, where `Reducer` vs `OtherReducer` would be opaque).
- **`DefaultReducer`** alias — considered as a friendly shorthand. Deferred until v1 ships and we see whether users care.

### For the persistence SPI

- **`Journal`** — short, evocative. Rejected as too generic; `OpLogStore` keeps the "store of envelopes" semantics legible.
- **`OperationStore`** — verbose. Rejected on length grounds.

## Open / deferred

- Whether to export `DefaultReducer` as an alias for `MaskMeetTombstoneReducer`. Decide based on v1 user feedback.
- Whether the legacy-replay adapter survives the unification with the same name (`LegacyReplayAdapter`) or gets a refresh. Likely keeps the name; deferred to the migration PR.

## Where this gets used

The names land in this order, per ADR-001's implementation plan:

- **Next unit (API skeleton):** all the public names defined here appear as empty class/function stubs with docstrings in `cmbs/session.py` and friends. No behavior yet.
- **Test port:** v0's invariant tests are rewritten to import from the new names. They will be red.
- **Implementation:** make them pass.
- **Migration & docs:** examples and `docs/` switch to the new vocabulary; old modules deleted.
