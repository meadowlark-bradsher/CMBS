# Capabilities and decisions

An inventory of everything CMBS does as of 0.2.0, and the recorded reasons it
does no more. The capabilities come from the code and the
[API reference](reference/api.md); the decisions come from the design records
under `design/`, the changelog, the merged pull-request descriptions, and the
[weekly recap of 12 November 2026](recaps/2026-11-12-weekly-recap.md).
Nothing here was inferred from memory, and the last section says what could
not be recovered.

## What CMBS is

CMBS (Constraint Mask Belief System) is a Python library that keeps "what has
been ruled out, and why" out of an LLM prompt and in an inspectable,
replay-auditable state machine. One `Session` is one investigation over a
finite set of opaque hypothesis IDs. Adapters submit eliminations; the kernel
books them into an append-only operation log, derives the surviving set from
that log, enforces a small set of invariants, and hashes every step so a third
party can replay the log and check the result.

The design is governed by one boundary, stated in the first architecture note
and kept through every release since: **the kernel is mechanism, not policy.**
It tracks hypotheses, records eliminations, computes entropy, and enforces
obligation discipline. It never executes or schedules probes, never chooses the
next action, never interprets an observable, a hypothesis, or a conclusion,
never holds probabilities, and never decides on its own that an investigation
is finished. All of that belongs to adapters and the surrounding agent. The
capabilities below are what the kernel does; the decisions after them are why
it does no more.

As of 15 November 2026 the released version is 0.2.0 (8 November 2026),
Apache 2.0, Python 3.10 to 3.12, one runtime dependency (`pyyaml`), 302 tests.

## Capabilities 1: the kernel

The kernel is `Session`, one instance per investigation. Everything it knows
is `reduce(initial_hypotheses, op_log)`: a session holds no mutable belief
state of its own, only a cached snapshot that always equals a full fold of the
log.

**Belief tracking.** A session starts from a finite universe of opaque
hypothesis IDs and exposes `survivors`, `eliminated`, `entropy` (log₂ of the
survivor count), and an immutable `Snapshot` of the whole state at the current
log position. IDs for hypotheses, probes, observables, conclusions,
obligations, and sources are strings the kernel never parses. An optional
`OntologyBundle` records which hypothesis registry and version the session was
built against, for audit only.

**The imperative facade.** Six calls cover the normal loop; each one appends a
typed operation and returns a result with the reducer's verdict.

| Call | What it books | Result |
| --- | --- | --- |
| `submit_probe_result(probe_id, observable_id, eliminated, ...)` | An elimination set from one probe, keyed by `probe_id` | `ProbeResult` with `eliminated` and `already_eliminated` |
| `enter_obligation(id, min_eliminations, semantics=...)` | Opens a scope that must earn N eliminations before it may close | `AppendResult` |
| `request_obligation_exit(id)` | Asks to close the scope; refused under threshold | `ObligationExitResult` |
| `declare_conclusion(conclusion_id)` | Appends to the conclusion history | `AppendResult` |
| `request_termination()` | Marks the session terminated; gated by the stability window | `TerminationResult` |
| `reinstate(seq)` / `reinstate_probe(probe_id)` | Voids one earlier elimination (opt-in reducer only) | `ReinstateResult` |

Below the facade sits `append(OperationSpec)` for callers who build envelopes
directly, with `source_id`, an opaque `provenance` payload, and optional
`op_id` and `idempotency_key`.

**The op log.** Every submitted operation, accepted or rejected, becomes an
`OperationEnvelope` in the log with its verdict and a reason. There is no
separate audit structure that can drift from the state: the log is the audit
trail. `operations(from_seq, to_seq)` reads it back. Two kinds of repeat are
told apart: a repeated caller-supplied `op_id` is a transport retry and returns
the original envelope without appending, while a repeated `idempotency_key` is
a domain repeat and appends a new rejected envelope so the attempt is visible.

**Enforced invariants.** The reducer's `check` step decides acceptance at
append time; only accepted operations change belief.

