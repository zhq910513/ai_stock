from __future__ import annotations

from fastapi import FastAPI

from hot_candidates_model_service.api import router
from hot_candidates_model_service.config import get_settings

settings = get_settings()

app = FastAPI(
    title="ai_stock hot-candidates-model-service",
    version="0.1.0",
)
app.include_router(router)
