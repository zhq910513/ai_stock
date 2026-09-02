from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from scheduler_service.api import router
from scheduler_service.runtime import runtime


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    runtime.start()
    try:
        yield
    finally:
        runtime.stop()


app = FastAPI(title="ai_stock scheduler-service", version="0.2.0", lifespan=lifespan)
app.include_router(router)
