# Belief Server v1 Spec (Next Step)

## 0. Scope

### Goal

Wrap the existing CMBS kernel as a **Belief Server** that:

* owns belief state for a session
* accepts **message verbs** (“belief protocol”)
* produces **auditable**, **replayable** state transitions
* remains **coordination-free** (set-based eliminations only)

### Non-goals (this step)

* no causal graph CRUD
* no Bayesian weights in core
* no constraint propagation in core
* no probe selection logic
* no long-running agent loops

---

## 1. Core Model

### 1.1 Entities

#### Hypothesis Space (immutable per session)

A fixed set of hypothesis IDs.

```yaml
HypothesisSpace:
  id: string
  version: string
  hypotheses: [string]
```

#### Ontology Bundle (immutable per session)

References upstream causal model versions but does not fetch or validate them.

```yaml
OntologyBundle:
  hypothesis_space_id: string
  hypothesis_version: string
  causal_graph_ref: string        # e.g. "graphstore://postgres-repl"
  causal_graph_version: string    # e.g. "v17"
```

#### Belief Session (server-owned mutable state)

```yaml
BeliefSession:
  session_id: uuid
  ontology: OntologyBundle
  survivors: set[string]
  terminated: bool
  obligations: map[string, ObligationState]
  audit_log: [AuditEntry]
```

#### Audit Entry (append-only)

```yaml
AuditEntry:
  event_id: uuid
  ts: timestamp
  verb: string
  payload: object
  survivors_before_hash: string
  survivors_after_hash: string
  delta:
    eliminated: [string]
  notes: optional string
```

Hashing: `sha256(sorted_survivors + session_id + prev_event_hash)` is sufficient for v1.

---

## 2. Belief Protocol (Verbs)

All verbs are **messages**. The server is a **state transition machine** with an append-only log.

### 2.1 Verbs (v1)

#### `DECLARE_SESSION`

Create a new belief session.

Request:

```yaml
DECLARE_SESSION:
  ontology: OntologyBundle
  hypotheses: [string]          # explicit list OR hypothesis_space_id resolves to list (v1: explicit list)
  metadata: optional object
```

Response:

```yaml
session_id: uuid
snapshot: BeliefSnapshot
```

Rules:

* initializes `survivors = set(hypotheses)`
* initializes empty audit log (or logs DECLARE_SESSION as first entry)

---

#### `ELIMINATE`

Monotone update: remove hypotheses from survivors.

Request:

```yaml
ELIMINATE:
  session_id: uuid
  source_id: string            # e.g. "adapter://sre", "oracle://20q", "human://alice"
  observation_id: string       # caller-defined id for traceability
  eliminated: [string]         # hypotheses claimed inconsistent
  justification: object        # opaque to server (stored, not interpreted)
```

Response:

```yaml
applied_eliminated: [string]   # actual elimination intersected with current survivors
ignored_eliminated: [string]   # not in survivors (idempotence)
snapshot: BeliefSnapshot
audit_event_id: uuid
```

Rules (server enforced):

* Let `A = eliminated ∩ survivors`
* Set `survivors := survivors \ A`
* Never resurrect
* Idempotent (same elimination twice is safe)
* Append audit entry

---

#### `QUERY_BELIEF`

Request:

```yaml
QUERY_BELIEF:
  session_id: uuid
```

Response: `BeliefSnapshot`

---

#### `AUDIT_TRACE`

Request:

```yaml
AUDIT_TRACE:
  session_id: uuid
  since_event_id: optional uuid
```

Response:

```yaml
events: [AuditEntry]
```

---

#### `ENTER_OBLIGATION`

An “epistemic gate”: policy about when exit/termination is allowed. (Still belief-server-side because it gates *requests*, not belief updates.)

Request:

```yaml
ENTER_OBLIGATION:
  session_id: uuid
  obligation_id: string
  min_total_eliminations: int
```

Response: updated snapshot + audit event id

---

#### `REQUEST_EXIT`

Request:

```yaml
REQUEST_EXIT:
  session_id: uuid
  obligation_id: string
  context: optional object
```

Response:

```yaml
approved: bool
reason: string
snapshot: BeliefSnapshot
audit_event_id: uuid
```

Rule (v1 default policy):

* approved iff `total_eliminations_since_obligation_entry >= min_total_eliminations`

This matches what your kernel already does.

---

#### `DECLARE_CONCLUSION`

Request:

```yaml
DECLARE_CONCLUSION:
  session_id: uuid
  conclusion_id: string
  context: optional object
```

Response:

```yaml
accepted: bool
reason: string
snapshot: BeliefSnapshot
audit_event_id: uuid
```

