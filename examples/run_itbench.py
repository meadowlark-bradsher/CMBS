from cmbs.adapters.itbench import ITBenchAdapter, ITBenchOracle, load_builtin_kit
from cmbs.belief_server import BeliefServer, OntologyBundle


def main() -> None:
    kit = load_builtin_kit("itb_min_4")
    server = BeliefServer()
    adapter = ITBenchAdapter(kit)

    scenario = {
        "check_replication_lag": "high",
        "check_disk_usage": "ok",
        "check_deploy_version": "expected",
        "check_db_connections": "high",
    }
    oracle = ITBenchOracle(kit, scenario=scenario)

    session_id, snapshot = server.declare_session(
        ontology=OntologyBundle(
            hypothesis_space_id="itbench",
            hypothesis_version="itb_min_4",
            causal_graph_ref="none",
            causal_graph_version="v0",
        ),
        hypotheses=kit.hypotheses,
    )

    while snapshot.n_survivors > 1:
        actions = adapter.list_actions(snapshot)
        if not actions:
            break
        action = actions[0]
        ctx = adapter.apply_action(action.action_id, snapshot)
        outcome = oracle.answer(action.action_id)
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
