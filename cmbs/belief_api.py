"""FastAPI transport for Belief Server v1 and operator-log v2."""

from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .belief_server import BeliefServer, BeliefServerError, OntologyBundle
from .op_models import OperationSpec
from .oplog_server import OplogServer, OplogServerError

app = FastAPI(title="Belief Server")
server = BeliefServer()
v2_server = OplogServer()


class OntologyBundleModel(BaseModel):
    hypothesis_space_id: str
    hypothesis_version: str
    causal_graph_ref: str
    causal_graph_version: str


class DeclareSessionRequest(BaseModel):
    ontology: OntologyBundleModel
    hypotheses: list[str]
    metadata: dict[str, Any] | None = None


class EliminateRequest(BaseModel):
    source_id: str
    observation_id: str
    eliminated: list[str]
    justification: dict[str, Any] | None = None
    session_id: str | None = None


class EnterObligationRequest(BaseModel):
    obligation_id: str
    min_total_eliminations: int


class RequestExitRequest(BaseModel):
    context: dict[str, Any] | None = None


class DeclareConclusionRequest(BaseModel):
    conclusion_id: str
    context: dict[str, Any] | None = None


class RequestTerminationRequest(BaseModel):
    context: dict[str, Any] | None = None


class V2CreateSessionRequest(BaseModel):
    ontology: dict[str, Any]
    initial_hypotheses: list[str]
    default_reducer: str = "v1_mask_meet_tombstone"
    metadata: dict[str, Any] | None = None


class OpSpecModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    op_id: str | None = None
    op_type: str = Field(alias="type")
    payload: dict[str, Any] = Field(default_factory=dict)
    source_id: str
    preconditions: list[str] = Field(default_factory=list)
    commutativity_key: str | None = None
    idempotency_key: str | None = None


class V2AppendOpRequest(BaseModel):
    op_id: str | None = None
    op_type: str = Field(alias="type")
    payload: dict[str, Any] = Field(default_factory=dict)
    source_id: str
    preconditions: list[str] = Field(default_factory=list)
    commutativity_key: str | None = None
    idempotency_key: str | None = None


class V2BranchRequest(BaseModel):
    from_branch: str
    from_seq: int
    name: str
    note: str | None = None


class V2CommutativityRequest(BaseModel):
    sid: str
    branch: str = "main"
    seq: int
    reducer: str
    op_a: OpSpecModel
    op_b: OpSpecModel


class V2ReplayRequest(BaseModel):
    sid: str
    branch: str = "main"
    from_seq: int | None = Field(default=None, alias="from")
    to_seq: int | None = Field(default=None, alias="to")
    reducers: list[str]


class V2BranchRef(BaseModel):
    branch: str
    seq: int


class V2MergeRequest(BaseModel):
    sid: str
    base: V2BranchRef
    heads: list[V2BranchRef]
    policy: str
    reducer: str


ERROR_STATUS = {
    "SESSION_NOT_FOUND": 404,
    "OBLIGATION_NOT_FOUND": 404,
    "SESSION_TERMINATED": 409,
    "CONFLICT": 409,
    "INVALID_HYPOTHESIS_ID": 400,
}


@app.exception_handler(BeliefServerError)
async def _belief_error_handler(_, exc: BeliefServerError):
    status = ERROR_STATUS.get(exc.code, 400)
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )


@app.exception_handler(OplogServerError)
async def _oplog_error_handler(_, exc: OplogServerError):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )


@app.post("/v1/sessions")
def declare_session(req: DeclareSessionRequest):
    ontology = OntologyBundle(
        hypothesis_space_id=req.ontology.hypothesis_space_id,
        hypothesis_version=req.ontology.hypothesis_version,
        causal_graph_ref=req.ontology.causal_graph_ref,
        causal_graph_version=req.ontology.causal_graph_version,
    )
    session_id, snapshot = server.declare_session(
        ontology=ontology,
        hypotheses=req.hypotheses,
        metadata=req.metadata,
    )
    return {"session_id": session_id, "snapshot": snapshot.to_dict()}


@app.post("/v1/sessions/{session_id}/eliminate")
def eliminate(session_id: str, req: EliminateRequest):
    applied, ignored, snapshot, event_id = server.eliminate(
        session_id=session_id,
        source_id=req.source_id,
        observation_id=req.observation_id,
        eliminated=req.eliminated,
        justification=req.justification,
    )
    return {
        "applied_eliminated": applied,
        "ignored_eliminated": ignored,
        "snapshot": snapshot.to_dict(),
        "audit_event_id": event_id,
    }


@app.get("/v1/sessions/{session_id}")
def query_belief(session_id: str):
    snapshot = server.query_belief(session_id=session_id)
    return snapshot.to_dict()


@app.get("/v1/sessions/{session_id}/audit")
def audit_trace(session_id: str, since_event_id: str | None = None):
    events = server.audit_trace(session_id=session_id, since_event_id=since_event_id)
    return {"events": [entry.to_dict() for entry in events]}


