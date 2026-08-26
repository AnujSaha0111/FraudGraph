# FraudGraph API application factory (modular monolith)
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings, get_settings
from app.routers import (
    cases,
    evidence,
    graph,
    health,
    placeholders,
    risk,
    transactions,
)
from app.version import __version__


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    app = FastAPI(title="FraudGraph",
                  version=__version__,
                  description="Transaction risk + coordinated-risk "
                              "investigation")
    app.state.settings = resolved

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        return JSONResponse(status_code=500,
                            content={"error": "internal_error",
                                     "detail": str(exc),
                                     "path": str(request.url.path)})

    app.include_router(health.router)
    app.include_router(risk.router)
    app.include_router(graph.router)
    app.include_router(evidence.router)
    app.include_router(cases.router)
    app.include_router(transactions.router)
    app.include_router(placeholders.router)

    dist = Path(resolved.frontend_dist_dir)
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True),
                  name="frontend")
    return app


app = create_app()
