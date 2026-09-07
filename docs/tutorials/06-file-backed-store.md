# 06 · File-backed store

The package ships only `InMemoryOpLogStore`. The `OpLogStore` SPI has
five methods, and a durable implementation is a short exercise: one
JSONL file per session, a header line for the session metadata, one
line per envelope after it. This tutorial writes a session through such
a store, throws the `Session` object away as a stand-in for a process
restart, and recovers from disk.

No LLM involved. The store is a demonstration, not production code: no
locking, no `fsync`, no concurrent writers.

## Run it

```bash
python tutorials/06_file_backed_store.py
```

## Walkthrough

### The store

```python
class JsonlOpLogStore:
    """One ``<session_id>.jsonl`` per session under ``root``."""

    def create_session(self, session_id, initial_hypotheses, ontology, stability_window, reducer_version):
        path = self._path(session_id)
        if path.exists():
            raise ValueError(f"Session {session_id!r} already exists.")
        header = {
            "session_id": session_id,
            "initial_hypotheses": sorted(initial_hypotheses),
            "ontology": ontology.__dict__ if ontology else None,
            "stability_window": stability_window,
            "reducer_version": reducer_version,
        }
        path.write_text(json.dumps(header) + "\n")

    def append(self, session_id, envelope):
        expected = self.head_seq(session_id) + 1
        if envelope.seq != expected:
            raise ValueError(f"Out-of-order append: got {envelope.seq}, expected {expected}.")
        with self._path(session_id).open("a") as f:
            f.write(json.dumps(envelope.to_dict()) + "\n")
```

`read_ops`, `head_seq`, and `recover` are the reverse: read the lines,
skip the header, rebuild `OperationEnvelope` records with `**row`. The
whole class is about forty lines, and because `OpLogStore` is a
runtime-checkable protocol, the script asserts `isinstance(store,
OpLogStore)` before using it.

### 1. Write a session through the file store

```python
s = Session(
    hypothesis_ids={"H1", "H2", "H3"},
    store=store,
    session_id="durable-1",
    ontology=OntologyBundle(hypothesis_space_id="demo", hypothesis_version="1"),
    stability_window=1,
)
s.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})
s.enter_obligation("O", min_eliminations=1)
s.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H2"})  # rejected, still logged
```

```
file                   .../cmbs-tutorial-xxxx/durable-1.jsonl
lines (header + ops)   4
survivors              ['H2', 'H3']
```

Three calls, three envelopes, four lines with the header. The rejected
repeat is on disk like everything else.

### 2. "Restart": drop the object, recover from disk

```python
claimed = s.snapshot()
del s
r = Session.recover(JsonlOpLogStore(root), "durable-1")
```

```
survivors              ['H2', 'H3']
active obligations     ['O']
snapshot identical     True
```

A brand-new store object pointed at the same directory, and a session
rebuilt from the file. The open obligation came back with it, as did the
ontology and the stability window from the header line.

### 3. The recovered session keeps writing the same file

```
P1 again accepted?     False
P2 accepted?           True
head_seq               5
lines on disk          6
```

The consumed probe IDs are part of the replayed state, so `P1` is still
refused after the restart. New envelopes append to the same file at the
next sequence number.

## What to notice

- **The store never interprets anything.** It serializes envelopes and
  session metadata and hands them back. All meaning lives in the reducer.
- **Contiguous sequence numbers are the one invariant a store must
  hold.** The in-memory store checks it and so does this one. A store
  that accepted a gap would let recovery silently skip an operation.
- **This is where the ADR left off.** ADR-001 deferred shipping a
  file-backed store in the package. This tutorial shows the shape as
  user code; a packaged one would add locking and durability guarantees.

## Source

[`tutorials/06_file_backed_store.py`](https://github.com/meadowlark-bradsher/CMBS/blob/main/tutorials/06_file_backed_store.py)

Back to the [overview](index.md).