Rule (v1 default policy):

* accepted iff current obligation has approved exit (or no obligation is active)

(If your kernel enforces this, mirror it; otherwise implement as server policy.)

---

#### `REQUEST_TERMINATION`

Request:

```yaml
REQUEST_TERMINATION:
  session_id: uuid
  context: optional object
```

Response:

```yaml
approved: bool
reason: string
snapshot: BeliefSnapshot
audit_event_id: uuid
```

Rule (v1 default policy):

* approved iff **no active obligation** AND `len(survivors) == 1` OR `caller context says “force” and policy allows (optional)`

Keep termination conservative in v1.

---

### 2.2 Snapshot Format

```yaml
BeliefSnapshot:
  session_id: uuid
  ontology: OntologyBundle
  survivors: [string]            # sorted
  n_survivors: int
  entropy_proxy: float           # log2(n_survivors), 0 if n<=1
  terminated: bool
  active_obligation_id: optional string
  audit_head_event_id: optional uuid
```

---

## 3. API (HTTP/JSON)

### 3.1 Endpoints

**POST** `/v1/sessions`

* body: `DECLARE_SESSION`
* returns: session_id + snapshot

**POST** `/v1/sessions/{session_id}/eliminate`

* body: `ELIMINATE` (session_id may be omitted because it’s in path)
* returns: applied/ignored + snapshot + audit_event_id

**GET** `/v1/sessions/{session_id}`

* returns: snapshot

**GET** `/v1/sessions/{session_id}/audit`

* query: `since_event_id` optional
* returns: list of events

**POST** `/v1/sessions/{session_id}/obligations`

* body: `ENTER_OBLIGATION`

**POST** `/v1/sessions/{session_id}/obligations/{obligation_id}/exit`

* body: `REQUEST_EXIT`

**POST** `/v1/sessions/{session_id}/conclusions`

* body: `DECLARE_CONCLUSION`

**POST** `/v1/sessions/{session_id}/terminate`

* body: `REQUEST_TERMINATION`

### 3.2 Error Model

All errors return:

```yaml
error:
  code: string
  message: string
  details: optional object
```

Required error cases:

* `SESSION_NOT_FOUND`
* `SESSION_TERMINATED`
* `INVALID_HYPOTHESIS_ID` (if you choose to validate IDs against the declared set)
* `OBLIGATION_NOT_FOUND`
* `CONFLICT` (rare; only if you enforce optimistic concurrency)

---

## 4. Invariants and Proof Obligations

### 4.1 Invariants (must be enforced or testable)

* **Monotonicity:** `survivors_next ⊆ survivors_prev`
* **Idempotence:** reapplying same `ELIMINATE` yields no state change
* **Order independence:** applying two elimination sets in either order yields same final survivors
* **Replayability:** replaying audit log reproduces snapshot

### 4.2 Determinism Constraints

* survivors must be stored and emitted in **sorted order**
* audit hash must be computed on **canonical JSON** or a stable serialization

---

## 5. Storage and Concurrency

### 5.1 Storage (v1 choices)

* **In-memory** store is acceptable for dev
* **SQLite/Postgres** recommended for durability:

  * `sessions` table: session metadata + current survivors blob
  * `audit_events` table: append-only event log (JSON payload + hashes)

### 5.2 Concurrency (v1 minimal)

You can make this safe without heavy coordination:

* Per-session **mutex** in-process
* Or DB transaction + row lock
* Optional optimistic concurrency: include `If-Match: audit_head_event_id`

Because updates are monotone, conflict resolution is simple, but you still want consistent audit ordering per session.

---

## 6. Python Mechanism (reference implementation)

### 6.1 Architecture

* `BeliefKernel` = your existing `CMBSCore`
* `BeliefServer` = session manager + audit log + policy checks
* `Transport` = FastAPI routes translating HTTP ↔ protocol messages

### 6.2 Minimal type shapes (Python)

```python
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple
import math
import time
import uuid
import hashlib
import json

@dataclass(frozen=True)
class OntologyBundle:
    hypothesis_space_id: str
    hypothesis_version: str
    causal_graph_ref: str
    causal_graph_version: str

@dataclass
class BeliefSnapshot:
    session_id: str
    ontology: OntologyBundle
    survivors: List[str]
    terminated: bool
    active_obligation_id: Optional[str]
    audit_head_event_id: Optional[str]

    @property
    def n_survivors(self) -> int:
        return len(self.survivors)

    @property
    def entropy_proxy(self) -> float:
        n = self.n_survivors
        return 0.0 if n <= 1 else math.log2(n)

@dataclass
class AuditEntry:
    event_id: str
    ts: float
    verb: str
    payload: Dict[str, Any]
    survivors_before_hash: str
    survivors_after_hash: str
    delta_eliminated: List[str]
```

