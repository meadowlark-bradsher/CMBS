from cmbs.adapters.twenty_questions import TwentyQAdapter, TwentyQOracle, load_builtin_kit
from cmbs.belief_server import BeliefServer, OntologyBundle


def main() -> None:
    kit = load_builtin_kit("20q_4")
    server = BeliefServer()
    adapter = TwentyQAdapter(kit)
    oracle = TwentyQOracle(kit)

    session_id, snapshot = server.declare_session(
        ontology=OntologyBundle(
            hypothesis_space_id="20q",
            hypothesis_version="20q_4",
            causal_graph_ref="none",
            causal_graph_version="v0",
        ),
        hypotheses=kit.hypotheses,
    )

    secret = "eagle"
    while snapshot.n_survivors > 1:
        actions = adapter.list_actions(snapshot)
        if not actions:
            break
        action = actions[0]
        ctx = adapter.apply_action(action.action_id, snapshot)
        outcome = oracle.answer(secret=secret, action_id=action.action_id)
        messages = adapter.observe(ctx, outcome)
        for msg in messages:
            _, _, snapshot, _ = server.eliminate(
                session_id=session_id,
                source_id=msg.source_id,
                observation_id=msg.observation_id,
                eliminated=msg.eliminated,
                justification=msg.justification,
            )

    print("survivors:", snapshot.survivors)
    print("audit_events:", len(server.audit_trace(session_id)))


if __name__ == "__main__":
    main()