| ID | Name | Rule |
| --- | --- | --- |
| INV-3 | Probe non-repetition | An op whose idempotency key was already consumed is rejected and logged. The facade keys `probe_result` ops by `probe_id`, so an agent cannot ask the same question twice |
| INV-6 | Non-trivial exit | `exit_obligation` is accepted only once `min_eliminations` have been recorded after the matching `enter_obligation` |
| INV-2 | Stability window (opt-in) | `request_termination` is accepted only if the last N declared conclusions are identical; N = 0 disables the gate |
| INV-5a | Entropy quantification | `entropy` is always computable and never used as a gate; non-increasing under the default reducer |

The gaps in the numbering are inherited from the original v0 specification.
INV-2, 3, 5a and 6 are the ones the kernel enforces, and no record of what the
other numbers named survives in the repository.

**Boundary properties** are tested as hard as the invariants: identifiers are
opaque (B-OPAQUE), termination is allowed at any survivor count including zero
(B-NONSINGLETON), conclusions are not assumed binary (B-NONBINARY), the API is
observation-only with no attempt or success states (B-NONEXEC), obligations and
termination are initiated by the caller and never self-trigger (B-ADAPTER), and
entropy is diagnostic only (B-NONGATE).

**Obligations, conclusions, termination.** An obligation is a named scope with
a threshold. Any newly eliminated hypothesis, whatever operation removed it,
counts toward every obligation open at the time. Re-entering an open
obligation is rejected; re-entry after a permitted exit starts a fresh scope.
Termination does not freeze the session, can be re-requested idempotently, and
does not require closed obligations or a single survivor.

## Capabilities 2: reinstatement

By default survivors only shrink. `ReinstatingMaskReducer` (version string
`v2_mask_reinstate`, added in 0.2.0) is an opt-in sibling of the default
reducer under which an elimination can be voided by a logged `reinstate` op
while the log and the record set stay monotone. Pass it to the `Session`
constructor to enable it.

**Record sets, not a mutable mask.** Every accepted elimination records a
`(seq, hypothesis)` pair for each hypothesis it asserted dead, whether or not
that hypothesis was still a survivor. A hypothesis is eliminated iff at least
one pair naming it is in force. The two sets `asserted_pairs` and
`reinstated_pairs` only grow; the survivor set is a derived view that can move
back up the lattice. Consequences the tests pin:

- Reinstating one of two killers of `H` leaves `H` dead (INV-R2).
- A `reinstate` targets exactly one accepted elimination envelope, by `seq` or
  by the `probe_id` it consumed, optionally restricted to a subset of what it
  asserted; each pair is reinstated at most once (INV-R1).
- Reinstatement never touches `attrs` and never un-consumes a probe ID, so
  INV-3 still holds (INV-R3, INV-R4).
- Entropy is non-increasing across any log segment with no accepted
  `reinstate`, and nothing else can raise it (the conditional form of INV-5a).

**Obligation counting semantics.** Under this reducer each obligation declares
at entry how it counts. `gross` is the running in-scope count and ignores
reinstatement (the v1 behaviour). `net`, the default, is the number of
hypotheses dead now that were alive when the obligation opened, so an in-scope
eliminate-then-reinstate earns nothing (INV-O1). A permitted exit leaves a
frozen `ClosedObligation` record with `open_seq`, `exit_seq`, semantics,
threshold, and progress at exit, which no later op can change (INV-O2).
`Session.obligation_progress(id)` reports progress under the declared
semantics.

**Reinstatement budget.** The reducer can bound how much reinstatement a log
may contain, set by constructor:

| Limit | Meaning |
| --- | --- |
| `max_reinstates` | Cap on accepted `reinstate` ops over the session; rejected ones never count (INV-B1) |
| `max_reinstated_pairs` | Cap on voided pairs; an op that would cross it is rejected whole, and re-eliminating a reinstated hypothesis frees nothing (INV-B2) |
| `retractable(recorded)` | A caller predicate over what the snapshot recorded about the target envelope, its `seq` and `weight`; returning `False` rejects (INV-B3) |

