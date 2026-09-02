from __future__ import annotations

from functools import lru_cache

try:
    from ai_stock_common.settings import BaseServiceSettings
except ModuleNotFoundError:  # pragma: no cover - local package may be absent in isolated test bundles.
    try:
        from pydantic_settings import BaseSettings as BaseServiceSettings
    except ModuleNotFoundError:
        from pydantic import BaseModel as BaseServiceSettings


class CandidateMemoryModelServiceSettings(BaseServiceSettings):
    service_name: str = "candidate-memory-model-service"
    port: int = 8032


@lru_cache(maxsize=1)
def get_settings() -> CandidateMemoryModelServiceSettings:
    return CandidateMemoryModelServiceSettings()
