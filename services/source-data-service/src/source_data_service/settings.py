from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class SourceDataSettings(BaseSettings):
    """Runtime settings for provider adapters and resilience defaults."""

    model_config = SettingsConfigDict(env_prefix="SOURCE_DATA_", env_file=".env", extra="ignore")

    provider_timeout_seconds: float = 12.0
    provider_max_retries: int = 2
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_seconds: int = 60
    tushare_token: str | None = None

    # DS-5 queue durability. Local unit tests use memory by default; Docker/production
    # should set SOURCE_DATA_QUEUE_BACKEND=postgres so producer/consumer jobs,
    # leases, callback outbox events and build triggers survive service restarts.
    queue_backend: str = "memory"
    database_url: str | None = None
    queue_lease_reclaim_seconds: int = 120
    worker_poll_interval_seconds: float = 1.0


settings = SourceDataSettings()
