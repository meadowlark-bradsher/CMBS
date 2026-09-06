"""
Tutorial 06 — a file-backed OpLogStore in forty lines.

The package ships only ``InMemoryOpLogStore``. The SPI is small enough that
a durable store is a short exercise: one JSONL file per session, the
header line holding session metadata and one line per envelope after it.
This tutorial writes a session, throws the ``Session`` object away as a
"process restart", and recovers from disk.

No LLM involved. Not production code: no locking, no fsync.

    python tutorials/06_file_backed_store.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from _support import banner, show

from cmbs import OntologyBundle, OperationEnvelope, OpLogStore, RecoveredSession, Session


class JsonlOpLogStore:
    """One ``<session_id>.jsonl`` per session under ``root``."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self.root / f"{session_id}.jsonl"

    def _lines(self, session_id: str) -> list[dict]:
        path = self._path(session_id)
        if not path.exists():
            raise KeyError(f"Unknown session_id {session_id!r}.")
        return [json.loads(line) for line in path.read_text().splitlines() if line]

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

    def read_ops(self, session_id, from_seq=None, to_seq=None):
        ops = [OperationEnvelope(**d) for d in self._lines(session_id)[1:]]
        lo = 1 if from_seq is None else from_seq
        hi = len(ops) if to_seq is None else to_seq
        return tuple(ops[lo - 1 : hi])

    def head_seq(self, session_id):
        return len(self._lines(session_id)) - 1

    def recover(self, session_id):
        header, *rows = self._lines(session_id)
        return RecoveredSession(
            session_id=header["session_id"],
            initial_hypotheses=frozenset(header["initial_hypotheses"]),
            ontology=OntologyBundle(**header["ontology"]) if header["ontology"] else None,
            stability_window=header["stability_window"],
            reducer_version=header["reducer_version"],
            envelopes=tuple(OperationEnvelope(**d) for d in rows),
        )


def run(root: Path | None = None) -> tuple[Session, Session]:
    root = root or Path(tempfile.mkdtemp(prefix="cmbs-tutorial-"))
    store = JsonlOpLogStore(root)
    assert isinstance(store, OpLogStore), "the class satisfies the runtime-checkable protocol"

    banner("1. Write a session through the file store")
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
    path = root / "durable-1.jsonl"
    show("file", path)
    show("lines (header + ops)", len(path.read_text().splitlines()))
    show("survivors", sorted(s.survivors))

    banner("2. 'Restart': drop the object, recover from disk")
    claimed = s.snapshot()
    del s
    r = Session.recover(JsonlOpLogStore(root), "durable-1")
    show("survivors", sorted(r.survivors))
    show("active obligations", sorted(r.active_obligations))
    show("snapshot identical", r.snapshot() == claimed)

    banner("3. The recovered session keeps writing the same file")
    show("P1 again accepted?", r.submit_probe_result(probe_id="P1", observable_id="O1", eliminated=set()).accepted)
    show("P2 accepted?", r.submit_probe_result(probe_id="P2", observable_id="O2", eliminated={"H2"}).accepted)
    show("head_seq", r.head_seq)
    show("lines on disk", len(path.read_text().splitlines()))
    return r, Session.recover(JsonlOpLogStore(root), "durable-1")


def main() -> None:
    run()


if __name__ == "__main__":
    main()
