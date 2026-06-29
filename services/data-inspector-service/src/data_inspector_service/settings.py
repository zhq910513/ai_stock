from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    service_name: str = "data-inspector-service"
    port: int = 8025
    database_url: str | None = None
    ai_stock_database_url: str | None = None
    source_data_service_base_url: str = "http://source-data-service:8041"
    scheduler_service_base_url: str = "http://scheduler-service:8023"
    hot_candidates_service_base_url: str = "http://hot-candidates-service:8031"
    candidate_memory_service_base_url: str = "http://candidate-memory-service:8032"
    ambush_watchlist_service_base_url: str = "http://ambush-watchlist-service:8033"
    t_board_relay_service_base_url: str = "http://t-board-relay-service:8034"
    data_inspector_required_model_services: str | None = None
    required_model_services: str | None = None
    default_symbol: str = "000063.SZ"
    t_board_default_symbol: str = "000759.SZ"
    default_trade_date: str = "2026-06-12"
    request_timeout_seconds: float = 20.0
    persist_default: bool = True

    @property
    def effective_database_url(self) -> str | None:
        return self.database_url or self.ai_stock_database_url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
