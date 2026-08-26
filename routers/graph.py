from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["graph"])

@router.get("/transactions/{transaction_id}/graph")
def get_graph(transaction_id: int, request: Request, back_days: int | None = None, fwd_days: int | None = None, hub_cap: int | None = None, neighbor_cap: int | None = None):
    settings = request.app.state.settings
    # check storage available
    try:
        if not (settings.processed_dir / "experiment_base.parquet").exists():
            raise HTTPException(status_code=503, detail="graph index/storage unavailable")
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 - any storage failure maps to 503
        raise HTTPException(status_code=503, detail="graph index/storage unavailable") from None
    # model/risk not required for graph, but we check graph index buildability
    # params
    params = {}
    if back_days is not None:
        params["back_s"] = back_days * 86400
    if fwd_days is not None:
        params["fwd_s"] = fwd_days * 86400
    if hub_cap is not None:
        params["hub_degree_max"] = hub_cap
    if neighbor_cap is not None:
        params["neighbor_cap"] = neighbor_cap
    try:
        from app.graph.service import expand_transaction
        result = expand_transaction(transaction_id, params if params else None, settings)
        return result
    except KeyError as e:
        if str(e) == "'404'":
            raise HTTPException(status_code=404, detail="transaction not found")
        raise HTTPException(status_code=404, detail="transaction not found")
    except ValueError as e:
        if "422" in str(e):
            raise HTTPException(status_code=422, detail="transaction exists but graph expansion is unsupported because required entity information is unavailable")
        if "only depth=1" in str(e):
            raise HTTPException(status_code=422, detail=str(e))
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as ex:  # noqa: BLE001 - last-resort mapping
        # check if graph index unavailable
        if "graph" in str(ex).lower():
            raise HTTPException(status_code=503, detail="graph index/storage unavailable")
        raise HTTPException(status_code=500, detail=str(ex))
