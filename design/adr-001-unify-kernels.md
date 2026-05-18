# ADR-001: Unify v0 and v2 into a single kernel

**Status:** Accepted (2026-05-18).

**Reference:** [design/kernel-comparison.md](kernel-comparison.md) for the
full per-dimension analysis that motivates these choices.

## Context

CMBS currently ships two parallel kernels with zero code overlap:

- "v0" — `cmbs.core.CMBSCore` (imperative kernel) plus
  `cmbs.belief_server.BeliefServer` (session manager) and the
  `cmbs.spi.EliminationStore` SPI.
- "v2" — `cmbs.oplog_server.OplogServer` (transcript-conditioned)
  plus `cmbs.op_models.*` and `cmbs.reducers.*`.

The "v0/v2" naming is residue of development caution, not a real
version progression. There is no v1. Three different things called
"v1" appear in the codebase (`/v1/*` HTTP routes for the v0-backed
server, `"v1_mask_meet_tombstone"` reducer version strings, and the
implied v1 in the v0→v2 sequence). Together this is confusing and
unjustified by code reality.

No external consumers exist. Breaking changes are free.

## Decision

1. **Unify under the v2 substrate.** Keep the transcript-conditioned
   model: state is derived from an append-only operation log via a
   versioned reducer. Drop the mutable-kernel pattern from v0 as the
   primary state model.

2. **Port v0's workflow primitives onto the v2 substrate.** The
   invariants v0 enforces — INV-3 (probe non-repetition), INV-6
   (non-trivial obligation exit), INV-2 (termination stability),
   plus the `enter_obligation`/`request_obligation_exit`/`declare_conclusion`/`request_termination`
   methods — become op types and reducer logic. The invariants are
   genuinely general-purpose and worth preserving.

3. **Expose an imperative facade.** Public API stays method-shaped
   (`kernel.submit_probe_result(...)`, `kernel.enter_obligation(...)`,
   etc.). Internally each method translates to an `append_op` call
   against the substrate. Best of both ergonomics: typed signatures
   at the call site, log-derived state under the hood.

4. **Single-session kernel.** The kernel handles one investigation.
   Users compose multiple investigations themselves. Drop the
   session-manager layer (current `BeliefServer` / `OplogServer`
   internal session dict) for v1. If aggregation across
   investigations is needed later, that becomes a new feature with
   its own design — not just a hash-table-with-queries.

5. **One reducer at launch:** `MaskMeetTombstoneReducer` (the richer
   one — supports `refine` for conditional eliminations). The
   `V1MaskNoRefineReducer` becomes a test fixture if retained at
   all. The internal version string stays `"v1_mask_meet_tombstone"`
   for replay tagging.

6. **Library-only at v1.** Delete `cmbs/belief_api.py` and the
   `Dockerfile`. Drop `fastapi` and `uvicorn` from required
   dependencies. HTTP/gRPC client-server can be reintroduced as
   separate work when distributed multi-agent scenarios actually
   need it.

7. **Naming.** Drop "v0" and "v2" from external nomenclature
   entirely. "Belief Server" goes away too — without HTTP, "Server"
   is misleading. The project remains **Constraint Mask Belief
   System (CMBS)**. Final class and module names for the unified
   kernel are deferred to a follow-up decision.

8. **Persistence SPI.** Keep the shape of v0's `EliminationStore`
   Protocol but adapt it to the log model. Define `OpLogStore` with
   methods to append envelopes, read op ranges, and recover full
   session state. Ship only an in-memory implementation at v1.

## Consequences

### Positive

- Single state model. No more "state vs audit can diverge."
- Replay, branching, idempotency, deterministic verification all
  available by construction.
- Smaller install footprint (FastAPI and uvicorn removed).
- The naming finally matches what the code does.
- Future-proof: when distributed scenarios arrive, HTTP/gRPC is
  additive on top of the same kernel — no double-kernel maintenance.

### Negative / costs

- Substantial rewrite. 77 tests today; v0's 49 invariant tests must
  be ported to assert against the new surface.
- The imperative facade adds one indirection vs. direct method
  calls — minor but real.
- Loss of `BeliefServer`'s multi-session-in-process pattern as a
  shipped feature. Users who need that compose it themselves until a
  manager layer is reintroduced.
- HTTP API users (none today) would have to wait for a future
  client-server work item.

### Risks

- Termination-semantics three-way disagreement (logged in
  `REVIEW_FOR_DELETION.md`) is adjacent to this work. The
  unification will surface it. We are explicitly **not** resolving
  it here; the unified kernel will pick one behavior provisionally
  and a follow-up ADR will lock in the policy.

## Alternatives considered

- **Pick one kernel as the canonical, freeze the other.** Considered
  and rejected: the imperative kernel can't grow into branching/
  replay without becoming the v2 kernel anyway. Freezing v0 leaves
  workflow primitives stranded on the wrong side.
- **Keep both kernels and rename for clarity.** Considered and
  rejected: two kernels means twice the test burden, twice the docs
  burden, and ongoing confusion about which to use. The cost of
  unification is bounded; the cost of perpetual duplication isn't.
- **Don't unify; just rename "v0" / "v2" to something more
  descriptive.** Considered and rejected as half-measure. The
  underlying duplication remains the actual problem.

## Deferred / open questions

- Final class and module names for the unified kernel.
- File-backed `OpLogStore` implementation (SPI is defined at v1;
  default implementations beyond in-memory come later).
- Termination/conclusion-gating policy. The v0 spec, server, and
  core disagree three ways. A follow-up ADR will lock this in.
- Multi-session manager. Whether and when to reintroduce.
- HTTP / gRPC client-server. Whether and when to reintroduce.

## Implementation plan

Work proceeds in small, individually reviewable units:

1. **Names.** Decide class/module names for the unified kernel. (One PR.)
2. **Target API skeleton.** Public surface stubs with docstrings, no
   implementation. (One PR.)
3. **Port v0 invariant tests.** Adapt the 49 invariant tests to
   assert against the new surface. They will all fail initially.
   (One PR.)
4. **Implement the kernel.** Make the tests pass. (One PR.)
5. **Migrate examples and remove legacy modules.** Cut over
   `examples/run_20q.py`, `examples/run_itbench.py`. Delete
   `cmbs/core.py`, `cmbs/belief_server.py`, `cmbs/oplog_server.py`,
   `cmbs/belief_api.py`, `cmbs/op_models.py`, `cmbs/reducers.py`,
   `cmbs/belief_state.py`, `cmbs/spi/elimination_store.py`,
   `cmbs/stores/memory.py`, `Dockerfile`. (One PR.)
6. **Update docs.** Rewrite `docs/architecture.md`,
   `docs/use-cases.md`, `docs/reference/api.md`,
   `docs/reference/repository.md`,
   `docs/reference/invariant-test-matrix.md` against the unified
   surface. (One PR.)
