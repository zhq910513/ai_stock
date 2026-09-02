from __future__ import annotations

from research_center_service.repository import ResearchCenterRepository
from research_center_service.settings import get_settings

settings = get_settings()


def build_repository() -> ResearchCenterRepository:
    return ResearchCenterRepository(settings.effective_database_url)
