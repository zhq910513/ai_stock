from __future__ import annotations

from typing import Any

from source_data_service.adapters.base import ProviderAdapter, dataframe_to_rows
from source_data_service.models import Provider, RawFetchResult


class TushareAdapter(ProviderAdapter):
    provider = Provider.TUSHARE

    def __init__(self, token: str | None = None) -> None:
        self.token = token

    def fetch(self, api_name: str, params: dict[str, Any], *, dry_run: bool = False) -> RawFetchResult:
        if dry_run:
            return self.build_result(api_name, params, [], dry_run=True, warning="dry_run: provider not called")
        if not self.token:
            raise RuntimeError("Tushare token is required for this provider adapter")
        try:
            import tushare as ts  # type: ignore
        except Exception as exc:  # pragma: no cover - optional provider
            raise RuntimeError("tushare package is not installed or cannot be imported") from exc
        ts.set_token(self.token)
        pro = ts.pro_api(self.token)
        if api_name == "daily":
            frame = pro.daily(**params)
        elif api_name == "stock_basic":
            frame = pro.stock_basic(**params)
        elif api_name == "trade_cal":
            frame = pro.trade_cal(**params)
        elif api_name == "adj_factor":
            frame = pro.adj_factor(**params)
        elif api_name == "moneyflow":
            frame = pro.moneyflow(**params)
        elif api_name == "stk_limit":
            frame = pro.stk_limit(**params)
        else:
            raise KeyError(f"unsupported tushare api: {api_name}")
        return self.build_result(api_name, params, dataframe_to_rows(frame))
