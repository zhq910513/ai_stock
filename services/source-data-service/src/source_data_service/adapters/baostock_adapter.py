from __future__ import annotations

from threading import Lock
from typing import Any

from source_data_service.adapters.base import ProviderAdapter
from source_data_service.models import Provider, RawFetchResult


_BAOSTOCK_LOCK = Lock()


class BaoStockAdapter(ProviderAdapter):
    """BaoStock free provider adapter.

    The import is intentionally lazy. Unit tests and service startup must not fail
    when the optional provider package is not installed. Real probes will report a
    provider error instead of bringing the whole service down.
    """

    provider = Provider.BAOSTOCK

    def fetch(self, api_name: str, params: dict[str, Any], *, dry_run: bool = False) -> RawFetchResult:
        if dry_run:
            return self.build_result(api_name, params, [], dry_run=True, warning="dry_run: provider not called")
        with _BAOSTOCK_LOCK:
            return self._fetch_locked(api_name, params)

    def _fetch_locked(self, api_name: str, params: dict[str, Any]) -> RawFetchResult:
        try:
            import baostock as bs  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on optional provider
            raise RuntimeError("baostock package is not installed or cannot be imported") from exc

        login_result = bs.login()
        if getattr(login_result, "error_code", "0") != "0":
            raise RuntimeError(f"baostock login failed: {getattr(login_result, 'error_msg', '')}")
        try:
            if api_name == "query_all_stock":
                rs = bs.query_all_stock(day=params["day"])
            elif api_name == "query_stock_basic":
                rs = bs.query_stock_basic(code=params["code"])
            elif api_name == "query_trade_dates":
                rs = bs.query_trade_dates(start_date=params["start_date"], end_date=params["end_date"])
            elif api_name in {
                "query_history_k_data_plus_daily_raw",
                "query_history_k_data_plus_daily_qfq",
            }:
                adjustflag = params.get("adjustflag") or ("2" if api_name.endswith("qfq") else "3")
                rs = bs.query_history_k_data_plus(
                    params["code"],
                    params.get("fields")
                    or "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,tradestatus,pctChg,isST",
                    start_date=params["start_date"],
                    end_date=params["end_date"],
                    frequency=params.get("frequency", "d"),
                    adjustflag=adjustflag,
                )
            elif api_name == "query_adjust_factor":
                rs = bs.query_adjust_factor(
                    code=params["code"], start_date=params["start_date"], end_date=params["end_date"]
                )
            elif api_name == "query_stock_industry":
                rs = bs.query_stock_industry(date=params["date"])
            else:
                raise KeyError(f"unsupported baostock api: {api_name}")

            rows: list[dict[str, Any]] = []
            while rs.next():
                rows.append(dict(zip(rs.fields, rs.get_row_data(), strict=False)))
            return self.build_result(api_name, params, rows)
        finally:
            try:
                bs.logout()
            except Exception:
                pass
