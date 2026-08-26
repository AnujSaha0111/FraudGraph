# Case management + EntityRisk API
# HTTP conventions: 404 missing resource, 409 invalid state/conflict, 422 malformed/invalid, 503 underlying storage unavailable.

import uuid
from datetime import UTC, datetime

import duckdb
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.cases.service import CaseError, CaseService
from app.storage.db import connect

router = APIRouter(tags=["cases"])


class CaseCreate(BaseModel):
    transaction_id: int
    title: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    evidence_ids: list[str] = []
    request_id: str | None = None


class CasePatch(BaseModel):
    actor: str = Field(min_length=1)
    status: str | None = None
    note: str | None = None
    request_id: str | None = None


class DecisionCreate(BaseModel):
    decision: str
    actor: str = Field(min_length=1)
    notes: str | None = None
    evidence_ids: list[str] = []
    request_id: str | None = None


def _service(request: Request) -> CaseService:
    """Open the case store or raise 503. Caller MUST close svc.conn."""
    settings = request.app.state.settings
    if not settings.db_path.exists():
        raise HTTPException(status_code=503,
                            detail="case storage unavailable (uninitialized)")
    try:
        conn = connect(settings.db_path)
        return CaseService(conn, settings)
    except HTTPException:
        raise
    except (duckdb.Error, OSError):
        raise HTTPException(status_code=503, detail="case storage unavailable")


@router.post("/cases", status_code=201)
def create_case(body: CaseCreate, request: Request):
    svc = _service(request)
    try:
        return svc.create_case(body.transaction_id, body.title, body.actor,
                               body.evidence_ids,
                               body.request_id or str(uuid.uuid4()))
    except CaseError as e:
        raise HTTPException(status_code=int(e.code), detail=e.detail)
    finally:
        svc.conn.close()


@router.get("/cases")
def list_cases(request: Request, status: str | None = None):
    svc = _service(request)
    try:
        rows = svc.list_cases(status)
        return {"cases": rows, "count": len(rows),
                "request_id": str(uuid.uuid4())}
    except CaseError as e:
        raise HTTPException(status_code=int(e.code), detail=e.detail)
    finally:
        svc.conn.close()


@router.get("/cases/{case_id}")
def get_case(case_id: int, request: Request):
    svc = _service(request)
    try:
        out = svc.get_case(case_id)
        out["request_id"] = str(uuid.uuid4())
        return out
    except CaseError as e:
        raise HTTPException(status_code=int(e.code), detail=e.detail)
    finally:
        svc.conn.close()


@router.patch("/cases/{case_id}")
def patch_case(case_id: int, body: CasePatch, request: Request):
    svc = _service(request)
    try:
        return svc.patch_case(case_id, body.actor, body.status, body.note,
                              body.request_id or str(uuid.uuid4()))
    except CaseError as e:
        raise HTTPException(status_code=int(e.code), detail=e.detail)
    finally:
        svc.conn.close()


@router.post("/cases/{case_id}/decision", status_code=201)
def decide(case_id: int, body: DecisionCreate, request: Request):
    svc = _service(request)
    try:
        return svc.decide(case_id, body.decision, body.actor, body.notes,
                          body.evidence_ids,
                          body.request_id or str(uuid.uuid4()))
    except CaseError as e:
        raise HTTPException(status_code=int(e.code), detail=e.detail)
    finally:
        svc.conn.close()


# --------------- EntityRisk (optional verification endpoint) ----------------


@router.get("/entities/{entity_type}/{entity_key}/risk")
def entity_risk(entity_type: str, entity_key: str, request: Request,
                as_of_ts: int = Query(...)):
    if entity_type not in ("CARD", "DEVICE", "ADDRESS"):
        raise HTTPException(status_code=422,
                            detail="entity_type must be CARD|DEVICE|ADDRESS")
    settings = request.app.state.settings
    if not settings.db_path.exists():
        raise HTTPException(status_code=503, detail="entity storage unavailable")
    try:
        from app.cases.entityrisk import compute_entity_risk
        conn = connect(settings.db_path)
    except HTTPException:
        raise
    except (duckdb.Error, OSError):
        raise HTTPException(status_code=503, detail="entity storage unavailable")
    try:
        r = compute_entity_risk(conn, entity_type, entity_key, as_of_ts,
                                settings.min_label_lag_days)
        return {
            "entity_type": r.entity_type, "entity_key": r.entity_key,
            "as_of_ts": r.as_of_ts,
            "min_label_lag_days": r.min_label_lag_days,
            "eligible_boundary": r.eligible_boundary,
            "entity_fraud_count": r.entity_fraud_count,
            "entity_total_labeled_count": r.entity_total_labeled_count,
            "fraud_rate": r.fraud_rate,
            "computed_at": datetime.now(UTC).replace(
                microsecond=0).isoformat(),
            "note": "delayed investigation context; NOT a model feature",
            "request_id": str(uuid.uuid4()),
        }
    finally:
        conn.close()
