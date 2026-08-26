# Health/readiness endpoint
from fastapi import APIRouter, Request

from app.storage import db
from app.version import __version__

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request):
    settings = request.app.state.settings
    storage = "unavailable"
    try:
        if settings.db_path.exists():
            conn = db.connect(settings.db_path)
            try:
                ok = db.readiness(conn)
                tables = db.existing_tables(conn)
                storage = ("ok" if ok and
                           db.required_tables().issubset(tables)
                           else "degraded")
            finally:
                conn.close()
        else:
            storage = "uninitialized"
    except Exception:  # noqa: BLE001 - readiness probe must not raise
        storage = "unavailable"
    return {"status": "ok",
            "service": "fraudgraph",
            "version": __version__,
            "env": settings.env,
            "storage": storage}
