from __future__ import annotations

from source_data_service.adapters.akshare_adapter import AKShareAdapter
from source_data_service.adapters.baidu_adapter import BaiduAdapter
from source_data_service.adapters.baostock_adapter import BaoStockAdapter
from source_data_service.adapters.coingecko_adapter import CoinGeckoAdapter
from source_data_service.adapters.eastmoney_adapter import EastMoneyAdapter
from source_data_service.adapters.jin10_adapter import Jin10Adapter
from source_data_service.adapters.sina_adapter import SinaAdapter
from source_data_service.adapters.sohu_adapter import SohuAdapter
from source_data_service.adapters.tencent_adapter import TencentAdapter
from source_data_service.adapters.ths_adapter import THSAdapter
from source_data_service.adapters.tushare_adapter import TushareAdapter
from source_data_service.adapters.yahoo_adapter import YahooAdapter
from source_data_service.models import Provider
from source_data_service.settings import settings


def get_adapter(provider: Provider):
    if provider == Provider.BAOSTOCK:
        return BaoStockAdapter()
    if provider == Provider.AKSHARE:
        return AKShareAdapter()
    if provider == Provider.EASTMONEY:
        return EastMoneyAdapter()
    if provider == Provider.TENCENT:
        return TencentAdapter()
    if provider == Provider.SOHU:
        return SohuAdapter()
    if provider == Provider.BAIDU:
        return BaiduAdapter()
    if provider == Provider.SINA:
        return SinaAdapter()
    if provider == Provider.THS:
        return THSAdapter()
    if provider == Provider.COINGECKO:
        return CoinGeckoAdapter()
    if provider == Provider.YAHOO:
        return YahooAdapter()
    if provider == Provider.JIN10:
        return Jin10Adapter()
    if provider == Provider.TUSHARE:
        return TushareAdapter(token=settings.tushare_token)
    raise KeyError(f"provider adapter not implemented yet: {provider.value}")


__all__ = [
    "get_adapter",
    "BaoStockAdapter",
    "AKShareAdapter",
    "EastMoneyAdapter",
    "SohuAdapter",
    "TencentAdapter",
    "BaiduAdapter",
    "SinaAdapter",
    "THSAdapter",
    "CoinGeckoAdapter",
    "YahooAdapter",
    "Jin10Adapter",
    "TushareAdapter",
]