### 6.3 Session state (wrapping your kernel)

```python
@dataclass
class SessionState:
    session_id: str
    ontology: OntologyBundle
    kernel: Any  # CMBSCore
    terminated: bool = False
    active_obligation_id: Optional[str] = None
    audit: List[AuditEntry] = None
```

### 6.4 Canonical hashing helper

```python
def _hash_survivors(survivors: Set[str]) -> str:
    s = "\n".join(sorted(survivors)).encode("utf-8")
    return hashlib.sha256(s).hexdigest()

def _canonical_json(obj: Dict[str, Any]) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))
```

### 6.5 BeliefServer handlers (sketch)

Key rule: the server only calls kernel methods that implement monotone elimination + obligations.

```python
class BeliefServer:
    def __init__(self):
        self._sessions: Dict[str, SessionState] = {}

    def declare_session(self, ontology: OntologyBundle, hypotheses: List[str]) -> BeliefSnapshot:
        session_id = str(uuid.uuid4())
        # kernel = CMBSCore(hypotheses)  # adapt to your constructor
        kernel = CMBSCore(hypotheses)   # placeholder name
        st = SessionState(session_id=session_id, ontology=ontology, kernel=kernel, audit=[])
        self._sessions[session_id] = st
        self._append_audit(st, "DECLARE_SESSION", {"ontology": ontology.__dict__, "hypotheses": hypotheses}, eliminated=[])
        return self._snapshot(st)

    def eliminate(self, session_id: str, source_id: str, observation_id: str,
                  eliminated: List[str], justification: Dict[str, Any]) -> Tuple[List[str], List[str], BeliefSnapshot, str]:
        st = self._get(session_id)
        self._ensure_not_terminated(st)

        before = set(st.kernel.survivors)  # or st.kernel._survivors if property not exposed
        before_hash = _hash_survivors(before)

        applied = list(set(eliminated) & before)
        ignored = list(set(eliminated) - set(applied))

        # Call your kernel method (rename submit_probe_result -> submit_elimination)
        st.kernel.submit_elimination(
            source_id=source_id,
            observation_id=observation_id,
            eliminated=set(eliminated),
            justification=justification,
        )

        after = set(st.kernel.survivors)
        after_hash = _hash_survivors(after)

        payload = {
            "source_id": source_id,
            "observation_id": observation_id,
            "eliminated": eliminated,
            "justification": justification,
        }
        event_id = self._append_audit(st, "ELIMINATE", payload, eliminated=sorted(applied),
                                      before_hash=before_hash, after_hash=after_hash)
        return sorted(applied), sorted(ignored), self._snapshot(st), event_id

    # ... enter_obligation, request_exit, declare_conclusion, request_termination ...
```

The only “mechanism” work here is:

* session registry
* append-only audit
* translating protocol messages into kernel calls

---

## 7. Acceptance Criteria for “Next Step Done”

You’re done when you have:

1. A running server with the above endpoints

2. A single end-to-end script that:

   * creates a session
   * submits 2 elimination messages
   * fetches snapshot
   * fetches audit log
   * replays audit log to reproduce final survivors

3. Test suite covering:

* monotonicity
* order independence
* idempotence
* replayability

That’s the “Belief Server” claim, fully supported.

---

## 8. What to name the artifacts in your repo

* `BELIEF_SERVER_SPEC.md` (this)
* `BELIEF_PROTOCOL.md` (verbed messages + schemas)
* `api/openapi.yaml` (optional next, but easy)
* `tests/test_invariants.py`
* `examples/replay_demo.py`

---

## 9. V2 Operator-Log Extension (Transcript-Conditioned State)

CMBS v2 adds an operator-log surface while keeping `/v1` behavior unchanged.

State definition:

`State = reduce(reducer_version, op_log_prefix(branch, seq))`

Primary `/v2` endpoints:

- `POST /v2/sessions`
- `POST /v2/sessions/{sid}/ops`
- `POST /v2/sessions/{sid}/branches`
- `GET /v2/sessions/{sid}/ops`
- `GET /v2/sessions/{sid}/state`
- `POST /v2/analysis/commute`
- `POST /v2/analysis/replay`
- `POST /v2/merge`

Phase-1 merge contract:

- Supported policy: `refuse_non_commutative`
- On order-sensitive conflicts: `409 NON_COMMUTATIVE_CONFLICT`
- Conflict response includes witness with both order hashes and a projection diff summary.
