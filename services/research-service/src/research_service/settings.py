from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    service_name: str = "research-service"
    port: int = 8029
    database_url: str | None = None
    ai_stock_database_url: str | None = None
    source_data_service_base_url: str = "http://source-data-service:8041"
    hot_candidates_service_base_url: str = "http://hot-candidates-service:8031"
    candidate_memory_service_base_url: str = "http://candidate-memory-service:8032"
    ambush_watchlist_service_base_url: str = "http://ambush-watchlist-service:8033"
    t_board_relay_service_base_url: str = "http://t-board-relay-service:8034"
    default_symbols: str = "000063.SZ,000759.SZ"
    source_query_limit_daily: int = 40
    source_query_limit_intraday: int = 260
    request_timeout_seconds: float = 12.0

    @property
    def effective_database_url(self) -> str | None:
        return self.database_url or self.ai_stock_database_url

    @property
    def default_symbol_list(self) -> list[str]:
        return [item.strip().upper() for item in self.default_symbols.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
