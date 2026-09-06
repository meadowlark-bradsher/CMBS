"""
Tutorial 04 — two agents, two sessions, one belief.

Agent A and agent B investigate the same universe in separate sessions
with different probe orders. Their logs, state hashes, and session IDs all
differ. ``position_digest`` is the thing that agrees when their *beliefs*
agree, so they can check convergence without exchanging logs. When they
disagree, the meet of the two frontiers is itself a position, and the
digest names it.

With a key visible, agent A is Claude and agent B is scripted with the
question list reversed; offline, both are scripted.

    python tutorials/04_convergence_two_agents.py
    python tutorials/04_convergence_two_agents.py --offline
"""

from __future__ import annotations

import argparse
import sys

from _support import Choice, ProbePolicy, ScriptedPolicy, banner, make_policy, show

from cmbs import Session, compute_position_digest
from cmbs.adapters.twenty_questions import TwentyQAdapter, TwentyQOracle, load_builtin_kit


def _step(session, adapter, oracle, kit, policy, order, asked, secret) -> str | None:
    choices = [
        Choice(action_id=aid, prompt=kit.actions[aid].question, already_asked=aid in asked)
        for aid in order
        if aid not in asked
    ]
    if not choices or len(session.survivors) <= 1:
        return None
    decision = policy.choose(
        task="Identify the secret animal.",
        survivors=sorted(session.survivors),
        choices=choices,
        history=asked,
    )
    answer = oracle.answer(secret=secret, action_id=decision.action_id)
    ctx = adapter.apply_action(decision.action_id, session.snapshot())
    (msg,) = adapter.observe(ctx, answer)
    session.submit_probe_result(
        probe_id=decision.action_id, observable_id=msg.observation_id, eliminated=msg.eliminated
    )
    asked.append(decision.action_id)
    return decision.action_id


def run(policy_a: ProbePolicy, *, secret: str = "shark", kit_name: str = "20q_8") -> tuple[Session, Session]:
    kit = load_builtin_kit(kit_name)
    oracle = TwentyQOracle(kit)
    policy_b = ScriptedPolicy()
    a = Session(hypothesis_ids=kit.hypotheses, session_id="agent-a")
    b = Session(hypothesis_ids=kit.hypotheses, session_id="agent-b")
    adapter_a, adapter_b = TwentyQAdapter(kit), TwentyQAdapter(kit)
    order_a, order_b = list(kit.actions_order), list(reversed(kit.actions_order))
    asked_a: list[str] = []
    asked_b: list[str] = []

    banner(f"Two agents on secret {secret!r} — A is {policy_a.name}, B is scripted (reversed order)")
    print(f"  {'step':<5} {'A asked':<14} {'B asked':<14} {'A digest':<10} {'B digest':<10} same?")
    for step in range(1, len(kit.actions_order) + 1):
        qa = _step(a, adapter_a, oracle, kit, policy_a, order_a, asked_a, secret)
        qb = _step(b, adapter_b, oracle, kit, policy_b, order_b, asked_b, secret)
        if qa is None and qb is None:
            break
        same = a.position_digest == b.position_digest
        print(
            f"  {step:<5} {qa or '-':<14} {qb or '-':<14} "
            f"{a.position_digest[:8]:<10} {b.position_digest[:8]:<10} {'yes' if same else 'no'}"
        )
        if not same:
            meet = a.survivors & b.survivors
            print(f"        meet = {sorted(meet)}  digest {compute_position_digest(meet)[:8]}")

    banner("Where they ended up")
    show("A survivors", sorted(a.survivors))
    show("B survivors", sorted(b.survivors))
    show("A state_hash", a.snapshot().state_hash[:16] + "…")
    show("B state_hash", b.snapshot().state_hash[:16] + "…")
    show("state hashes equal", a.snapshot().state_hash == b.snapshot().state_hash)
    show("position digests equal", a.position_digest == b.position_digest)
    return a, b


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--secret", default="shark")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args(argv)
    run(make_policy(["--offline"] if args.offline else []), secret=args.secret)


if __name__ == "__main__":
    main(sys.argv[1:])
