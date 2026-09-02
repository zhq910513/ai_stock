from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


MODEL_CODE = "t_board_relay"
MODEL_NAME = "t_board_relay"
MODEL_VERSION = "t_board_relay_v1"
FEATURE_VERSION = "t_board_relay_feature_v1"
RULE_VERSION = "t_board_relay_rule_v1"
SERVICE_NAME = "t-board-relay-model-service"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    service_name: str = SERVICE_NAME
    database_url: str | None = None
    ai_stock_database_url: str | None = None
    persist_decisions: bool = True
    repository_limit_default: int = 100

    @property
    def effective_database_url(self) -> str | None:
        return self.database_url or self.ai_stock_database_url


@dataclass(frozen=True)
class TBoardRelayRuleConfig:
    model_code: str = MODEL_CODE
    model_version: str = MODEL_VERSION
    feature_version: str = FEATURE_VERSION
    rule_version: str = RULE_VERSION
    day1_float_market_cap_min: Decimal = Decimal("5000000000")
    day1_float_market_cap_max: Decimal = Decimal("30000000000")
    day2_monitor_window_start_time: str = "09:30:00"
    day2_monitor_window_end_time: str = "10:30:00"
    day2_monitor_interval_minutes: int = 5
    day2_near_limit_threshold_pct: Decimal = Decimal("0.01")
    day3_tail_window_start_time: str = "14:40:00"
    day3_tail_window_end_time: str = "14:55:00"


def get_rule_config() -> TBoardRelayRuleConfig:
    return TBoardRelayRuleConfig()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
