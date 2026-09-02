from __future__ import annotations

from fastapi import FastAPI

from research_service import __version__
from research_service.api import router
from research_service.service_factory import build_repository

app = FastAPI(title="ai_stock research-service", version=__version__)
app.include_router(router)


@app.get("/health")
@app.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "research-service", "version": __version__}


@app.get("/readyz")
def readyz() -> dict[str, object]:
    db = build_repository().ready()
    status = "ready" if db.get("status") == "ready" else "degraded"
    return {
        "status": status,
        "service": "research-service",
        "version": __version__,
        "assembler_contract": "research_model_payload_assembler_v1",
        "checks": {"database": db},
        "guardrails": {
            "direct_provider_calls_allowed": False,
            "raw_table_reads_allowed": False,
            "computes_model_scores": False,
            "materializes_owner_model_facts": True,
            "official_signal_requires_owner_release_gate": True,
            "missing_facts_remain_gap_coded": True,
        },
    }
