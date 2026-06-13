from __future__ import annotations

import json
from datetime import date, datetime, timezone
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


def _schema_table(table_name: str) -> tuple[str, str]:
    if "." not in table_name:
        raise ValueError(f"table name must be schema-qualified: {table_name}")
    schema, table = table_name.split(".", 1)
    return schema, table


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
    value = _first(row, "code", "代码", "ts_code", "symbol")
    if value is None:
        value = _first(request_params, "code", "symbol", "ts_code")
    return None if value is None else str(value)


def _normalize_symbol(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value)
    if text.startswith("sz."):
        return f"{text[3:]}.SZ"
    if text.startswith("sh."):
        return f"{text[3:]}.SH"
    if text.endswith(".SZ") or text.endswith(".SH"):
        return text
    if text.endswith(".SZ") or text.endswith(".SH"):
        return text
    if len(text) == 6 and text.startswith(("0", "3")):
        return f"{text}.SZ"
    if len(text) == 6 and text.startswith("6"):
        return f"{text}.SH"
    if len(text) == 9 and text.endswith((".SZ", ".SH")):
        return text
    return text


def _column_value(column: str, *, row: dict[str, Any], request_params: dict[str, Any], common: dict[str, Any]) -> Any:
    if column in common:
        return common[column]
    if column == "raw_row_json":
        return json.loads(_json(row))
    if column in {"trade_date", "day", "calendar_date", "update_date", "effective_date"}:
        return _extract_trade_date(row, request_params)
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
    if column in {"volume", "vol"}:
        return _num_or_none(_first(row, "volume", "成交量", "vol"))
    if column == "amount":
        return _num_or_none(_first(row, "amount", "成交额"))
    if column in {"pct_chg", "change_pct"}:
        return _num_or_none(_first(row, "pctChg", "pct_chg", "涨跌幅", "change_pct"))
    if column in {"change_amount", "change"}:
        return _num_or_none(_first(row, "涨跌额", "change", "change_amount"))
    if column == "turnover_rate":
        return _num_or_none(_first(row, "turn", "换手率", "turnover_rate"))
    if column == "amplitude":
        return _num_or_none(_first(row, "振幅", "amplitude"))
    if column == "adjustflag":
        return str(_first(row, "adjustflag") or request_params.get("adjustflag") or "3")
    if column == "adjust":
        return str(_first(row, "adjust") or request_params.get("adjust") or "")
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
                            "symbol": _normalize_symbol(_extract_code(raw.row, request_params)),
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

    def upsert_source_row(self, row: SourceCanonicalRowOut, lineage: list[SourceLineageRecordOut]) -> None:  # pragma: no cover - requires runtime Postgres
        if not self.ready:
            raise RuntimeError("postgres raw/source repository is not ready")
        schema, table = _schema_table(row.source_table_name)
        values = dict(row.values)
        with self._connect() as conn:
            columns = self._columns(conn, schema, table)
            key_cols = [c for c in ["symbol", "trade_date"] if c in columns]
            if row.source_table_name == "source.adjusted_daily_bar_v1" and "adjustment_mode" in columns:
                values.setdefault("adjustment_mode", "qfq")
                key_cols.append("adjustment_mode")
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
            insert_cols = [c for c in columns if c in payload and c != "lineage_id"]
            if "lineage_id" in columns and lineage:
                payload["lineage_id"] = lineage[0].lineage_id
                insert_cols.append("lineage_id")
            placeholders = ",".join(["%s"] * len(insert_cols))
            columns_sql = ",".join(f'"{c}"' for c in insert_cols)
            update_cols = [c for c in insert_cols if c not in key_cols]
            update_sql = ",".join(f'"{c}"=EXCLUDED."{c}"' for c in update_cols)
            conflict_sql = f"({','.join(f'\"{c}\"' for c in key_cols)})" if key_cols else "ON CONSTRAINT does_not_exist"
            qualified = f'"{schema}"."{table}"'
            with conn.cursor() as cur:
                if key_cols:
                    cur.execute(
                        f"INSERT INTO {qualified} ({columns_sql}) VALUES ({placeholders}) ON CONFLICT {conflict_sql} DO UPDATE SET {update_sql}",
                        [payload[c] for c in insert_cols],
                    )
                for lin in lineage:
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
                            int(lin.raw_id) if lin.raw_id and str(lin.raw_id).isdigit() else None,
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
            if trade_date and "trade_date" in cols:
                where.append("trade_date = %s")
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
            values = {k: v for k, v in data.items() if k not in {"symbol", "trade_date", "source_quality_status", "primary_provider", "backup_provider", "lineage_id", "build_batch_id", "captured_at", "available_at"}}
            out.append(
                SourceCanonicalRowOut(
                    source_table_name=source_table_name,
                    source_pk=f"{data.get('symbol')}|{data.get('trade_date')}",
                    symbol=data.get("symbol"),
                    trade_date=data.get("trade_date"),
                    values=values,
                    source_quality_status=QualityStatus(data.get("source_quality_status") or "usable"),
                    primary_provider=Provider(data["primary_provider"]) if data.get("primary_provider") else None,
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
