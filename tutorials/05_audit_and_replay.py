"""
Tutorial 05 — the log as evidence.

Someone hands a reviewer an initial hypothesis set and an op log. Without
trusting the sender's session object, the reviewer rebuilds the state
with the same reducer and compares hashes. Then we tamper with one
envelope and watch the comparison fail.

No LLM involved.

    python tutorials/05_audit_and_replay.py
"""

from __future__ import annotations

import json
from dataclasses import replace

from _support import banner, show

from cmbs import MaskMeetTombstoneReducer, OperationEnvelope, Session


def run() -> Session:
    session = Session(hypothesis_ids={"H1", "H2", "H3", "H4"}, session_id="case-42")
    session.submit_probe_result(probe_id="P1", observable_id="O1", eliminated={"H1"})
    session.enter_obligation("review", min_eliminations=1)
    session.submit_probe_result(probe_id="P2", observable_id="O2", eliminated={"H3"})
    session.submit_probe_result(probe_id="P2", observable_id="O2", eliminated={"H4"})  # rejected
    session.request_obligation_exit("review")
    session.declare_conclusion("H2-or-H4")

    banner("1. What the investigator hands over")
    handoff = {
        "session_id": session.session_id,
        "initial_hypotheses": sorted(session.initial_hypotheses),
        "stability_window": session.stability_window,
        "reducer_version": session.reducer.version,
        "claimed_state_hash": session.snapshot().state_hash,
        "ops": [op.to_dict() for op in session.operations()],
    }
    wire = json.dumps(handoff)
    show("bytes on the wire", len(wire))
    show("claimed state_hash", handoff["claimed_state_hash"][:16] + "…")

    banner("2. The reviewer replays it independently")
    received = json.loads(wire)
    envelopes = [OperationEnvelope(**d) for d in received["ops"]]
    replayed = MaskMeetTombstoneReducer().reduce(
        received["initial_hypotheses"],
        envelopes,
        session_id=received["session_id"],
        stability_window=received["stability_window"],
    )
    show("replayed survivors", sorted(replayed.survivors))
    show("hash matches claim", replayed.state_hash == received["claimed_state_hash"])
    for op in envelopes:
        verdict = "ok " if op.accepted else "REJ"
        print(f"  {op.seq:>2} {verdict} {op.op_type:<20} {op.rejected_reason or ''}")

    banner("3. Tampering with one envelope breaks the chain")
    tampered = list(envelopes)
    first_probe = tampered[0]  # seq 1: the probe that eliminated H1
    tampered[0] = replace(first_probe, payload={**first_probe.payload, "eliminate": ["H1", "H2"]})
    bad = MaskMeetTombstoneReducer().reduce(
        received["initial_hypotheses"], tampered, session_id=received["session_id"],
        stability_window=received["stability_window"],
    )
    show("tampered survivors", sorted(bad.survivors))
    show("hash matches claim", bad.state_hash == received["claimed_state_hash"])

    banner("4. Two hashes, two questions")
    show("state_hash", "which position in THIS log?")
    show("position_digest", "which point in the lattice?")
    other = Session(hypothesis_ids={"H1", "H2", "H3", "H4"}, session_id="case-99")
    other.submit_probe_result(probe_id="X", observable_id="O", eliminated={"H1", "H3"})
    show("other state_hash equal", other.snapshot().state_hash == session.snapshot().state_hash)
    show("other digest equal", other.position_digest == session.position_digest)
    return session


def main() -> None:
    run()


if __name__ == "__main__":
    main()
