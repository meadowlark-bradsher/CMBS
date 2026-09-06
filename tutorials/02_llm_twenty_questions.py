"""
Tutorial 02 — an LLM plays Twenty Questions against the kernel.

Claude chooses which question to ask; the kit's oracle answers for a
secret; the adapter turns each answer into an elimination set; the
``Session`` books it. The LLM is shown *every* question, including ones it
already asked, so you can watch INV-3 refuse a repeat instead of trusting
the prompt to prevent it.

    python tutorials/02_llm_twenty_questions.py              # live if a key is visible
    python tutorials/02_llm_twenty_questions.py --offline    # scripted policy
    python tutorials/02_llm_twenty_questions.py --secret dolphin
"""

from __future__ import annotations

import argparse
import sys

from _support import Choice, ProbePolicy, banner, make_policy, show

from cmbs import OntologyBundle, Session
from cmbs.adapters.twenty_questions import TwentyQAdapter, TwentyQOracle, load_builtin_kit


def run(
    policy: ProbePolicy,
    *,
    secret: str = "eagle",
    kit_name: str = "20q_8",
    max_turns: int = 8,
) -> Session:
    kit = load_builtin_kit(kit_name)
    adapter = TwentyQAdapter(kit)
    oracle = TwentyQOracle(kit)
    session = Session(
        hypothesis_ids=kit.hypotheses,
        ontology=OntologyBundle(hypothesis_space_id="20q", hypothesis_version=kit_name),
    )
    asked: list[str] = []

    banner(f"Twenty Questions — secret is {secret!r}, policy is {policy.name}")
    show("hypotheses", sorted(session.survivors))

    for turn in range(1, max_turns + 1):
        if len(session.survivors) <= 1:
            break
        choices = [
            Choice(action_id=aid, prompt=kit.actions[aid].question, already_asked=aid in asked)
            for aid in kit.actions_order
        ]
        decision = policy.choose(
            task="Identify the secret animal with as few questions as possible.",
            survivors=sorted(session.survivors),
            choices=choices,
            history=asked,
        )
        question = kit.actions[decision.action_id].question
        answer = oracle.answer(secret=secret, action_id=decision.action_id)

        # The adapter needs the *pre-answer* frontier to compute what the
        # answer rules out, so take the snapshot before booking.
        ctx = adapter.apply_action(decision.action_id, session.snapshot())
        (msg,) = adapter.observe(ctx, answer)
        before = session.position_digest
        result = session.submit_probe_result(
            probe_id=decision.action_id,  # the question is the probe; re-asking is a repeat
            observable_id=msg.observation_id,
            eliminated=msg.eliminated,
            source_id=f"policy://{policy.name}",
            provenance={"question": question, "answer": answer, "reason": decision.reason},
        )

        print(f"\n  turn {turn}: {question}  →  {answer}")
        if decision.reason:
            print(f"    reason: {decision.reason}")
        if not result.accepted:
            print(f"    REJECTED by the kernel: {result.error}")
            continue
        asked.append(decision.action_id)
        show("eliminated", sorted(result.eliminated) or "nothing")
        show("survivors", sorted(session.survivors))
        if session.position_digest == before:
            print("    (zero-information question: position_digest unchanged)")

    banner("Result")
    show("survivors", sorted(session.survivors))
    show("secret survived", secret in session.survivors)
    show("ops in log", session.head_seq)
    rejected = [op for op in session.operations() if not op.accepted]
    show("rejected attempts", len(rejected))
    return session


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--secret", default="eagle")
    parser.add_argument("--kit", default="20q_8")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args(argv)
    policy = make_policy(["--offline"] if args.offline else [])
    run(policy, secret=args.secret, kit_name=args.kit)


if __name__ == "__main__":
    main(sys.argv[1:])
