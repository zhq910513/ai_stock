from __future__ import annotations

from fastapi import FastAPI

from data_inspector_service import __version__
from data_inspector_service.api import router
from data_inspector_service.repository import DataInspectorRepository
from data_inspector_service.service_factory import settings


app = FastAPI(title="ai_stock data-inspector-service", version=__version__)
app.include_router(router)


@app.get("/health")
@app.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "data-inspector-service", "version": __version__}


@app.get("/readyz")
def readyz() -> dict[str, object]:
    repository = DataInspectorRepository(settings.effective_database_url)
    db = repository.ready()
    status = "ready" if db.get("status") == "ready" else "degraded"
    return {
        "status": status,
        "service": "data-inspector-service",
        "version": __version__,
        "checks": {
            "database": db,
            "source_base_url": settings.source_data_service_base_url,
        },
    }
