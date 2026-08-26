# Reserved endpoint stubs.
# These stubs intentionally return 501 — never fake data. They reserve the logical endpoint names that are not part of the released surface; real routers own every implemented path. Response payloads are part of the frozen API surface and are returned verbatim.

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(tags=["placeholders"])


def _not_implemented(reserved: int, detail: str | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=501,
        content={"detail": detail or "not implemented in Phase 1",
                 "owned_by_phase": reserved})


@router.get("/transactions/{txn_id}")
def get_transaction(txn_id: int):
    return _not_implemented(3)


@router.get("/transactions/{txn_id}/risk-legacy")
def get_risk_legacy(txn_id: int):
    return _not_implemented(3)


@router.get("/transactions/{txn_id}/evidence-legacy")
def get_evidence_legacy(txn_id: int):
    return _not_implemented(5)


@router.get("/transactions/{txn_id}/network")
def get_network(txn_id: int):
    return _not_implemented(4)


@router.post("/transactions/{txn_id}/expand")
def expand_community(txn_id: int):
    return _not_implemented(4)


@router.get("/communities/{community_id}")
def get_community(community_id: str):
    return _not_implemented(4)


@router.get("/cases-legacy")
def list_cases_legacy():
    return _not_implemented(6)


@router.post("/cases-create-legacy")
def create_case_legacy():
    return _not_implemented(6)


@router.patch("/cases-legacy/{case_id}")
def update_case_legacy(case_id: int):
    return _not_implemented(6)


@router.post("/cases-legacy/{case_id}/decision")
def decide_case_legacy(case_id: int):
    return _not_implemented(6)
