from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    service_name: str = "research-center-service"
    port: int = 8028
    database_url: str | None = None
    ai_stock_database_url: str | None = None
    default_operator_id: str = "local_researcher"

    @property
    def effective_database_url(self) -> str | None:
        return self.database_url or self.ai_stock_database_url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
