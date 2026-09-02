from __future__ import annotations

from fastapi import FastAPI

from t_board_relay_model_service.api import router

app = FastAPI(
    title="ai_stock t-board-relay-model-service",
    version="0.1.0",
)
app.include_router(router)

