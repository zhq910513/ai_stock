from __future__ import annotations

from data_inspector_service.client import ServiceClient
from data_inspector_service.repository import DataInspectorRepository
from data_inspector_service.settings import get_settings


settings = get_settings()


def build_repository() -> DataInspectorRepository:
    return DataInspectorRepository(settings.effective_database_url)


def build_client() -> ServiceClient:
    return ServiceClient(
        source_base_url=settings.source_data_service_base_url,
        scheduler_base_url=settings.scheduler_service_base_url,
        hot_base_url=settings.hot_candidates_service_base_url,
        memory_base_url=settings.candidate_memory_service_base_url,
        ambush_base_url=settings.ambush_watchlist_service_base_url,
        t_board_base_url=settings.t_board_relay_service_base_url,
        timeout_seconds=settings.request_timeout_seconds,
    )
