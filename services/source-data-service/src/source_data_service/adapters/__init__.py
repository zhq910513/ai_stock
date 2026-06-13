from __future__ import annotations

from source_data_service.adapters.akshare_adapter import AKShareAdapter
from source_data_service.adapters.baostock_adapter import BaoStockAdapter
from source_data_service.adapters.tushare_adapter import TushareAdapter
from source_data_service.models import Provider
from source_data_service.settings import settings


def get_adapter(provider: Provider):
    if provider == Provider.BAOSTOCK:
        return BaoStockAdapter()
    if provider == Provider.AKSHARE:
        return AKShareAdapter()
    if provider == Provider.TUSHARE:
        return TushareAdapter(token=settings.tushare_token)
    raise KeyError(f"provider adapter not implemented yet: {provider.value}")


__all__ = ["get_adapter", "BaoStockAdapter", "AKShareAdapter", "TushareAdapter"]