A refused reinstate is logged as a rejected envelope with a reason naming the
limit. The budget acts in `check` only, so a budgeted log replays to the same
snapshot under the unbudgeted default and the version string is unchanged
(INV-B4). It is not stored with the session.

**Weight and reason.** `submit_probe_result` accepts an optional numeric
`weight` and string `reason`, copied into the payload only when given. The
kernel never compares, sums, or thresholds a weight; the one thing it does is
record an accepted weight as `Snapshot.weights[seq]` so a budget predicate can
read it. `reason` stays in the payload. Neither changes what is eliminated
(INV-W1).

**Retired ops.** The v1 `retract` and `tombstone` op types, which both meant
"eliminate", are rejected with a reason under this reducer rather than
silently accepted. Other unknown op types remain silent no-ops under both
reducers.

## Capabilities 3: identities, the bounded view, persistence

**Three identities.** A session carries three hashes that answer different
questions. Two live on the snapshot; the third lives on each envelope.

| Hash | Answers | Covers | Changes when |
| --- | --- | --- | --- |
| `state_hash` | Which position in this log? | Survivors, eliminated, consumed keys, obligations, conclusion history, terminated flag, attrs, reducer version, session ID, `seq` | Every append, rejected ones included; never equal across sessions |
| `position_digest` | Which point in the belief lattice? | The sorted survivor set and nothing else | Only when the survivor set changes; equal across sessions with the same survivors |
| `log_hash` | Is this the log that was written? | Every stored field of every envelope, chained: `sha256(previous || canonical(envelope))` from a fixed genesis link | Any edit to any field of envelope *n* moves hashes *n* through the head |

`state_hash` is the audit identity of the state: a reviewer who replays the
handed-over log under the same reducer must land on the same hash at every
step. `position_digest` is the convergence identity: two agents can confirm
they have reached the same frontier without exchanging logs, a
zero-information probe leaves it unchanged, and
`compute_position_digest(a & b)` names the meet of two positions. `log_hash` is
the integrity identity of the record: `Session.append` computes it and
`Session.recover` recomputes and checks the whole chain before replaying,
raising on the first mismatch (INV-H1 tamper evidence, INV-H2 replay
determinism). A log written before the chain existed loads with its unhashed
prefix reported in `unverified_prefix`.

**The bounded view.** `Session.view(k)` returns a JSON-serializable summary
whose size does not grow with the log: survivor count, entropy, position
digest, open obligations with semantics and progress, closed-obligation
records, the numbers of in-force and reinstated pairs, and the last `k`
envelopes reduced to `seq`, `op_type`, `accepted`, `rejected_reason`. It never
carries the survivor list (INV-V1), and it is a pure function of the snapshot
plus those `k` envelopes, identical before and after recovery (INV-V2). This is
the object meant to go into a model-facing prompt.

**Persistence and recovery.** Every envelope goes to an `OpLogStore` as it is
appended. `InMemoryOpLogStore` ships in the box; file, database, or network
stores implement the same five-method protocol outside the package, and a
JSONL store short enough to read in one sitting is
[tutorial 06](tutorials/06-file-backed-store.md).
`Session.recover(store, session_id)` rebuilds a session by replaying its log,
verifies the hash chain first, refuses to replay under a reducer version other
than the one stored, and picks the reducer from a version registry when none is
passed. A recovered session continues the same log: a probe ID consumed before
a crash is still rejected after it. Multiple sessions may share one store, and
each envelope's `source_id` records who contributed it, which is the
integration point for several agents writing to one belief.

## Capabilities 4: extension points and supporting material

Policy sits outside the kernel; the kernel is one `Session` over a reducer and
a store:

1. **Policy and adapters (outside the kernel).** An LLM or a scripted policy
   picks the next probe; the kernel never sees a prompt. Adapters turn an
   observation into an elimination set (Twenty Questions, ITBench, legacy
   replay). The `HypothesisProvider` SPI supplies hypothesis spaces from other
   packages via entry points.
