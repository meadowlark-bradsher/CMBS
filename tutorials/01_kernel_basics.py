"""
Tutorial 01 — the kernel on its own.

No LLM, no adapters. Just a ``Session`` and the five facade calls, to see
what the kernel books and what it refuses. Run it and read the output next
to the code.

    python tutorials/01_kernel_basics.py
"""

from __future__ import annotations

from _support import banner, show

from cmbs import InMemoryOpLogStore, Session


def run() -> Session:
    store = InMemoryOpLogStore()
    session = Session(
        hypothesis_ids={"disk_full", "bad_deploy", "replication_lag", "network_partition"},
        stability_window=2,  # INV-2: two identical conclusions before termination
        store=store,
    )

    banner("1. A fresh session is the top of the lattice")
    show("survivors", sorted(session.survivors))
    show("entropy (bits)", round(session.entropy, 3))
    show("position_digest", session.position_digest[:16] + "…")

    banner("2. Probes eliminate; the kernel trusts the caller's set")
    r = session.submit_probe_result(
        probe_id="check_disk", observable_id="disk_usage=41%", eliminated={"disk_full"}
    )
    show("accepted", r.accepted)
    show("newly eliminated", sorted(r.eliminated))
    show("survivors", sorted(session.survivors))

    banner("3. INV-3: the same probe_id is refused and the attempt is logged")
    r = session.submit_probe_result(
        probe_id="check_disk", observable_id="disk_usage=41%", eliminated={"bad_deploy"}
    )
    show("accepted", r.accepted)
    show("error", r.error)
    show("survivors", sorted(session.survivors))
    show("log length", session.head_seq)

    banner("4. INV-6: an obligation gates its own exit on eliminations *in scope*")
    session.enter_obligation("triage", min_eliminations=2)
    show("exit before work", session.request_obligation_exit("triage").permitted)
    session.submit_probe_result(
        probe_id="check_deploy", observable_id="version=expected", eliminated={"bad_deploy"}
    )
    show("exit after one", session.request_obligation_exit("triage").permitted)
    session.submit_probe_result(
        probe_id="check_network", observable_id="packet_loss=0", eliminated={"network_partition"}
    )
    exit_result = session.request_obligation_exit("triage")
    show("exit after two", exit_result.permitted)
    show("survivors", sorted(session.survivors))

    banner("5. INV-2: termination waits for a stable conclusion")
    session.declare_conclusion("replication_lag")
    show("terminate after one", session.request_termination().permitted)
    session.declare_conclusion("replication_lag")
    show("terminate after two", session.request_termination().permitted)
    show("is_terminated", session.is_terminated)

    banner("6. The log is the audit trail, including the refusals")
    for op in session.operations():
        verdict = "ok " if op.accepted else "REJ"
        print(f"  {op.seq:>2} {verdict} {op.op_type:<20} {op.rejected_reason or ''}")

    banner("7. Recovery is replay")
    again = Session.recover(store, session.session_id)
    show("same snapshot", again.snapshot() == session.snapshot())
    show("same state_hash", again.snapshot().state_hash == session.snapshot().state_hash)
    return session


def main() -> None:
    run()


if __name__ == "__main__":
    main()
