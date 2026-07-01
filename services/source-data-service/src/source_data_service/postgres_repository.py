from __future__ import annotations

import json
from datetime import date, datetime, timezone
from datetime import time, timedelta
from decimal import Decimal
from typing import Any

from source_data_service.fetch_persistence import configured_database_url, psycopg_available
from source_data_service.models import (
    Provider,
    RawFetchResult,
    RawIngestResult,
    SourceBuildExecutionResult,
    SourceCanonicalRowOut,
    SourceLineageRecordOut,
    QualityStatus,
)
from source_data_service.provider_registry import get_api_spec
from source_data_service.symbol_rules import normalize_symbol


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _pg_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        from psycopg.types.json import Jsonb

        return Jsonb(value)
    return value


def _json_value(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        return json.loads(value)
    return value


_RAW_RECORD_METADATA_COLUMNS = {
    "raw_id",
    "provider",
    "api_name",
    "request_params_json",
    "request_hash",
    "response_schema_hash",
    "response_row_hash",
    "batch_id",
    "biz_key",
}


def _durable_raw_row_payload(data: dict[str, Any], request_params: dict[str, Any]) -> dict[str, Any]:
    raw_row = _json_value(data.get("raw_row_json"), {})
    if not isinstance(raw_row, dict):
        raw_row = {}
    row = dict(raw_row)

    raw_provider_row = _json_value(data.get("raw_provider_row"), None)
    if raw_provider_row is not None and "raw_provider_row" not in row:
        row["raw_provider_row"] = raw_provider_row

    for key, value in data.items():
        if key in _RAW_RECORD_METADATA_COLUMNS or key == "raw_row_json":
            continue
        if value in (None, "") or key in row:
            continue
        row[key] = value

    if "date" not in row:
        request_date = request_params.get("date")
        trade_date = _date_or_none(data.get("trade_date") or request_params.get("trade_date"))
        if request_date not in (None, ""):
            row["date"] = request_date
        elif trade_date is not None:
            row["date"] = trade_date.strftime("%Y%m%d")
    return row


def _schema_table(table_name: str) -> tuple[str, str]:
    if "." not in table_name:
        raise ValueError(f"table name must be schema-qualified: {table_name}")
    schema, table = table_name.split(".", 1)
    return schema, table


def _split_canonical_symbol(symbol: str | None) -> tuple[str | None, str | None]:
    if not symbol:
        return None, None
    text = str(symbol).strip()
    if "." in text:
        code, exchange = text.split(".", 1)
        return code, exchange.upper()
    if len(text) == 6 and text.startswith(("0", "3")):
        return text, "SZ"
    if len(text) == 6 and text.startswith("6"):
        return text, "SH"
    return text, None


def _daily_bar_event_time(trade_date: date | None) -> datetime | None:
    if trade_date is None:
        return None
    china_tz = timezone(timedelta(hours=8))
    return datetime.combine(trade_date, time(hour=15), tzinfo=china_tz)


def _datetime_or_none(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value)
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _date_or_none(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value)
    try:
        if len(text) == 8 and text.isdigit():
            return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
        if len(text) >= 10:
            return date.fromisoformat(text[:10])
    except Exception:
        return None
    return None


def _bool_or_none(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "t", "yes", "y", "是", "交易", "正常"}:
        return True
    if text in {"0", "false", "f", "no", "n", "否", "停牌"}:
        return False
    return None


def _num_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except Exception:
        return None


def _first(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


def _extract_trade_date(row: dict[str, Any], request_params: dict[str, Any]) -> date | None:
    value = _first(row, "date", "日期", "trade_date", "cal_date", "calendar_date")
    if value is None:
        value = _first(request_params, "trade_date", "day")
    if value is None:
        start = request_params.get("start_date")
        end = request_params.get("end_date")
        if start and start == end:
            value = start
    return _date_or_none(value)


def _extract_code(row: dict[str, Any], request_params: dict[str, Any]) -> str | None:
    value = _first(row, "symbol", "code", "代码", "provider_code", "ts_code", "secid")
    if value is None:
        value = _first(request_params, "code", "symbol", "provider_code", "ts_code", "secid")
    return None if value is None else str(value)


def _normalize_symbol(value: Any) -> str | None:
    return normalize_symbol(value)


def _source_payload_and_key(
    row: SourceCanonicalRowOut,
    columns: list[str],
    *,
    instrument_id: int | None = None,
) -> tuple[dict[str, Any], list[str]]:
    values = dict(row.values)
    base = {
        "symbol": row.symbol,
        "trade_date": row.trade_date,
        "source_quality_status": row.source_quality_status.value,
        "primary_provider": row.primary_provider.value if row.primary_provider else None,
        "build_batch_id": row.build_batch_id,
        "captured_at": row.captured_at,
        "available_at": row.available_at,
    }
    payload: dict[str, Any] = {**base, **values}
    key_cols = [c for c in ["symbol", "trade_date"] if c in columns]

    if row.source_table_name == "source.trade_calendar_v1" and "calendar_date" in columns:
        calendar_date = _date_or_none(values.get("calendar_date")) or row.trade_date
        is_trading_day = values.get("is_trading_day")
        if is_trading_day is None and "is_open" in values:
            is_trading_day = values.get("is_open")
        payload["calendar_date"] = calendar_date
        payload["is_trading_day"] = is_trading_day
        payload.setdefault("exchange", values.get("exchange") or "SSE_SZSE")
        payload["pretrade_date"] = _date_or_none(values.get("pretrade_date") or values.get("prev_trading_day"))
        if "trading_day" in columns:
            payload["trading_day"] = calendar_date
        if "market_code" in columns:
            payload["market_code"] = values.get("market_code") or "CN_A"
        if "is_open" in columns:
            payload["is_open"] = is_trading_day
        if "prev_trading_day" in columns:
            payload["prev_trading_day"] = payload.get("pretrade_date")
        key_cols = ["trading_day", "market_code"] if {"trading_day", "market_code"} <= set(columns) else ["calendar_date"]

    if row.source_table_name == "source.adjusted_daily_bar_v1" and "adjustment_mode" in columns:
        payload.setdefault("adjustment_mode", "qfq")
        key_cols = ["symbol", "trade_date", "adjustment_mode"]

    if row.source_table_name == "source.index_daily_bar_v1" and "index_code" in columns:
        payload["index_code"] = row.symbol
        key_cols = ["index_code", "trade_date"]

    moneyflow_key = {"symbol", "trade_date", "primary_provider"}
    if row.source_table_name == "source.stock_moneyflow_daily_v1" and moneyflow_key <= set(columns):
        if row.primary_provider is None:
            raise RuntimeError("source.stock_moneyflow_daily_v1 physical table requires primary_provider")
        key_cols = ["symbol", "trade_date", "primary_provider"]

    if row.source_table_name == "source.limit_event_v1" and "limit_event_type" in columns:
        if not payload.get("limit_event_type"):
            raise RuntimeError("source.limit_event_v1 physical table requires limit_event_type")
        key_cols = ["symbol", "trade_date", "limit_event_type"]

    if row.source_table_name == "source.event_news_v1" and "event_id" in columns:
        if row.primary_provider is None:
            raise RuntimeError("source.event_news_v1 physical table requires provider")
        payload["event_id"] = row.source_pk
        payload["provider"] = row.primary_provider.value
        payload.setdefault("event_time", row.values.get("published_at") or row.available_at or row.captured_at)
        payload["source_quality_status"] = row.source_quality_status.value
        key_cols = ["event_id"]

    if row.source_table_name == "source.minute_bar_v1" and {"instrument_id", "bar_time", "provider"} <= set(columns):
        if instrument_id is None:
            raise RuntimeError(
                "source.minute_bar_v1 physical table requires a real core.instrument_master instrument_id; "
                f"canonical symbol={row.symbol!r} cannot be persisted without master data"
            )
        if row.primary_provider is None:
            raise RuntimeError("source.minute_bar_v1 physical table requires provider")
        bar_time = _datetime_or_none(values.get("bar_time") or values.get("event_time"))
        if bar_time is None:
            raise RuntimeError("source.minute_bar_v1 requires bar_time/event_time")
        payload["instrument_id"] = instrument_id
        payload["bar_time"] = bar_time
        payload["event_time"] = _datetime_or_none(values.get("event_time")) or bar_time
        payload["provider"] = row.primary_provider.value
        payload["quality_status"] = row.source_quality_status.value
        key_cols = ["instrument_id", "bar_time", "provider"]

    if row.source_table_name == "source.realtime_quote_v1" and {"instrument_id", "event_time", "provider"} <= set(columns):
        if instrument_id is None:
            raise RuntimeError(
                "source.realtime_quote_v1 physical table requires a real core.instrument_master instrument_id; "
                f"canonical symbol={row.symbol!r} cannot be persisted without master data"
            )
        if row.primary_provider is None:
            raise RuntimeError("source.realtime_quote_v1 physical table requires provider")
        event_time = _datetime_or_none(values.get("event_time")) or row.available_at or row.captured_at
        payload["instrument_id"] = instrument_id
        payload["event_time"] = event_time
        payload["latest_price"] = values.get("latest_price") or values.get("last_price")
        payload["provider"] = row.primary_provider.value
        payload["quality_status"] = row.source_quality_status.value
        key_cols = ["instrument_id", "event_time", "provider"]

    if row.source_table_name == "source.auction_snapshot_v1" and {"instrument_id", "trading_day", "snapshot_time", "provider"} <= set(columns):
        if instrument_id is None:
            raise RuntimeError(
                "source.auction_snapshot_v1 physical table requires a real core.instrument_master instrument_id; "
                f"canonical symbol={row.symbol!r} cannot be persisted without master data"
            )
        if row.primary_provider is None:
            raise RuntimeError("source.auction_snapshot_v1 physical table requires provider")
        snapshot_time = _datetime_or_none(values.get("snapshot_time") or values.get("event_time"))
        if snapshot_time is None:
            raise RuntimeError("source.auction_snapshot_v1 requires snapshot_time/event_time")
        payload["instrument_id"] = instrument_id
        payload["trading_day"] = row.trade_date or snapshot_time.date()
        payload["snapshot_time"] = snapshot_time
        payload["event_time"] = _datetime_or_none(values.get("event_time")) or snapshot_time
        payload["provider"] = row.primary_provider.value
        payload["quality_status"] = row.source_quality_status.value
        key_cols = ["instrument_id", "trading_day", "snapshot_time", "provider"]

    if row.source_table_name == "source.trade_tick_v1" and {"symbol", "tick_time", "provider", "provider_sequence"} <= set(columns):
        tick_time = _datetime_or_none(values.get("tick_time"))
        if tick_time is None:
            raise RuntimeError("source.trade_tick_v1 requires tick_time")
        payload["tick_time"] = tick_time
        payload["provider"] = row.primary_provider.value if row.primary_provider else None
        payload["source_quality_status"] = row.source_quality_status.value
        key_cols = ["symbol", "tick_time", "provider", "provider_sequence"]

    legacy_daily_key = {"instrument_id", "trading_day", "adjustment", "provider"}
    if row.source_table_name == "source.daily_bar_v1" and legacy_daily_key <= set(columns):
        if instrument_id is None:
            raise RuntimeError(
                "source.daily_bar_v1 physical table requires a real core.instrument_master instrument_id; "
                f"canonical symbol={row.symbol!r} cannot be persisted without master data"
            )
        if row.primary_provider is None:
            raise RuntimeError("source.daily_bar_v1 physical table requires primary_provider/provider")
        payload["instrument_id"] = instrument_id
        payload["trading_day"] = row.trade_date
        payload.setdefault("trade_date", row.trade_date)
        payload["adjustment"] = "raw"
        payload["provider"] = row.primary_provider.value
        payload["quality_status"] = row.source_quality_status.value
        payload["event_time"] = _daily_bar_event_time(row.trade_date) or row.available_at or row.captured_at
        key_cols = ["instrument_id", "trading_day", "adjustment", "provider"]

    return payload, key_cols


def _source_identity_from_record(source_table_name: str, data: dict[str, Any]) -> tuple[str, str | None, date | None]:
    symbol = data.get("symbol")
    trade_date = data.get("trade_date")
    if source_table_name == "source.trade_calendar_v1":
        calendar_date = _date_or_none(data.get("calendar_date") or data.get("trading_day") or trade_date)
        source_pk = calendar_date.isoformat() if calendar_date else str(data.get("source_pk") or data.get("lineage_id") or "")
        return source_pk, None, calendar_date
    if source_table_name == "source.stock_master_v1":
        source_pk = str(symbol or data.get("source_pk") or data.get("lineage_id") or "")
        return source_pk, symbol, None
    if source_table_name == "source.index_daily_bar_v1":
        symbol = symbol or data.get("index_code")
    if source_table_name == "source.event_news_v1":
        source_pk = data.get("event_id") or data.get("source_pk") or data.get("lineage_id") or ""
        return str(source_pk), symbol, _date_or_none(trade_date)
    if source_table_name == "source.limit_event_v1":
        event_type = data.get("limit_event_type")
        source_pk = f"{symbol}|{trade_date}|{event_type}" if symbol and trade_date and event_type else str(data.get("lineage_id") or "")
        return source_pk, symbol, _date_or_none(trade_date)
    if source_table_name == "source.daily_bar_v1":
        trade_date = trade_date or data.get("trading_day")
    if source_table_name == "source.minute_bar_v1":
        bar_time = _datetime_or_none(data.get("bar_time"))
        source_pk = f"{symbol}|{bar_time.isoformat()}" if symbol and bar_time else str(data.get("source_minute_bar_id") or "")
        return source_pk, symbol, bar_time.date() if bar_time else _date_or_none(trade_date)
    if source_table_name == "source.realtime_quote_v1":
        event_time = _datetime_or_none(data.get("event_time"))
        source_pk = f"{symbol}|{event_time.isoformat()}" if symbol and event_time else str(data.get("quote_id") or "")
        return source_pk, symbol, event_time.date() if event_time else _date_or_none(trade_date)
    if source_table_name == "source.auction_snapshot_v1":
        snapshot_time = _datetime_or_none(data.get("snapshot_time") or data.get("event_time"))
        provider = data.get("provider")
        source_pk = (
            f"{symbol}|{snapshot_time.isoformat()}|{provider}"
            if symbol and snapshot_time and provider
            else str(data.get("auction_snapshot_id") or "")
        )
        return source_pk, symbol, _date_or_none(data.get("trading_day")) or (snapshot_time.date() if snapshot_time else _date_or_none(trade_date))
    if source_table_name == "source.trade_tick_v1":
        tick_time = _datetime_or_none(data.get("tick_time"))
        provider_sequence = data.get("provider_sequence")
        source_pk = f"{symbol}|{tick_time.isoformat()}|{provider_sequence}" if symbol and tick_time else str(data.get("trade_tick_id") or "")
        return source_pk, symbol, tick_time.date() if tick_time else _date_or_none(trade_date)
    trade_date_value = _date_or_none(trade_date)
    if symbol and trade_date_value:
        return f"{symbol}|{trade_date_value}", symbol, trade_date_value
    source_pk = data.get("source_pk") or data.get("lineage_id") or ""
    return str(source_pk), symbol, trade_date_value


def _lineage_raw_id(lin: SourceLineageRecordOut) -> int | None:
    return int(lin.raw_id) if lin.raw_id and str(lin.raw_id).isdigit() else None


def _source_lineage_identity(lin: SourceLineageRecordOut) -> tuple[Any, ...]:
    return (
        lin.source_table_name,
        lin.source_pk,
        lin.canonical_field_name,
        lin.provider.value,
        lin.api_name,
        lin.raw_table_name,
        _lineage_raw_id(lin),
        lin.request_hash,
        lin.response_row_hash,
    )


def _source_lineage_lock_key(identity: tuple[Any, ...]) -> str:
    return "source_lineage_v1:" + "|".join("" if value is None else str(value) for value in identity)


def _select_existing_lineage_id(cur: Any, identity: tuple[Any, ...]) -> str | None:
    cur.execute(
        "SELECT pg_advisory_xact_lock(hashtext(%s)::bigint)",
        (_source_lineage_lock_key(identity),),
    )
    cur.execute(
        """
        SELECT lineage_id
        FROM governance.source_lineage_v1
        WHERE source_table_name = %s
          AND source_pk = %s
          AND canonical_field_name = %s
          AND provider = %s
          AND api_name = %s
          AND raw_table_name = %s
          AND raw_id IS NOT DISTINCT FROM %s
          AND request_hash IS NOT DISTINCT FROM %s
          AND response_row_hash IS NOT DISTINCT FROM %s
        ORDER BY created_at ASC, lineage_id ASC
        LIMIT 1
        """,
        identity,
    )
    record = cur.fetchone()
    return str(record[0]) if record else None


def _raw_row_matches_requested_identity(raw_symbol: str | None, raw_trade_date: date | None, symbol: str | None, trade_date_value: date | None) -> bool:
    if symbol and raw_symbol != symbol:
        return False
    if trade_date_value and raw_trade_date != trade_date_value:
        return False
    return True


def _column_value(column: str, *, row: dict[str, Any], request_params: dict[str, Any], common: dict[str, Any]) -> Any:
    if column in common:
        return common[column]
    if column == "raw_row_json":
        return json.loads(_json(row))
    if column in {"trade_date", "day", "calendar_date", "update_date", "effective_date"}:
        return _extract_trade_date(row, request_params)
    if column in {"bar_time", "event_time", "tick_time"}:
        return _datetime_or_none(_first(row, column, "datetime", "time"))
    if column == "code":
        return _extract_code(row, request_params)
    if column == "symbol":
        return _normalize_symbol(_extract_code(row, request_params))
    if column == "ts_code":
        return _first(row, "ts_code") or request_params.get("ts_code")
    if column in {"name", "code_name", "stock_name", "board_name"}:
        return _first(row, "name", "名称", "code_name", "股票简称", "板块名称")
    if column == "open_price":
        return _num_or_none(_first(row, "open", "开盘", "open_price"))
    if column == "high_price":
        return _num_or_none(_first(row, "high", "最高", "high_price"))
    if column == "low_price":
        return _num_or_none(_first(row, "low", "最低", "low_price"))
    if column == "close_price":
        return _num_or_none(_first(row, "close", "收盘", "close_price"))
    if column in {"pre_close_price", "prev_close_price"}:
        return _num_or_none(_first(row, "preclose", "pre_close", "昨收", "prev_close_price"))
    if column == "last_price":
        return _num_or_none(_first(row, "最新价", "last_price", "close"))
    if column == "latest_price":
        return _num_or_none(_first(row, "latest_price", "last_price", "close"))
    if column in {"volume", "vol"}:
        return _num_or_none(_first(row, "volume", "成交量", "vol"))
    if column == "amount":
        return _num_or_none(_first(row, "amount", "成交额"))
    if column in {"pct_chg", "change_pct"}:
        return _num_or_none(_first(row, "pctChg", "pct_chg", "涨跌幅", "change_pct"))
    if column in {"change_amount", "change"}:
        return _num_or_none(_first(row, "涨跌额", "change", "change_amount"))
    if column == "main_net_inflow":
        return _num_or_none(_first(row, "main_net_inflow", "net_mf_amount", "net_inflow"))
    if column == "super_large_net_inflow":
        return _num_or_none(_first(row, "super_large_net_inflow"))
    if column == "large_net_inflow":
        return _num_or_none(_first(row, "large_net_inflow"))
    if column == "medium_net_inflow":
        return _num_or_none(_first(row, "medium_net_inflow"))
    if column == "small_net_inflow":
        return _num_or_none(_first(row, "small_net_inflow"))
    if column == "provider_definition":
        return _first(row, "provider_definition") or request_params.get("provider_definition")
    if column in {"total_market_cap", "float_market_cap"}:
        return _num_or_none(_first(row, column))
    if column in {"trade_count", "provider_sequence"}:
        return _num_or_none(_first(row, column))
    if column in {"side_code", "side_label"}:
        return _first(row, column)
    if column == "price":
        return _num_or_none(_first(row, "price"))
    if column == "turnover_rate":
        return _num_or_none(_first(row, "turn", "换手率", "turnover_rate"))
    if column == "amplitude":
        return _num_or_none(_first(row, "振幅", "amplitude"))
    if column == "adjustflag":
        return str(_first(row, "adjustflag") or request_params.get("adjustflag") or "3")
    if column == "adjust":
        return str(_first(row, "adjust") or request_params.get("adjust") or "")
    if column == "adjustment_mode":
        return str(_first(row, "adjustment_mode") or request_params.get("adjustment") or request_params.get("adjust") or "")
    if column == "trade_status":
        return _first(row, "tradestatus", "tradeStatus", "trade_status")
    if column == "is_st":
        return _bool_or_none(_first(row, "isST", "is_st"))
    if column == "is_trading_day":
        return _bool_or_none(_first(row, "is_trading_day", "is_open"))
    if column in row:
        return row[column]
    return None


class PostgresRawSourceRepository:
    """Postgres implementation for raw/source/lineage writes.

    The service keeps the public API identical in memory and Postgres modes.
    Production must use this repository so provider results, source rows,
    lineage, and write audits survive container restarts.
    """

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or configured_database_url()

    @property
    def ready(self) -> bool:
        return bool(self.database_url) and psycopg_available()

    def _connect(self):  # pragma: no cover - requires runtime Postgres
        if not self.database_url:
            raise RuntimeError("database URL is not configured")
        import psycopg

        return psycopg.connect(self.database_url)

    def _columns(self, conn: Any, schema: str, table: str) -> list[str]:  # pragma: no cover - requires runtime Postgres
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
                """,
                (schema, table),
            )
            return [r[0] for r in cur.fetchall()]

    def _instrument_id_for_symbol(self, conn: Any, symbol: str | None) -> int | None:  # pragma: no cover - requires runtime Postgres
        code, exchange = _split_canonical_symbol(symbol)
        if not code:
            return None
        with conn.cursor() as cur:
            if exchange:
                cur.execute(
                    """
                    SELECT instrument_id
                    FROM core.instrument_master
                    WHERE symbol = %s AND exchange = %s
                    LIMIT 1
                    """,
                    (code, exchange),
                )
            else:
                cur.execute(
                    """
                    SELECT instrument_id
                    FROM core.instrument_master
                    WHERE symbol = %s
                    LIMIT 1
                    """,
                    (code,),
                )
            found = cur.fetchone()
        return int(found[0]) if found else None

    def insert_raw_result(self, result: RawFetchResult) -> tuple[list[dict[str, Any]], int, int]:  # pragma: no cover - requires runtime Postgres
        if not self.ready:
            raise RuntimeError("postgres raw/source repository is not ready")
        spec = get_api_spec(result.provider, result.api_name)
        schema, table = _schema_table(spec.raw_table_name)
        inserted: list[dict[str, Any]] = []
        duplicate = 0
        with self._connect() as conn:
            cols = self._columns(conn, schema, table)
            insertable_cols = [c for c in cols if c != "raw_id"]
            with conn.cursor() as cur:
                for raw in result.rows:
                    request_params = raw.request_params or result.request_params
                    common = {
                        "provider": result.provider.value,
                        "api_name": result.api_name,
                        "request_params_json": json.loads(_json(request_params)),
                        "request_hash": raw.request_hash or result.request_hash,
                        "response_schema_hash": raw.response_schema_hash or result.response_schema_hash,
                        "response_row_hash": raw.response_row_hash,
                        "batch_id": raw.batch_id,
                        "biz_key": raw.biz_key,
                        "captured_at": raw.captured_at,
                        "available_at": raw.available_at or raw.captured_at,
                    }
                    values = [_pg_value(_column_value(c, row=raw.row, request_params=request_params, common=common)) for c in insertable_cols]
                    placeholders = ",".join(["%s"] * len(insertable_cols))
                    qualified = f'"{schema}"."{table}"'
                    columns_sql = ",".join(f'"{c}"' for c in insertable_cols)
                    cur.execute(
                        f"INSERT INTO {qualified} ({columns_sql}) VALUES ({placeholders}) ON CONFLICT DO NOTHING RETURNING raw_id",
                        values,
                    )
                    fetched = cur.fetchone()
                    if not fetched:
                        duplicate += 1
                        continue
                    raw_id = fetched[0]
                    inserted.append(
                        {
                            "raw_id": raw_id,
                            "provider": result.provider,
                            "api_name": result.api_name,
                            "raw_table_name": spec.raw_table_name,
                            "request_params": request_params,
                            "request_hash": raw.request_hash or result.request_hash,
                            "response_schema_hash": raw.response_schema_hash or result.response_schema_hash,
                            "response_row_hash": raw.response_row_hash,
                            "row": dict(raw.row),
                            "symbol": _normalize_symbol(raw.row.get("symbol") or _extract_code(raw.row, request_params)),
                            "trade_date": str(_extract_trade_date(raw.row, request_params)) if _extract_trade_date(raw.row, request_params) else None,
                            "captured_at": raw.captured_at,
                            "available_at": raw.available_at or raw.captured_at,
                            "batch_id": raw.batch_id,
                            "biz_key": raw.biz_key,
                            "quality_status": raw.quality_status,
                        }
                    )
                conn.commit()
        return inserted, duplicate, 0

    def insert_raw_write_audit(self, ingest: RawIngestResult) -> None:  # pragma: no cover - requires runtime Postgres
        if not self.ready:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO governance.raw_interface_write_audit_v1 (
                        raw_write_id, provider, api_name, raw_table_name, request_hash,
                        response_schema_hash, ingested_row_count, duplicate_row_count,
                        rejected_row_count, raw_write_status, quality_status, warnings_json
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                    ON CONFLICT (raw_write_id) DO NOTHING
                    """,
                    (
                        f"raw_write_{abs(hash((ingest.provider.value, ingest.api_name, ingest.request_hash, utcnow().isoformat())))}",
                        ingest.provider.value,
                        ingest.api_name,
                        ingest.raw_table_name,
                        ingest.request_hash,
                        ingest.response_schema_hash,
                        ingest.ingested_row_count,
                        ingest.duplicate_row_count,
                        ingest.rejected_row_count,
                        ingest.raw_write_status,
                        ingest.quality_status,
                        _json(ingest.warnings),
                    ),
                )
            conn.commit()

    def read_raw_rows(
        self,
        *,
        provider: Provider,
        api_name: str,
        raw_table_name: str,
        request_hash: str | None = None,
        symbol: str | None = None,
        trade_date: str | date | None = None,
    ) -> list[dict[str, Any]]:  # pragma: no cover - requires runtime Postgres
        if not self.ready:
            return []
        schema, table = _schema_table(raw_table_name)
        trade_date_value = _date_or_none(trade_date)
        with self._connect() as conn:
            cols = self._columns(conn, schema, table)
            where = []
            params: list[Any] = []
            if "provider" in cols:
                where.append("provider = %s")
                params.append(provider.value)
            if "api_name" in cols:
                where.append("api_name = %s")
                params.append(api_name)
            if symbol and "symbol" in cols:
                where.append("symbol = %s")
                params.append(symbol)
            if trade_date_value and "trade_date" in cols:
                where.append("trade_date = %s")
                params.append(trade_date_value)
            elif trade_date_value and "day" in cols:
                where.append("day = %s")
                params.append(trade_date_value)
            if request_hash and "request_hash" in cols and not (symbol or trade_date_value):
                # The orchestration request_hash and provider/raw request_hash
                # can differ. Symbol/date scoped source builds must recover by
                # business identity after process restart, otherwise duplicate
                # build triggers cannot find already-ingested durable raw rows.
                where.append("request_hash = %s")
                params.append(request_hash)
            sql = f'SELECT * FROM "{schema}"."{table}"'
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY captured_at DESC LIMIT 20000"
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
                names = [d.name for d in cur.description]
        out: list[dict[str, Any]] = []
        for record in rows:
            data = dict(zip(names, record))
            request_params = _json_value(data.get("request_params_json"), {})
            raw_row = _durable_raw_row_payload(data, request_params)
            raw_symbol = _normalize_symbol(data.get("symbol") or _extract_code(raw_row, request_params))
            raw_trade_date = _extract_trade_date(raw_row, request_params) or _date_or_none(data.get("trade_date") or data.get("day"))
            if not _raw_row_matches_requested_identity(raw_symbol, raw_trade_date, symbol, trade_date_value):
                continue
            out.append(
                {
                    "raw_id": str(data.get("raw_id")),
                    "provider": provider,
                    "api_name": api_name,
                    "raw_table_name": raw_table_name,
                    "request_params": request_params,
                    "request_hash": data.get("request_hash"),
                    "response_schema_hash": data.get("response_schema_hash"),
                    "response_row_hash": data.get("response_row_hash"),
                    "row": raw_row,
                    "symbol": raw_symbol,
                    "trade_date": str(raw_trade_date) if raw_trade_date else None,
                    "captured_at": data.get("captured_at"),
                    "available_at": data.get("available_at") or data.get("captured_at"),
                    "batch_id": data.get("batch_id"),
                    "biz_key": data.get("biz_key") or (f"{raw_symbol}|{raw_trade_date}" if raw_symbol and raw_trade_date else None),
                    "quality_status": QualityStatus.USABLE,
                }
            )
        return out

    def upsert_source_row(self, row: SourceCanonicalRowOut, lineage: list[SourceLineageRecordOut]) -> None:  # pragma: no cover - requires runtime Postgres
        if not self.ready:
            raise RuntimeError("postgres raw/source repository is not ready")
        schema, table = _schema_table(row.source_table_name)
        with self._connect() as conn:
            columns = self._columns(conn, schema, table)
            requires_instrument = row.source_table_name in {"source.auction_snapshot_v1", "source.daily_bar_v1", "source.minute_bar_v1", "source.realtime_quote_v1"}
            instrument_id = self._instrument_id_for_symbol(conn, row.symbol) if requires_instrument else None
            payload, key_cols = _source_payload_and_key(row, columns, instrument_id=instrument_id)
            qualified = f'"{schema}"."{table}"'
            with conn.cursor() as cur:
                existing_lineage_ids: dict[int, str] = {}
                lineage_identity_ids: dict[tuple[Any, ...], str] = {}
                for idx, lin in enumerate(lineage):
                    identity = _source_lineage_identity(lin)
                    if identity in lineage_identity_ids:
                        existing_lineage_ids[idx] = lineage_identity_ids[identity]
                        continue
                    existing_lineage_id = _select_existing_lineage_id(cur, identity)
                    if existing_lineage_id:
                        existing_lineage_ids[idx] = existing_lineage_id
                        lineage_identity_ids[identity] = existing_lineage_id
                    else:
                        lineage_identity_ids[identity] = lin.lineage_id

                insert_cols = [c for c in columns if c in payload and c != "lineage_id"]
                if "lineage_id" in columns and lineage:
                    payload["lineage_id"] = existing_lineage_ids.get(0, lineage[0].lineage_id)
                    insert_cols.append("lineage_id")
                placeholders = ",".join(["%s"] * len(insert_cols))
                columns_sql = ",".join(f'"{c}"' for c in insert_cols)
                update_cols = [c for c in insert_cols if c not in key_cols]
                update_sql = ",".join(f'"{c}"=EXCLUDED."{c}"' for c in update_cols)
                quoted_key_cols = ",".join(f'"{c}"' for c in key_cols)
                conflict_sql = f"({quoted_key_cols})" if key_cols else "ON CONSTRAINT does_not_exist"
                if key_cols:
                    if not update_sql:
                        update_sql = f'"{key_cols[0]}"=EXCLUDED."{key_cols[0]}"'
                    cur.execute(
                        f"INSERT INTO {qualified} ({columns_sql}) VALUES ({placeholders}) ON CONFLICT {conflict_sql} DO UPDATE SET {update_sql}",
                        [payload[c] for c in insert_cols],
                    )
                for idx, lin in enumerate(lineage):
                    if idx in existing_lineage_ids:
                        continue
                    cur.execute(
                        """
                        INSERT INTO governance.source_lineage_v1 (
                            lineage_id, source_table_name, source_pk, canonical_field_name,
                            provider, api_name, raw_table_name, raw_id, batch_id,
                            request_hash, response_row_hash, build_batch_id, confidence_score
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT DO NOTHING
                        """,
                        (
                            lin.lineage_id,
                            lin.source_table_name,
                            lin.source_pk,
                            lin.canonical_field_name,
                            lin.provider.value,
                            lin.api_name,
                            lin.raw_table_name,
                            _lineage_raw_id(lin),
                            None,
                            lin.request_hash,
                            lin.response_row_hash,
                            lin.build_batch_id,
                            lin.confidence_score,
                        ),
                    )
                    cur.execute(
                        """
                        INSERT INTO governance.source_canonical_write_audit_v1 (
                            source_write_id, source_table_name, source_pk, symbol, trade_date,
                            canonical_fields, provider, api_name, raw_table_name, request_hash,
                            build_batch_id, source_quality_status, available_at, captured_at
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT DO NOTHING
                        """,
                        (
                            f"source_write_{lin.lineage_id}",
                            row.source_table_name,
                            row.source_pk,
                            row.symbol,
                            row.trade_date,
                            list(row.values.keys()),
                            lin.provider.value,
                            lin.api_name,
                            lin.raw_table_name,
                            lin.request_hash,
                            lin.build_batch_id,
                            row.source_quality_status.value,
                            row.available_at,
                            row.captured_at,
                        ),
                    )
            conn.commit()

    def prune_stock_universe_non_a_share_rows(self, trade_date: str | date | None) -> int:  # pragma: no cover - requires runtime Postgres
        if not self.ready or trade_date in (None, ""):
            return 0
        trade_date_value = _date_or_none(trade_date)
        if trade_date_value is None:
            return 0
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM source.stock_universe_daily_v1
                    WHERE trade_date = %s
                      AND NOT (
                        (symbol ~ '^[0-9]{6}\\.SH$' AND left(symbol, 2) IN ('60', '68'))
                        OR (symbol ~ '^[0-9]{6}\\.SZ$' AND left(symbol, 2) IN ('00', '30'))
                        OR (symbol ~ '^[0-9]{6}\\.BJ$' AND (left(symbol, 1) IN ('4', '8') OR left(symbol, 2) = '92'))
                      )
                    """,
                    (trade_date_value,),
                )
                deleted = int(cur.rowcount or 0)
            conn.commit()
        return deleted

    def insert_build_result(self, result: SourceBuildExecutionResult) -> None:  # pragma: no cover - requires runtime Postgres
        if not self.ready:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO governance.source_build_execution_result_v1 (
                        build_execution_id, trigger_id, fetch_batch_id, job_item_id,
                        source_table_name, build_batch_id, status, raw_row_count,
                        source_row_count, lineage_row_count, quality_issue_count,
                        errors_json, warnings_json, started_at, finished_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s)
                    ON CONFLICT (build_execution_id) DO NOTHING
                    """,
                    (
                        f"build_exec_{result.trigger_id}_{result.build_batch_id}",
                        result.trigger_id,
                        result.fetch_batch_id,
                        result.job_item_id,
                        result.source_table_name,
                        result.build_batch_id,
                        result.status,
                        result.raw_row_count,
                        result.source_row_count,
                        result.lineage_row_count,
                        result.quality_issue_count,
                        _json(result.errors),
                        _json(result.warnings),
                        result.started_at,
                        result.finished_at,
                    ),
                )
            conn.commit()

    def read_build_results(self) -> list[SourceBuildExecutionResult]:  # pragma: no cover - requires runtime Postgres
        if not self.ready:
            return []
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        trigger_id,
                        fetch_batch_id,
                        job_item_id,
                        source_table_name,
                        build_batch_id,
                        status,
                        raw_row_count,
                        source_row_count,
                        lineage_row_count,
                        quality_issue_count,
                        errors_json,
                        warnings_json,
                        started_at,
                        finished_at
                    FROM governance.source_build_execution_result_v1
                    ORDER BY finished_at DESC
                    LIMIT 1000
                    """
                )
                rows = cur.fetchall()
        return [
            SourceBuildExecutionResult(
                trigger_id=row[0],
                fetch_batch_id=row[1],
                job_item_id=row[2],
                source_table_name=row[3],
                build_batch_id=row[4],
                status=row[5],
                raw_row_count=row[6],
                source_row_count=row[7],
                lineage_row_count=row[8],
                quality_issue_count=row[9],
                errors=_json_value(row[10], []),
                warnings=_json_value(row[11], []),
                started_at=row[12],
                finished_at=row[13],
            )
            for row in rows
        ]

    def repository_counts(self) -> dict[str, int]:  # pragma: no cover - requires runtime Postgres
        if not self.ready:
            return {}
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT table_schema, table_name
                    FROM information_schema.tables
                    WHERE table_type = 'BASE TABLE'
                      AND table_schema LIKE 'raw_%'
                    """
                )
                raw_tables = cur.fetchall()
                raw_count = 0
                for schema, table in raw_tables:
                    cur.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}"')
                    raw_count += int(cur.fetchone()[0])
                cur.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_type = 'BASE TABLE'
                      AND table_schema = 'source'
                    """
                )
                source_tables = [row[0] for row in cur.fetchall()]
                source_count = 0
                for table in source_tables:
                    cur.execute(f'SELECT COUNT(*) FROM "source"."{table}"')
                    source_count += int(cur.fetchone()[0])
                cur.execute("SELECT COUNT(*) FROM governance.source_lineage_v1")
                lineage_count = int(cur.fetchone()[0])
                cur.execute("SELECT COUNT(*) FROM governance.source_build_execution_result_v1")
                build_result_count = int(cur.fetchone()[0])
        return {
            "raw_row_count": raw_count,
            "source_row_count": source_count,
            "lineage_row_count": lineage_count,
            "build_result_count": build_result_count,
        }

    def read_source_rows(self, source_table_name: str | None = None, symbol: str | None = None, trade_date: str | None = None) -> list[SourceCanonicalRowOut]:  # pragma: no cover - requires runtime Postgres
        # Keep this intentionally narrow for source daily bars used by acceptance.
        if not self.ready or not source_table_name:
            return []
        schema, table = _schema_table(source_table_name)
        with self._connect() as conn:
            cols = self._columns(conn, schema, table)
            where = []
            params: list[Any] = []
            if symbol and "symbol" in cols:
                where.append("symbol = %s")
                params.append(symbol)
            elif symbol and "index_code" in cols:
                where.append("index_code = %s")
                params.append(symbol)
            if trade_date and "trade_date" in cols:
                where.append("trade_date = %s")
                params.append(trade_date)
            elif trade_date and "trading_day" in cols:
                where.append("trading_day = %s")
                params.append(trade_date)
            sql = f'SELECT * FROM "{schema}"."{table}"'
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " LIMIT 1000"
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
                names = [d.name for d in cur.description]
        out: list[SourceCanonicalRowOut] = []
        for record in rows:
            data = dict(zip(names, record))
            source_pk, canonical_symbol, canonical_trade_date = _source_identity_from_record(source_table_name, data)
            values = {
                k: v
                for k, v in data.items()
                if k
                not in {
                    "source_daily_bar_id",
                    "auction_snapshot_id",
                    "source_minute_bar_id",
                    "quote_id",
                    "trade_tick_id",
                    "event_id",
                    "instrument_id",
                    "symbol",
                    "index_code",
                    "trade_date",
                    "trading_day",
                    "adjustment",
                    "provider",
                    "quality_status",
                    "source_quality_status",
                    "primary_provider",
                    "provider",
                    "backup_provider",
                    "lineage_id",
                    "build_batch_id",
                    "captured_at",
                    "available_at",
                    "event_time",
                    "provider_payload_id",
                    "payload_hash",
                }
            }
            out.append(
                SourceCanonicalRowOut(
                    source_table_name=source_table_name,
                    source_pk=source_pk,
                    symbol=canonical_symbol,
                    trade_date=canonical_trade_date,
                    values=values,
                    source_quality_status=QualityStatus(data.get("source_quality_status") or data.get("quality_status") or "usable"),
                    primary_provider=Provider(data.get("primary_provider") or data.get("provider")) if data.get("primary_provider") or data.get("provider") else None,
                    build_batch_id=data.get("build_batch_id"),
                    captured_at=data.get("captured_at"),
                    available_at=data.get("available_at"),
                    updated_at=utcnow(),
                )
            )
        return out

    def read_lineage_records(self, source_table_name: str | None = None, source_pk: str | None = None, canonical_field_name: str | None = None) -> list[SourceLineageRecordOut]:  # pragma: no cover - requires runtime Postgres
        if not self.ready:
            return []
        where = []
        params: list[Any] = []
        if source_table_name:
            where.append("source_table_name = %s")
            params.append(source_table_name)
        if source_pk:
            where.append("source_pk = %s")
            params.append(source_pk)
        if canonical_field_name:
            where.append("canonical_field_name = %s")
            params.append(canonical_field_name)
        sql = "SELECT lineage_id, source_table_name, source_pk, canonical_field_name, provider, api_name, raw_table_name, raw_id, request_hash, response_row_hash, build_batch_id, confidence_score, created_at FROM governance.source_lineage_v1"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC LIMIT 1000"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                records = cur.fetchall()
        return [
            SourceLineageRecordOut(
                lineage_id=r[0],
                source_table_name=r[1],
                source_pk=r[2],
                canonical_field_name=r[3],
                provider=Provider(r[4]),
                api_name=r[5],
                raw_table_name=r[6],
                raw_id=str(r[7]) if r[7] is not None else None,
                request_hash=r[8],
                response_row_hash=r[9],
                build_batch_id=r[10],
                confidence_score=float(r[11]),
                created_at=r[12],
            )
            for r in records
        ]
