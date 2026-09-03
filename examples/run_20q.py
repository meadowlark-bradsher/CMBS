"""Twenty Questions against the unified Session kernel.

The adapter proposes questions, the oracle answers them for a fixed secret,
and every answer becomes one ``probe_result`` op in the session's log.
"""

from cmbs import OntologyBundle, Session
from cmbs.adapters.twenty_questions import TwentyQAdapter, TwentyQOracle, load_builtin_kit


def run(secret: str = "eagle", kit_name: str = "20q_4") -> Session:
    kit = load_builtin_kit(kit_name)
    adapter = TwentyQAdapter(kit)
    oracle = TwentyQOracle(kit)

    session = Session(
        hypothesis_ids=kit.hypotheses,
        ontology=OntologyBundle(
            hypothesis_space_id="20q",
            hypothesis_version=kit_name,
            causal_graph_ref="none",
            causal_graph_version="v0",
        ),
    )

    while session.snapshot().n_survivors > 1:
        actions = adapter.list_actions(session.snapshot())
        if not actions:
            break
        action = actions[0]
        ctx = adapter.apply_action(action.action_id, session.snapshot())
        outcome = oracle.answer(secret=secret, action_id=action.action_id)
        for msg in adapter.observe(ctx, outcome):
            session.submit_probe_result(
                probe_id=msg.observation_id,
                observable_id=msg.observation_id,
                eliminated=msg.eliminated,
                source_id=msg.source_id,
                provenance=msg.justification,
            )
    return session


def main() -> None:
    session = run()
    print("survivors:", sorted(session.survivors))
    print("ops:", session.head_seq)
    print("state_hash:", session.snapshot().state_hash)


if __name__ == "__main__":
    main()
