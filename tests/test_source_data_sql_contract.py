from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL_0012 = (ROOT / "infra/sql/0012_source_data_raw_interface_v1.sql").read_text(encoding="utf-8")
SQL_0013 = (ROOT / "infra/sql/0013_source_data_build_lineage_gap_v1.sql").read_text(encoding="utf-8")
SQL_0014 = (ROOT / "infra/sql/0014_source_existing_provider_raw_contracts_v1.sql").read_text(encoding="utf-8")


def test_raw_interface_tables_are_one_api_one_table() -> None:
    required = [
        "raw_baostock.query_history_k_data_plus_daily_raw_v1",
        "raw_baostock.query_history_k_data_plus_daily_qfq_v1",
        "raw_akshare.stock_zh_a_hist_daily_raw_v1",
        "raw_akshare.stock_zh_a_hist_daily_qfq_v1",
        "raw_tushare.daily_v1",
        "raw_tushare.adj_factor_v1",
    ]
    for table in required:
        assert table in SQL_0012


def test_raw_tables_have_governance_columns() -> None:
    for token in [
        "request_params_json",
        "response_schema_hash",
        "response_row_hash",
        "batch_id",
        "biz_key",
        "captured_at",
        "available_at",
        "raw_row_json",
    ]:
        assert token in SQL_0012


def test_source_lineage_gap_and_repair_tables_exist() -> None:
    for table in [
        "governance.source_table_requirement_v1",
        "governance.provider_field_mapping_v1",
        "governance.source_lineage_v1",
        "governance.source_gap_v1",
        "governance.source_repair_task_v1",
        "governance.source_probe_result_v1",
    ]:
        assert table in SQL_0013


def test_canonical_tables_keep_model_semantics_out() -> None:
    forbidden = ["ambush_score", "hot_score", "memory_score", "buy_signal", "recommendation_signal"]
    lowered = (SQL_0012 + SQL_0013).lower()
    for token in forbidden:
        assert token not in lowered


def test_existing_market_provider_raw_contracts_are_preserved() -> None:
    for table in [
        "raw_eastmoney.quote_snapshot_v1",
        "raw_eastmoney.daily_bars_v1",
        "raw_eastmoney.moneyflow_stock_series_v1",
        "raw_tencent.auction_snapshot_v1",
        "raw_sina.auction_snapshot_v1",
        "raw_cninfo.disclosure_direct_v1",
    ]:
        assert table in SQL_0014
    for token in ["request_params_json", "response_schema_hash", "response_row_hash", "raw_row_json"]:
        assert token in SQL_0014
