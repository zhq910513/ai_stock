from __future__ import annotations

from fastapi import FastAPI

from research_center_service import __version__
from research_center_service.api import router
from research_center_service.service_factory import build_repository

app = FastAPI(title="ai_stock research-center-service", version=__version__)
app.include_router(router)


@app.get("/health")
@app.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "research-center-service", "version": __version__}


@app.get("/readyz")
def readyz() -> dict[str, object]:
    db = build_repository().ready()
    status = "ready" if db.get("status") == "ready" else "degraded"
    return {
        "status": status,
        "service": "research-center-service",
        "version": __version__,
        "research_domains": ["research_ambush"],
        "checks": {"database": db},
        "guardrails": {
            "direct_provider_calls_allowed": False,
            "mutates_model_facts": False,
            "mutates_official_signals": False,
            "manual_labels_are_research_assets": True,
        },
    }
