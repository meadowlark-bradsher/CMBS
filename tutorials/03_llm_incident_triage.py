"""
Tutorial 03 — LLM-driven incident triage with obligation and stability gates.

The ITBench kit lists six candidate root causes and six checks. Claude
picks which check to run next; a scripted scenario reports each outcome.
Two pieces of workflow discipline sit on top:

- an obligation ``triage`` that must see at least three eliminations before
  the agent is allowed to leave the investigation phase (INV-6), and
- a stability window of two, so a conclusion has to be declared twice in
  a row before termination is permitted (INV-2).

Watch the kernel refuse the early exit and the early termination.

    python tutorials/03_llm_incident_triage.py
    python tutorials/03_llm_incident_triage.py --offline
"""

from __future__ import annotations

import argparse
import sys

from _support import Choice, ProbePolicy, banner, make_policy, show

from cmbs import OntologyBundle, Session
from cmbs.adapters.itbench import ITBenchAdapter, ITBenchOracle, load_builtin_kit

SCENARIO = {
    "check_replication_lag": "high",
    "check_disk_usage": "ok",
    "check_deploy_version": "expected",
    "check_db_connections": "normal",
    "check_network_health": "healthy",
    "check_cpu_throttle": "normal",
}


def run(policy: ProbePolicy, *, kit_name: str = "itb_sre_6", max_checks: int = 6) -> Session:
    kit = load_builtin_kit(kit_name)
    adapter = ITBenchAdapter(kit)
    oracle = ITBenchOracle(kit, scenario=SCENARIO)
    session = Session(
        hypothesis_ids=kit.hypotheses,
        ontology=OntologyBundle(hypothesis_space_id="itbench", hypothesis_version=kit_name),
        stability_window=2,
    )
    session.enter_obligation("triage", min_eliminations=3)
    ran: list[str] = []

    banner(f"Incident triage — policy is {policy.name}")
    show("candidate causes", sorted(session.survivors))

    banner("Trying to skip the investigation")
    early = session.request_obligation_exit("triage")
    show("exit permitted", early.permitted)
    show("reason", early.error)

    banner("Investigation")
    for _ in range(max_checks):
        if len(session.survivors) <= 1:
            break
        choices = [
            Choice(action_id=aid, prompt=kit.actions[aid].description, already_asked=aid in ran)
            for aid in kit.actions_order
            if aid not in ran
        ]
        if not choices:
            break
        decision = policy.choose(
            task="Find the root cause of the incident with as few checks as possible.",
            survivors=sorted(session.survivors),
            choices=choices,
            history=ran,
        )
        outcome = oracle.answer(decision.action_id)
        ctx = adapter.apply_action(decision.action_id, session.snapshot())
        (msg,) = adapter.observe(ctx, outcome)
        result = session.submit_probe_result(
            probe_id=decision.action_id,
            observable_id=msg.observation_id,
            eliminated=msg.eliminated,
            source_id=f"policy://{policy.name}",
            provenance={"outcome": outcome, "reason": decision.reason},
        )
        ran.append(decision.action_id)
        print(f"\n  {kit.actions[decision.action_id].description}  →  {outcome}")
        show("eliminated", sorted(result.eliminated) or "nothing")
        show("survivors", sorted(session.survivors))
        entry = session.snapshot().obligation("triage")
        show("triage progress", f"{entry.eliminations_in_scope}/{entry.min_eliminations}")

    banner("Leaving the investigation phase")
    exit_result = session.request_obligation_exit("triage")
    show("exit permitted", exit_result.permitted)
    if not exit_result.permitted:
        show("reason", exit_result.error)

    banner("Concluding")
    conclusion = sorted(session.survivors)[0] if session.survivors else "no_survivor"
    session.declare_conclusion(conclusion)
    first = session.request_termination()
    show("terminate after 1", f"{first.permitted}  ({first.error})")
    session.declare_conclusion(conclusion)
    second = session.request_termination()
    show("terminate after 2", second.permitted)
    show("conclusion", conclusion)
    show("is_terminated", session.is_terminated)
    return session


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args(argv)
    run(make_policy(["--offline"] if args.offline else []))


if __name__ == "__main__":
    main(sys.argv[1:])