2. **`Session`, the kernel.** The imperative facade over
   `append(OperationSpec)`. Computes the chained `log_hash` per envelope,
   caches the snapshot and advances it one `apply` per append, exposes the
   reads, and replays and verifies on `recover`.
3. **`Reducer`, the versioned fold.** `check()` decides acceptance at append
   time; `apply()` folds one envelope into the snapshot. v1
   `MaskMeetTombstoneReducer` is the monotone default; v2
   `ReinstatingMaskReducer` adds `reinstate` and the budget.
4. **`OpLogStore`, the persistence SPI.** A five-method protocol;
   `InMemoryOpLogStore` ships, other stores live outside. It holds envelopes
   and metadata and never interprets them; the chain is verified on recover.

Everything above the `Session` is policy and lives outside the kernel;
everything below it is a protocol a third party can implement without
touching the kernel.

**Extension points.**

| Point | Shape | What ships |
| --- | --- | --- |
| `Reducer` protocol | `initial`, `check`, `apply`, `reduce`, `classify`, plus a `version` string stored with the session | Two reducers and a version registry (`register_reducer`, `reducer_for_version`, `registered_reducer_versions`) |
| `OpLogStore` protocol | `create_session`, `append`, `read_ops`, `head_seq`, `recover` | `InMemoryOpLogStore`; stores written against the older five-argument `create_session` keep working |
| `HypothesisProvider` SPI | `id`, `version`, `hypothesis_ids`, `probe_ids`, `apply_probe` returning an elimination mask; discovered from the `cmbs.hypotheses` entry-point group | Nothing in the package consumes it; `tests/test_spi.py` shows a provider seeding a session |
| `BeliefAdapter` shape | `list_actions(snapshot)`, `apply_action(id, snapshot)`, `observe(ctx, outcome)` returning eliminate messages | Twenty Questions and ITBench reference adapters, each with YAML kits loadable after `pip install` via `load_builtin_kit` |
| `LegacyReplayAdapter` | Forwards pre-CMBS elimination events to `submit_probe_result` with no validation | Audit continuity for existing logs |

**Supporting material.** Six runnable [tutorials](tutorials/index.md) (kernel
basics, LLM Twenty Questions, LLM incident triage, two-agent convergence,
audit and replay, a file-backed store); the three LLM ones drive the
investigation with Claude through the `anthropic` SDK when a key is visible
and fall back to a scripted policy otherwise, and the test suite runs all six
offline. Two end-to-end examples. This site, with a full
[API reference](reference/api.md), an
[invariant test matrix](reference/invariant-test-matrix.md), a walkthrough
page per tutorial with captured output, and dated weekly recaps. CI runs
`ruff` and `pytest` on Python 3.10, 3.11 and 3.12 and deploys the docs from
`main` with a strict build.

## Decisions 1: the foundations