@app.post("/v1/sessions/{session_id}/obligations")
def enter_obligation(session_id: str, req: EnterObligationRequest):
    snapshot, event_id = server.enter_obligation(
        session_id=session_id,
        obligation_id=req.obligation_id,
        min_total_eliminations=req.min_total_eliminations,
    )
    return {"snapshot": snapshot.to_dict(), "audit_event_id": event_id}


@app.post("/v1/sessions/{session_id}/obligations/{obligation_id}/exit")
def request_exit(session_id: str, obligation_id: str, req: RequestExitRequest):
    approved, reason, snapshot, event_id = server.request_exit(
        session_id=session_id,
        obligation_id=obligation_id,
        context=req.context,
    )
    return {
        "approved": approved,
        "reason": reason,
        "snapshot": snapshot.to_dict(),
        "audit_event_id": event_id,
    }


@app.post("/v1/sessions/{session_id}/conclusions")
def declare_conclusion(session_id: str, req: DeclareConclusionRequest):
    accepted, reason, snapshot, event_id = server.declare_conclusion(
        session_id=session_id,
        conclusion_id=req.conclusion_id,
        context=req.context,
    )
    return {
        "accepted": accepted,
        "reason": reason,
        "snapshot": snapshot.to_dict(),
        "audit_event_id": event_id,
    }


@app.post("/v1/sessions/{session_id}/terminate")
def request_termination(session_id: str, req: RequestTerminationRequest):
    approved, reason, snapshot, event_id = server.request_termination(
        session_id=session_id,
        context=req.context,
    )
    return {
        "approved": approved,
        "reason": reason,
        "snapshot": snapshot.to_dict(),
        "audit_event_id": event_id,
    }


@app.post("/v2/sessions")
def v2_create_session(req: V2CreateSessionRequest):
    return v2_server.create_session(
        ontology=req.ontology,
        initial_hypotheses=req.initial_hypotheses,
        default_reducer=req.default_reducer,
        metadata=req.metadata,
    )


@app.post("/v2/sessions/{sid}/ops")
def v2_append_op(sid: str, req: V2AppendOpRequest, branch: str = "main"):
    result = v2_server.append_op(
        sid=sid,
        branch_id=branch,
        spec=OperationSpec(
            op_id=req.op_id,
            op_type=req.op_type,
            payload=req.payload,
            source_id=req.source_id,
            preconditions=req.preconditions,
            commutativity_key=req.commutativity_key,
            idempotency_key=req.idempotency_key,
        ),
    )
    return result.to_dict()


@app.post("/v2/sessions/{sid}/branches")
def v2_create_branch(sid: str, req: V2BranchRequest):
    return v2_server.create_branch(
        sid=sid,
        from_branch=req.from_branch,
        from_seq=req.from_seq,
        name=req.name,
        note=req.note,
    )


@app.get("/v2/sessions/{sid}/ops")
def v2_get_ops(
    sid: str,
    branch: str = "main",
    from_seq: int | None = Query(default=None, alias="from"),
    to_seq: int | None = Query(default=None, alias="to"),
):
    return v2_server.get_ops(
        sid=sid,
        branch=branch,
        from_seq=from_seq,
        to_seq=to_seq,
    )


@app.get("/v2/sessions/{sid}/state")
def v2_get_state(
    sid: str,
    branch: str = "main",
    at: int | None = None,
    reducer: str | None = None,
):
    return v2_server.get_state(
        sid=sid,
        branch=branch,
        at=at,
        reducer=reducer,
    )


@app.post("/v2/analysis/commute")
def v2_analysis_commute(req: V2CommutativityRequest):
    return v2_server.analyze_commute(
        sid=req.sid,
        branch=req.branch,
        seq=req.seq,
        reducer=req.reducer,
        op_a=OperationSpec(
            op_id=req.op_a.op_id,
            op_type=req.op_a.op_type,
            payload=req.op_a.payload,
            source_id=req.op_a.source_id,
            preconditions=req.op_a.preconditions,
            commutativity_key=req.op_a.commutativity_key,
            idempotency_key=req.op_a.idempotency_key,
        ),
        op_b=OperationSpec(
            op_id=req.op_b.op_id,
            op_type=req.op_b.op_type,
            payload=req.op_b.payload,
            source_id=req.op_b.source_id,
            preconditions=req.op_b.preconditions,
            commutativity_key=req.op_b.commutativity_key,
            idempotency_key=req.op_b.idempotency_key,
        ),
    )


@app.post("/v2/analysis/replay")
def v2_analysis_replay(req: V2ReplayRequest):
    return v2_server.analyze_replay(
        sid=req.sid,
        branch=req.branch,
        from_seq=req.from_seq,
        to_seq=req.to_seq,
        reducers=req.reducers,
    )


@app.post("/v2/merge")
def v2_merge(req: V2MergeRequest):
    return v2_server.merge(
        sid=req.sid,
        base_branch=req.base.branch,
        base_seq=req.base.seq,
        heads=[{"branch": h.branch, "seq": h.seq} for h in req.heads],
        policy=req.policy,
        reducer=req.reducer,
    )
