from __future__ import annotations

from functools import lru_cache

try:
    from ai_stock_common.settings import BaseServiceSettings
except ModuleNotFoundError:  # pragma: no cover - local package may be absent in isolated test bundles.
    try:
        from pydantic_settings import BaseSettings as BaseServiceSettings
    except ModuleNotFoundError:
        from pydantic import BaseModel as BaseServiceSettings


class AmbushWatchlistModelServiceSettings(BaseServiceSettings):
    service_name: str = "ambush-watchlist-model-service"
    port: int = 8033


@lru_cache(maxsize=1)
def get_settings() -> AmbushWatchlistModelServiceSettings:
    return AmbushWatchlistModelServiceSettings()