These decisions set the shape of the library. The first predates the public
repository; the rest were taken in May 2026 when two parallel kernels were
unified, and are recorded in
[design/kernel-comparison.md](https://github.com/meadowlark-bradsher/CMBS/blob/main/design/kernel-comparison.md),
[ADR-001](https://github.com/meadowlark-bradsher/CMBS/blob/main/design/adr-001-unify-kernels.md)
and
[ADR-002](https://github.com/meadowlark-bradsher/CMBS/blob/main/design/adr-002-naming.md).

- **The kernel is mechanism, not policy.** Recorded in the original v0
  architecture note and enforced by the boundary tests ever since. The
  reason: CMBS is meant to sit alongside frozen or learning agents, not inside
  them, so anything domain-specific (what an observable means, when to stop,
  which obligation types exist) must be an adapter concern or the kernel
  stops being reusable. Every later decision below was checked against this
  one, and the pull-request template has a "Boundary impact" section for that
  purpose.

- **State is the reduction of an append-only log.** The two earlier kernels
  disagreed here: v0 kept mutable state on an object with a side audit log,
  v2 derived state from an op log through a versioned reducer. The comparison
  chose v2's model because a side log is redundant and can diverge from the
  state it describes, while a log that causes the state cannot lie about it;
  replay comes free, and a version string turns "we replayed this log and got
  state S" into a verifiable claim. The cost, more expensive reads, is paid
  once per append by caching the snapshot and advancing it one `apply` step
  at a time.

- **Typed envelopes underneath, an imperative facade on top.** v0 had
  readable method calls; v2 had extensible envelopes but stringly-typed call
  sites. ADR-001 took both: each facade method translates to one `append`, so
  call sites keep typed signatures while adding a new op type needs no kernel
  change.

- **v0's workflow primitives survive as op types.** Obligations, conclusions,
  termination and the stability window were absent from the v2 prototype.
  They were ported because they encode general guardrails, above all "you
  cannot exit a scope without paying for it in eliminations", which catches
  confidently-wrong-and-done failures structurally rather than by prompt
  instruction.

- **One session per investigation; no session manager.** The v0
  `BeliefServer` and v2 `OplogServer` both multiplexed sessions. ADR-001
  dropped that layer: users compose sessions themselves, and if aggregation
  across investigations is ever needed it deserves its own design rather than
  a dictionary with queries.

- **Library only.** The FastAPI surface, Dockerfile, and `fastapi`,
  `pydantic` and `uvicorn` dependencies were removed. No consumers existed,
  "Belief Server" was misleading without HTTP, and client-server access is
  additive on top of the same kernel when a distributed scenario actually
  needs it. Runtime dependencies went to `pyyaml` alone.

- **One reducer at launch, with its version string kept.**
  `MaskMeetTombstoneReducer` shipped because it already supported conditional
  `refine` eliminations. Its string `v1_mask_meet_tombstone` was kept even
  though the class name dropped the prefix, because the string is a replay
  tag on persisted sessions.

- **The persistence SPI keeps v0's shape, adapted to the log.** v2 had no
  persistence interface at all. `OpLogStore` follows v0's `EliminationStore`
  protocol pattern but persists envelopes rather than tombstones; only the
  in-memory implementation ships, and a file-backed store was explicitly
  deferred.

- **Names (ADR-002).** `Session` for the kernel class because an instance is
  an investigation and the package qualifier is Python's disambiguation tool;
  `BeliefSession` rejected as verbose, `Kernel` because it names a role not an
  instance, `CMBSCore` because "core" implies a surrounding layer that no
  longer exists. `Snapshot` over `Projection` because the docs do not present
  CMBS as event-sourcing. `OpLogStore` over `Journal` to keep "store of
  envelopes" legible. One concept per type: `AuditEntry` and
  `EliminationEvent` were subsumed by the envelope, since the log is the
  audit.

- **Break freely, remove outright.** Because no published consumers existed,
  the whole v0 and v2 surface was removed rather than deprecated, and the
  "v0"/"v2" nomenclature was dropped as residue of development caution with
  no real version between them.

- **Unify rather than freeze or rename.** Freezing one kernel would strand the
  workflow primitives on the wrong side; keeping both doubles the test and
  documentation burden forever; renaming alone leaves the duplication. The
  cost of unification was bounded, the cost of perpetual duplication was not.

## Decisions 2: kernel semantics

These were settled while implementing the unified kernel (September 2026,
pull requests
[#7](https://github.com/meadowlark-bradsher/CMBS/pull/7),
[#8](https://github.com/meadowlark-bradsher/CMBS/pull/8) and
[#10](https://github.com/meadowlark-bradsher/CMBS/pull/10)) and are recorded
in the PR descriptions, the [architecture page](architecture.md), and the
kernel test suite.

- **Every attempt is logged, including rejections.** A duplicate probe appends
  a new rejected envelope rather than silently returning the earlier result,
  because "audit everything" was the stated principle and the ported INV-3
  test expects `accepted is False`. The same rule covers empty eliminations,
  which v0 had silently dropped: a probe that eliminates nothing is still a
  logged step.

- **Two dedupe rules with different meanings.** A repeated caller-supplied
  `op_id` is a transport retry and returns the original envelope without
  appending. A repeated `idempotency_key` is a domain repeat and is rejected
  on the record. Conflating them would either hide repeats from the audit or
  make retries unsafe.

- **The verdict is decided once, at append time, and persisted.** The
  `Reducer` protocol grew `initial`, `check` and `apply`, with `reduce` as the
  fold over the full log. Rejected envelopes only advance `seq` and rehash.
  This is what lets a log replay identically under any configuration that
  only changes acceptance (see the budget decision below).

- **Re-entering an open obligation is rejected**, where v0 silently reset its
  scope. Re-entry after a permitted exit starts a fresh scope.

- **Termination semantics are provisional and deliberately the least
  restrictive.** The v0 specification, server and core disagreed three ways
  about what termination should require. Rather than resolve that inside the
  unification, the kernel gates termination only on the stability window,
  does not require closed obligations or a single survivor, does not freeze
  the session, and can be re-requested. A follow-up ADR is still owed;
  callers who need stricter gating enforce it in their own loop.

- **Branching and merge were not carried over.** The v2 prototype had
  first-class branches, a merge that refused non-commutative histories, and
  commutativity analysis. They left with `OplogServer`. The op log keeps them
  reintroducible as a layer on top, so the gap is recorded in the changelog
  and in the [use-cases page](use-cases.md) ("fork and compare alternate
  orderings" moved to the does-not-fit table) rather than ported
  speculatively.

- **`state_hash` covers belief, reducer version, session ID and position.**
  Same belief at the same position of the same session hashes equal
  regardless of the order keys were consumed in; it differs across sessions
  by construction, which is what makes it an audit identity and not a
  convergence identity.

- **`position_digest` covers the sorted survivor set and nothing else.** The
  universe is excluded because the position is the subset (pair it with
  `initial_hypotheses` when the lattice matters); obligations, conclusion
  history and `attrs` are excluded because they are workflow state layered on
  the lattice, not belief. The digest changes no verdicts and no hashes.

- **Entropy is diagnostic, never gating.** It is always computable, and the
  kernel never auto-terminates on entropy or on a singleton survivor.
  Stopping is the caller's call.

- **`HypothesisProvider` was kept although nothing in the package consumes
  it.** ADR-002 judged a plugin point for external hypothesis spaces worth
  keeping; a test shows the intended pattern.

- **Reference kits load through `importlib.resources`.** Examples had used
  repo-relative paths and broke after `pip install`. In passing, the Twenty
  Questions kits had never loaded at all: YAML 1.1 reads bare `yes:` and `no:`
  keys as booleans. The loader now normalises outcome keys and validates that
  both outcomes are present.

- **The LLM tutorials show the model every question, asked or not.** The
  point is that INV-3 refuses the repeat rather than the prompt preventing
  it; a test drives a policy that insists on repeating and asserts the kernel
  refuses. The tutorials fall back to a scripted policy without a key, so the
  suite runs them all offline, and the file-backed store in tutorial 06 is
  explicitly user code demonstrating the SPI, not the deferred in-package
  deliverable.

## Decisions 3: retractable eliminations (0.2.0)

The 0.2.0 work (8 November 2026, pull requests
[#12](https://github.com/meadowlark-bradsher/CMBS/pull/12),
[#13](https://github.com/meadowlark-bradsher/CMBS/pull/13) and
[#14](https://github.com/meadowlark-bradsher/CMBS/pull/14)) came from a
four-draft requirements spec agreed in conversation; the spec text itself is
not in the repository, but its decisions are recorded in the PR descriptions,
the changelog, and the
[weekly recap of 12 November](recaps/2026-11-12-weekly-recap.md).

- **The problem was to make an elimination retractable while the lattice
  stays monotone.** The resolution: move the monotone object one level down.
  What only grows is the pair of record sets, every `(seq, hypothesis)` an
  elimination asserted and the subset a `reinstate` has voided. The survivor
  set becomes a derived view that may move back up. This keeps every replay
  and hashing guarantee intact because the log and the records never shrink.

- **Record every asserted hypothesis, not only the newly removed ones.**
  Otherwise reinstating one killer could revive a hypothesis another killer
  still holds. The property test checks this with random sequences.

- **A new sibling reducer rather than a change to the default.**
  `ReinstatingMaskReducer` has its own version string, and a
  version-to-reducer registry lets `Session.recover` select by what was
  stored. Existing sessions and their hashes are untouched.

- **New snapshot fields enter the state hash only when non-empty.** This is
  the rule that kept v1 hashes byte-identical through three feature PRs, and
  a test pins one v1 hash on a fixed log to prove it. The weekly recap lists
  it first among the decisions worth remembering.

- **`net` is the default obligation semantics.** An obligation that counts
  gross progress would be satisfied by an elimination that was later
  reinstated inside its scope. `net` measures what is dead now that was alive
  at entry, so a round trip earns nothing; `gross` remains available and is
  the v1 behaviour.

- **Closed obligations become frozen records.** A successful exit writes a
  `ClosedObligation` keyed by `(id, open_seq)` that no later op can change, so
  re-entry cannot rewrite history.

- **The retired `retract` and `tombstone` ops are rejected with a reason, not
  ignored.** Both had meant "eliminate" under v1. Under the new reducer a
  silent no-op would hide a caller's mistake; other unknown op types stay
  silent no-ops as documented.

- **Reinstatement never un-consumes a probe ID.** INV-3 is about asking, not
  about the answer standing. Reinstating an answer does not make the question
  askable again.

- **The budget acts in `check` only, so it is not part of the version and not
  persisted.** `apply` is the same fold whatever the limits, and the verdicts
  are already on the envelopes, so a budgeted log replays to the same
  snapshot under the unbudgeted default. Recovery through the registry
  therefore yields an unbudgeted reducer, and a caller who wants the limits
  kept passes the budgeted instance explicitly. The budget is mechanism: the
  kernel bounds and refuses, it never decides to reinstate.

- **`weight` and `reason` are opaque, with one narrow exception.** The kernel
  never compares or thresholds a weight; it records an accepted one on the
  snapshot only so a caller-supplied `retractable` predicate can read it.
  `reason` is never read at all. Both are absent from the payload unless
  given, so existing envelopes are byte-identical.

- **The bounded view never carries the survivor list.** `view(k)` exists so a
  model-facing prompt stays O(1) in log length; including survivors would
  reintroduce growth with the universe.

- **`log_hash` is separate from `state_hash`.** They answer different
  questions: the state hash covers what the reducer projects (a `provenance`
  edit leaves it unchanged) and does not chain; the log hash covers every
  stored byte of every envelope and chains, so any edit moves every later
  link. Computing it in `Session.append` rather than the reducer keeps the
  reducer from ever constructing envelopes.

- **`created_at` is hashed from the record, not the clock**, so the chain
  recomputes exactly from persisted envelopes.

- **A legacy prefix loads unverified and says so.** Logs written before the
  chain existed have `log_hash = None`; recovery accepts a leading run of
  them, reports the count in `unverified_prefix`, and verifies from the first
  hashed envelope. A missing hash after the chain has started is a broken
  chain. One test records the scheme's honest limit: a consistent rewrite of
  a whole suffix passes the chain but cannot keep the head hash, so a head
  recorded out of band still exposes it.

- **`admit`, the open-world op that would let a hypothesis enter after the
  session starts, stays deferred.** CMBS is closed-world by design; nothing on
  `main` starts it.

## Open questions and deliberate gaps

Some of these are deferred work; others are boundaries CMBS will not cross.

| Item | Status | Where recorded |
| --- | --- | --- |
| Termination and conclusion-gating policy | Provisional, least restrictive; a follow-up ADR is owed | ADR-001 risks; [architecture](architecture.md) "Provisional semantics" |
| File-backed `OpLogStore` in the package | Deferred; tutorial 06 shows one as user code | ADR-001 deferred list; PR #10 notes |
| Multi-session manager | Deferred; compose sessions yourself | ADR-001 decision 4 |
| HTTP or gRPC client-server | Deferred; additive on top of the kernel | ADR-001 decision 6 |
| Branching, merge, commutativity analysis | Dropped with the v2 prototype; rebuildable on the log, nothing ships | PR #8 notes; changelog 0.2.0 Removed |
| `admit` (open-world hypothesis entry) | Deferred | Weekly recap, 12 November |
| `DefaultReducer` alias | Deferred pending user feedback | ADR-002 open items |
| Numbered slots for INV-R, INV-O, INV-B, INV-V, INV-W, INV-H | Namespaced until given numbers | [Invariant test matrix](reference/invariant-test-matrix.md) |
| Naming irony: the reducer named for tombstones keeps none; the one that keeps records is named for `reinstate` | Accepted, because the version string is a replay tag | ADR-002 open items |

**What CMBS will not do**, by design rather than by omission: hold probability
distributions (use a Bayesian framework), combine soft constraints
continuously (use a solver), discover hypotheses mid-run (closed world), model
arc-consistent constraint graphs, or replace a plain dict when only last-turn
memory is needed. The [use-cases page](use-cases.md) keeps a fits and
does-not-fit table for this.

## Where the record lives

Everything above was taken from the repository at tag `v0.2.0` plus the
merged pull-request descriptions.

| Source | What it holds |
| --- | --- |
| [design/kernel-comparison.md](https://github.com/meadowlark-bradsher/CMBS/blob/main/design/kernel-comparison.md) | The fifteen-dimension comparison of the v0 and v2 kernels, with a pick and reasoning per dimension |
| [design/adr-001-unify-kernels.md](https://github.com/meadowlark-bradsher/CMBS/blob/main/design/adr-001-unify-kernels.md) | The eight unification decisions, alternatives rejected, deferred questions, and the six-step plan |
| [design/adr-002-naming.md](https://github.com/meadowlark-bradsher/CMBS/blob/main/design/adr-002-naming.md) | Every public name, the alternatives rejected for each, removed concepts |
| [Architecture](architecture.md) | Mechanism vs policy, the invariants, the three identities, provisional semantics |
| [API reference](reference/api.md) | Every exported symbol, the op-type table, the hash schemes, the budget |
| [Invariant test matrix](reference/invariant-test-matrix.md) | Which tests pin which invariant and boundary property |
| [Use cases](use-cases.md) | Fits and does-not-fit tables, what the caller must bring |
| [CHANGELOG.md](https://github.com/meadowlark-bradsher/CMBS/blob/main/CHANGELOG.md) | 0.1.0 and 0.2.0 with Added, Changed and Removed |
| [Weekly recap, 12 November 2026](recaps/2026-11-12-weekly-recap.md) | The 0.2.0 phases and the decisions worth remembering |
| Pull requests [#7](https://github.com/meadowlark-bradsher/CMBS/pull/7), [#8](https://github.com/meadowlark-bradsher/CMBS/pull/8), [#10](https://github.com/meadowlark-bradsher/CMBS/pull/10), [#12](https://github.com/meadowlark-bradsher/CMBS/pull/12), [#13](https://github.com/meadowlark-bradsher/CMBS/pull/13), [#14](https://github.com/meadowlark-bradsher/CMBS/pull/14) | Reviewer notes recording the judgement calls made during implementation |

Two records were not recoverable. The 0.2.0 requirements spec (four drafts)
was agreed in conversation and never committed, so its decisions are known
only through the PR descriptions that implemented it. `REVIEW_FOR_DELETION.md`,
which logged the three-way disagreement on termination semantics between the
v0 spec, server and core, was gitignored and never committed, so the detail of
that disagreement survives only as ADR-001's one-line reference to it. The
pre-unification design vault (`docs-vault/`) was untracked for the open-source
release; its architecture note is still in git history and is the source for
the mechanism-not-policy origin above.
