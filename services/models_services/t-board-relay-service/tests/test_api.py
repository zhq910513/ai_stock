from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from t_board_relay_model_service import api
from t_board_relay_model_service.main import app
from t_board_relay_model_service.repository import OBSERVATION_COLUMNS


API_SOURCE = Path(api.__file__)


def _day1_row() -> dict[str, object]:
    return {
        "canonical_symbol": "000001.SZ",
        "stock_name": "测试股份",
        "trade_date": "2026-06-15",
        "open_price": "11.00",
        "high_price": "11.00",
        "low_price": "10.38",
        "close_price": "11.00",
        "pre_close_price": "10.00",
        "up_limit_price": "11.00",
        "is_one_word_limit": False,
        "limit_open_count": 2,
        "close_on_limit_flag": True,
        "first_open_board_time": "09:42:10",
        "last_reseal_time": "14:38:30",
        "total_open_board_minutes": "23",
        "max_open_board_drawdown_pct": "0.018",
        "float_market_cap": "12000000000",
        "final_seal_order_amount": "72000000",
        "max_seal_order_amount": "110000000",
        "avg_seal_order_amount_after_reseal": "68000000",
    }


def test_t_board_relay_healthz_and_readyz() -> None:
    client = TestClient(app)

    assert client.get("/healthz").json() == {"status": "ok", "service": "t-board-relay-model-service"}
    ready = client.get("/t-board-relay/readyz")

    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ready.json()["model_version"] == "t_board_relay_v1"


def test_day1_scan_qualifies_strict_t_board_and_ratios() -> None:
    response = TestClient(app).post("/t-board-relay/day1/scan", json={"rows": [_day1_row()]})

    assert response.status_code == 200
    body = response.json()
    candidate = body["structured_output"]["day1_scan"]["candidates"][0]
    assert body["model_name"] == "t_board_relay"
    assert candidate["candidate_status"] == "qualified"
    assert candidate["is_t_board"] is True
    assert candidate["float_market_cap_pass"] is True
    assert candidate["final_seal_to_float_mcap_ratio"] == "0.00600000"
    assert body["jarvis_payload"]["guardrails"]["can_place_order"] is False
    assert "repository_write" in body["structured_output"]


def test_day1_scan_accepts_source_limit_event_field_names() -> None:
    row = _day1_row()
    row.pop("is_one_word_limit")
    row["is_one_word_board"] = False

    response = TestClient(app).post("/t-board-relay/day1/scan", json={"rows": [row]})

    candidate = response.json()["structured_output"]["day1_scan"]["candidates"][0]
    assert candidate["candidate_status"] == "qualified"
    assert "source_gap:one_word_limit_flag_missing" not in candidate["source_gap_codes"]


def test_day1_one_word_limit_is_rejected_not_repaired() -> None:
    row = _day1_row()
    row["low_price"] = "11.00"
    row["is_one_word_limit"] = True
    row["limit_open_count"] = 0

    response = TestClient(app).post("/t-board-relay/day1/scan", json={"rows": [row]})

    candidate = response.json()["structured_output"]["day1_scan"]["candidates"][0]
    assert candidate["candidate_status"] == "rejected"
    assert candidate["reject_reason"] == "not_t_board"
    assert candidate["is_t_board"] is False


def test_day2_trigger_preserves_raw_label_and_standardizes_side() -> None:
    response = TestClient(app).post(
        "/t-board-relay/day2/trigger-check",
        json={
            "payload": {
                "day1_candidate_status": "qualified",
                "canonical_symbol": "000001.SZ",
                "day2_trade_date": "2026-06-16",
                "last_price_at_trigger": "10.92",
                "up_limit_price": "11.00",
                "distance_to_up_limit_pct": "0.0072",
                "market_context_status": "supportive",
                "order_consumption_raw_label": "ALL_BUY_ORDERS_CONSUMED",
                "aggressive_buy_sweep_amount": "38000000",
                "near_limit_order_absorption_score": "82",
                "ask_absorption_speed_near_limit": "9",
                "dynamic_feature_run_id": "dyn-1",
            }
        },
    )

    trigger = response.json()["structured_output"]["day2_entry_trigger"]
    assert trigger["entry_trigger_status"] == "triggered"
    assert trigger["order_consumption_raw_label"] == "ALL_BUY_ORDERS_CONSUMED"
    assert trigger["order_consumption_side"] == "ASK"
    assert trigger["game_hypothesis"]["dominant_capital_intent"] == "relay"


def test_near_limit_triggers_with_ask_sweep_even_when_order_book_gap_is_warning() -> None:
    response = TestClient(app).post(
        "/t-board-relay/day2/trigger-check",
        json={
            "payload": {
                "day1_candidate_status": "qualified",
                "distance_to_up_limit_pct": "0.002",
                "up_limit_price": "11.00",
                "market_context_status": "supportive",
                "p0_order_book_complete": False,
                "p0_trade_tick_complete": True,
                "order_consumption_side": "ASK",
                "order_consumption_amount": "3000000",
                "dynamic_feature_run_id": "dyn-2",
            }
        },
    )

    body = response.json()
    trigger = body["structured_output"]["day2_entry_trigger"]
    assert trigger["entry_trigger_status"] == "triggered"
    assert "source_gap:order_book_snapshot_missing" in body["contract_gaps"]
    assert "source_gap:near_limit_order_absorption_missing" in body["contract_gaps"]


def test_near_limit_without_ask_sweep_confirmation_is_data_blocked() -> None:
    response = TestClient(app).post(
        "/t-board-relay/day2/trigger-check",
        json={
            "payload": {
                "day1_candidate_status": "qualified",
                "distance_to_up_limit_pct": "0.002",
                "up_limit_price": "11.00",
                "market_context_status": "supportive",
                "p0_trade_tick_complete": True,
                "order_consumption_amount": "3000000",
                "near_limit_order_absorption_score": "70",
            }
        },
    )

    trigger = response.json()["structured_output"]["day2_entry_trigger"]
    assert trigger["entry_trigger_status"] == "data_blocked"
    assert trigger["not_trigger_reason"] == "day2_ask_sweep_confirmation_missing"


def test_bid_pressure_hit_buy_orders_does_not_trigger_entry() -> None:
    response = TestClient(app).post(
        "/t-board-relay/day2/trigger-check",
        json={
            "payload": {
                "day1_candidate_status": "qualified",
                "distance_to_up_limit_pct": "0.002",
                "up_limit_price": "11.00",
                "market_context_status": "supportive",
                "order_consumption_side": "BID",
                "order_consumption_amount": "3000000",
                "near_limit_order_absorption_score": "70",
            }
        },
    )

    trigger = response.json()["structured_output"]["day2_entry_trigger"]
    assert trigger["entry_trigger_status"] == "not_triggered"
    assert trigger["not_trigger_reason"] == "day2_bid_pressure_hit_buy_orders"
    assert trigger["order_consumption_interpretation"] == "bearish"


def test_post_entry_any_open_board_is_failed_even_if_resealed() -> None:
    response = TestClient(app).post(
        "/t-board-relay/post-entry/monitor",
        json={
            "payload": {
                "entry_trigger_id": "entry-1",
                "canonical_symbol": "000001.SZ",
                "post_entry_board_opened": True,
                "close_on_limit_flag": True,
                "first_board_open_time_after_entry": "13:14:00",
                "board_open_count_after_entry": 1,
            }
        },
    )

    monitor = response.json()["structured_output"]["post_entry_monitor"]
    assert monitor["post_entry_status"] == "FAILED_AFTER_OPEN"
    assert monitor["outcome_label"] == "day2_board_open_after_entry_failed"
    assert monitor["control_failure_score"] == "100"


def test_day3_open_limit_holds_and_tail_no_limit_exits() -> None:
    client = TestClient(app)

    hold = client.post(
        "/t-board-relay/day3/exit-check",
        json={"payload": {"day3_open_limit_up_flag": True, "day3_tail_limit_up_flag": True}},
    ).json()["structured_output"]["day3_exit_decision"]
    exit_decision = client.post(
        "/t-board-relay/day3/exit-check",
        json={"payload": {"day3_open_limit_up_flag": False, "day3_tail_limit_up_flag": False}},
    ).json()["structured_output"]["day3_exit_decision"]

    assert hold["day3_action"] == "hold_open_limit"
    assert exit_decision["day3_action"] == "exit_tail_no_limit"


def test_repository_write_is_called_when_repository_attached(monkeypatch) -> None:  # noqa: ANN001
    calls = []

    class FakeRepository:
        def persist_response(self, **kwargs):  # noqa: ANN001
            calls.append(kwargs)
            return {"persisted": True, "stage": kwargs["stage"], "inserted_count": 1, "primary_keys": [1]}

        def status(self):
            return {"repository_attached": True, "warning_codes": []}

    monkeypatch.setattr(api, "_repository", lambda: FakeRepository())

    response = TestClient(app).post("/t-board-relay/day1/scan", json={"rows": [_day1_row()], "run_id": "repo-test-1"})

    body = response.json()
    assert response.status_code == 200
    assert calls[0]["stage"] == "day1_scan"
    assert calls[0]["run_id"] == "repo-test-1"
    assert body["structured_output"]["repository_write"]["persisted"] is True


def test_observation_board_excludes_day1_rejected_rows(monkeypatch) -> None:  # noqa: ANN001
    class FakeRepository:
        def status(self):
            return {"repository_attached": True, "warning_codes": []}

        def list_rows(self, entity, *, limit=100):  # noqa: ANN001, ARG002
            if entity == "day1_candidates":
                return [
                    {
                        "day1_candidate_id": "day1-rejected",
                        "canonical_symbol": "000759.SZ",
                        "stock_name": "测试股份",
                        "trade_date": "2026-06-12",
                        "candidate_status": "rejected",
                        "reject_reason": "not_t_board",
                        "is_t_board": False,
                        "float_market_cap_pass": False,
                        "created_at": "2026-06-19T02:18:20",
                    }
                ]
            return []

    monkeypatch.setattr(api, "_repository", lambda: FakeRepository())

    body = TestClient(app).get("/t-board-relay/observation-board").json()

    assert body["contract_kind"] == "t_board_relay_observation_board_v1"
    assert body["items"] == []
    assert body["excluded_counts"]["day1_not_qualified"] == 1


def test_observation_board_queries_qualified_day1_before_page_limit(monkeypatch) -> None:  # noqa: ANN001
    class FakeRepository:
        def status(self):
            return {"repository_attached": True, "warning_codes": []}

        def list_day1_observation_candidates(self, *, limit=100):  # noqa: ANN001, ARG002
            return [
                {
                    "day1_candidate_id": "day1-qualified-late",
                    "canonical_symbol": "600769.SH",
                    "stock_name": "测试股份",
                    "trade_date": "2026-06-22",
                    "candidate_status": "qualified",
                    "is_t_board": True,
                    "float_market_cap_pass": True,
                    "created_at": "2026-06-22T15:10:00",
                }
            ]

        def list_rows(self, entity, *, limit=100):  # noqa: ANN001, ARG002
            if entity == "day1_candidates":
                return [
                    {
                        "day1_candidate_id": f"day1-rejected-{idx}",
                        "canonical_symbol": f"000{idx:03d}.SZ",
                        "trade_date": "2026-06-22",
                        "candidate_status": "rejected",
                        "is_t_board": False,
                        "float_market_cap_pass": False,
                        "created_at": "2026-06-22T15:30:00",
                    }
                    for idx in range(30)
                ]
            return []

    monkeypatch.setattr(api, "_repository", lambda: FakeRepository())

    body = TestClient(app).get("/t-board-relay/observation-board?limit=1").json()

    assert len(body["items"]) == 1
    assert body["items"][0]["stock"]["symbol"] == "600769.SH"
    assert body["items"][0]["current_stage"] == "Day1 已入选"


def test_observation_board_uses_lightweight_stage_rows(monkeypatch) -> None:  # noqa: ANN001
    calls: list[str] = []

    class FakeRepository:
        def status(self):
            return {"repository_attached": True, "warning_codes": []}

        def list_day1_observation_candidates(self, *, limit=100):  # noqa: ANN001, ARG002
            return [
                {
                    "day1_candidate_id": "day1-qualified",
                    "canonical_symbol": "000001.SZ",
                    "stock_name": "Test",
                    "trade_date": "2026-06-12",
                    "candidate_status": "qualified",
                    "is_t_board": True,
                    "float_market_cap_pass": True,
                    "created_at": "2026-06-12T15:10:00",
                }
            ]

        def list_observation_rows(self, entity, *, limit=100):  # noqa: ANN001, ARG002
            calls.append(entity)
            return []

        def list_rows(self, entity, *, limit=100):  # noqa: ANN001, ARG002
            raise AssertionError("observation-board should use lightweight stage rows")

    monkeypatch.setattr(api, "_repository", lambda: FakeRepository())

    body = TestClient(app).get("/t-board-relay/observation-board").json()

    assert len(body["items"]) == 1
    assert calls == ["day2_watch", "day2_triggers", "post_entry_status", "day3_decisions", "outcomes", "game_hypotheses"]


def test_observation_board_projects_day2_watch_before_trigger(monkeypatch) -> None:  # noqa: ANN001
    class FakeRepository:
        def status(self):
            return {"repository_attached": True, "warning_codes": []}

        def list_day1_observation_candidates(self, *, limit=100):  # noqa: ANN001, ARG002
            return [
                {
                    "day1_candidate_id": "day1-qualified",
                    "canonical_symbol": "002297.SZ",
                    "stock_name": "\u535a\u4e91\u65b0\u6750",
                    "trade_date": "2026-06-22",
                    "candidate_status": "qualified",
                    "is_t_board": True,
                    "float_market_cap_pass": True,
                    "created_at": "2026-06-22T15:10:00",
                }
            ]

        def list_observation_rows(self, entity, *, limit=100):  # noqa: ANN001, ARG002
            if entity == "day2_watch":
                return [
                    {
                        "day2_watch_pk": 7,
                        "day2_watch_snapshot_id": "watch-1",
                        "day1_candidate_id": "day1-qualified",
                        "canonical_symbol": "002297.SZ",
                        "day2_trade_date": "2026-06-23",
                        "as_of_time": "2026-06-23T09:40:00",
                        "watch_status": "near_limit_reached",
                        "near_limit_flag": True,
                        "created_at": "2026-06-23T09:40:03",
                    }
                ]
            return []

        def list_rows(self, entity, *, limit=100):  # noqa: ANN001, ARG002
            raise AssertionError("observation-board should use lightweight stage rows")

    monkeypatch.setattr(api, "_repository", lambda: FakeRepository())

    item = TestClient(app).get("/t-board-relay/observation-board").json()["items"][0]

    assert item["day2_trade_date"] == "2026-06-23"
    assert item["day2_trigger_time"] == "09:40:00"
    assert item["latest_snapshot_time"] == "2026-06-23T09:40:03"
    assert item["updated_at"] == "2026-06-23T09:40:03"
    assert item["last_monitor_at"] == "2026-06-23T09:40:00"
    assert item["monitor_interval_minutes"] == 5
    assert item["monitoring_summary"] == "Day2 每5分钟滚动监测，最近检查 09:40:00"
    assert item["model_score"] == 58.0
    assert item["model_score_label"] == "\u4f4e"
    assert item["score_state"] == "scored"
    assert item["model_score_version"] == "t_board_relay_observation_score_v1"
    assert item["relay_strength_label"] == "\u5f85\u786e\u8ba4"
    assert item["current_conclusion"] == "Day2 \u5df2\u63a5\u8fd1\u6da8\u505c\uff0c\u7b49\u5f85\u76d8\u53e3\u786e\u8ba4"
    assert item["key_reason"] == "Day2 09:40:00 \u4e94\u5206\u949f\u76d1\u6d4b\u5df2\u63a5\u8fd1\u6da8\u505c"
    assert "ASK" not in item["risk_tip"]
    assert "BID" not in item["risk_tip"]
    assert all("source_gap:" not in label for label in item["data_gap_labels"])


def test_observation_columns_exclude_audit_payloads() -> None:
    forbidden = {"request_payload", "result_payload", "game_hypothesis_payload", "evidence_json", "related_payload"}

    for columns in OBSERVATION_COLUMNS.values():
        assert forbidden.isdisjoint(columns)


def test_observation_key_reason_uses_day_labels() -> None:
    for line in API_SOURCE.read_text(encoding="utf-8").splitlines():
        if "key_reason =" in line:
            assert "次日" not in line
            assert "第三日" not in line
            assert "BID" not in line
            assert "ASK" not in line
        if "risk_tip =" in line:
            assert "BID" not in line
            assert "ASK" not in line
            assert "不自动下单" not in line
            assert "仅作观察" not in line


def test_observation_board_ignores_same_day_day2_fact(monkeypatch) -> None:  # noqa: ANN001
    class FakeRepository:
        def status(self):
            return {"repository_attached": True, "warning_codes": []}

        def list_rows(self, entity, *, limit=100):  # noqa: ANN001, ARG002
            if entity == "day1_candidates":
                return [
                    {
                        "day1_candidate_id": "day1-qualified",
                        "canonical_symbol": "000001.SZ",
                        "stock_name": "测试股份",
                        "trade_date": "2026-06-12",
                        "candidate_status": "qualified",
                        "is_t_board": True,
                        "float_market_cap_pass": True,
                        "source_gap_codes": ["source_gap:seal_order_snapshot_missing"],
                        "created_at": "2026-06-12T15:10:00",
                    }
                ]
            if entity == "day2_triggers":
                return [
                    {
                        "entry_trigger_id": "entry-same-day",
                        "day1_candidate_id": "day1-qualified",
                        "canonical_symbol": "000001.SZ",
                        "day2_trade_date": "2026-06-12",
                        "entry_trigger_status": "triggered",
                        "relay_consensus_score": "88",
                        "source_gap_codes": ["source_gap:dynamic_feature_bundle_missing"],
                        "created_at": "2026-06-12T09:35:00",
                    }
                ]
            return []

    monkeypatch.setattr(api, "_repository", lambda: FakeRepository())

    item = TestClient(app).get("/t-board-relay/observation-board").json()["items"][0]

    assert item["day2_trade_date"] is None
    assert item["current_conclusion"] == "等待Day2开盘后滚动观察"
    assert item["data_notice"] == "Day2交易日待校验"
    assert "source_gap:" not in str(item)


def test_observation_board_returns_user_facing_valid_day2_projection(monkeypatch) -> None:  # noqa: ANN001
    class FakeRepository:
        def status(self):
            return {"repository_attached": True, "warning_codes": []}

        def list_rows(self, entity, *, limit=100):  # noqa: ANN001, ARG002
            if entity == "day1_candidates":
                return [
                    {
                        "day1_candidate_id": "day1-qualified",
                        "canonical_symbol": "000001.SZ",
                        "stock_name": "测试股份",
                        "trade_date": "2026-06-12",
                        "candidate_status": "qualified",
                        "is_t_board": True,
                        "float_market_cap_pass": True,
                        "created_at": "2026-06-12T15:10:00",
                    }
                ]
            if entity == "day2_triggers":
                return [
                    {
                        "entry_trigger_id": "entry-valid",
                        "day1_candidate_id": "day1-qualified",
                        "canonical_symbol": "000001.SZ",
                        "day2_trade_date": "2026-06-15",
                        "entry_trigger_status": "triggered",
                        "order_consumption_side": "ASK",
                        "order_consumption_amount": "3000000",
                        "relay_consensus_score": "88",
                        "source_gap_codes": ["source_gap:near_limit_order_absorption_missing"],
                        "trigger_time": "09:35:00",
                        "created_at": "2026-06-15T09:35:00",
                    }
                ]
            return []

    monkeypatch.setattr(api, "_repository", lambda: FakeRepository())

    body = TestClient(app).get("/t-board-relay/observation-board").json()
    item = body["items"][0]

    assert item["current_conclusion"] == "接力机会已触发，可买入观察"
    assert item["current_stage"] == "Day2 观察"
    assert item["key_reason"] == "Day2 接近涨停，买盘主动扫掉卖盘"
    assert item["next_observation"] == "继续每5分钟跟踪封板强度和开板风险"
    assert item["risk_tip"] == "买盘扫卖盘已确认，后续只看封板能否维持到收盘"
    assert item["day2_trade_date"] == "2026-06-15"
    assert item["day2_trigger_time"] == "09:35:00"
    assert item["updated_at"] == "2026-06-15T09:35:00"
    assert item["last_monitor_at"] == "09:35:00"
    assert item["monitor_interval_minutes"] == 5
    assert item["monitoring_summary"] == "Day2 09:35:00 触发后，按每5分钟跟踪封板"
    assert item["relay_strength_label"] == "强"
    assert item["data_gap_labels"] == ["盘口吸收待补"]
    assert "source_gap:" not in str(body)


def test_observation_board_describes_missed_day2_as_rolling_monitor_end(monkeypatch) -> None:  # noqa: ANN001
    class FakeRepository:
        def status(self):
            return {"repository_attached": True, "warning_codes": []}

        def list_rows(self, entity, *, limit=100):  # noqa: ANN001, ARG002
            if entity == "day1_candidates":
                return [
                    {
                        "day1_candidate_id": "day1-qualified",
                        "canonical_symbol": "600769.SH",
                        "stock_name": "祥龙电业",
                        "trade_date": "2026-06-22",
                        "candidate_status": "qualified",
                        "is_t_board": True,
                        "float_market_cap_pass": True,
                        "created_at": "2026-06-22T15:10:00",
                    }
                ]
            if entity == "day2_triggers":
                return [
                    {
                        "entry_trigger_id": "entry-missed",
                        "day1_candidate_id": "day1-qualified",
                        "canonical_symbol": "600769.SH",
                        "day2_trade_date": "2026-06-23",
                        "entry_trigger_status": "not_triggered",
                        "not_trigger_reason": "day2_not_near_limit_rolling_5m",
                        "relay_consensus_score": "20",
                        "trigger_time": "10:30:00",
                        "created_at": "2026-06-23T10:30:03",
                    }
                ]
            return []

    monkeypatch.setattr(api, "_repository", lambda: FakeRepository())

    item = TestClient(app).get("/t-board-relay/observation-board").json()["items"][0]

    assert item["observation_status"] == "stopped"
    assert item["key_reason"] == "Day2 09:30-10:30 每5分钟监测均未接近涨停"
    assert item["monitoring_summary"] == "Day2 09:30-10:30 每5分钟监测已结束，未接近涨停"


def test_observation_board_reclassifies_legacy_bid_trigger_as_stopped(monkeypatch) -> None:  # noqa: ANN001
    class FakeRepository:
        def status(self):
            return {"repository_attached": True, "warning_codes": []}

        def list_rows(self, entity, *, limit=100):  # noqa: ANN001, ARG002
            if entity == "day1_candidates":
                return [
                    {
                        "day1_candidate_id": "day1-qualified",
                        "canonical_symbol": "000001.SZ",
                        "stock_name": "测试股份",
                        "trade_date": "2026-06-12",
                        "candidate_status": "qualified",
                        "is_t_board": True,
                        "float_market_cap_pass": True,
                        "created_at": "2026-06-12T15:10:00",
                    }
                ]
            if entity == "day2_triggers":
                return [
                    {
                        "entry_trigger_id": "entry-bid-risk",
                        "day1_candidate_id": "day1-qualified",
                        "canonical_symbol": "000001.SZ",
                        "day2_trade_date": "2026-06-15",
                        "entry_trigger_status": "triggered",
                        "order_consumption_side": "BID",
                        "order_consumption_amount": "3000000",
                        "relay_consensus_score": "60",
                        "trigger_time": "09:35:00",
                        "created_at": "2026-06-15T09:35:00",
                    }
                ]
            return []

    monkeypatch.setattr(api, "_repository", lambda: FakeRepository())

    item = TestClient(app).get("/t-board-relay/observation-board").json()["items"][0]

    assert item["observation_status"] == "stopped"
    assert "可买入" not in item["current_conclusion"]
    assert item["current_conclusion"] == "卖盘主动砸向买盘，停止观察"
    assert item["key_reason"] == "Day2 接近涨停时卖盘主动砸向买盘"
    assert item["risk_tip"] == "接近涨停时卖盘主动砸向买盘，承接转弱，追高风险高"
    assert "BID" not in str(item)
    assert "ASK" not in str(item)
    assert "次日" not in item["key_reason"]
    assert item["day2_trigger_time"] == "09:35:00"


def test_observation_board_updates_after_post_entry_board_open(monkeypatch) -> None:  # noqa: ANN001
    class FakeRepository:
        def status(self):
            return {"repository_attached": True, "warning_codes": []}

        def list_rows(self, entity, *, limit=100):  # noqa: ANN001, ARG002
            if entity == "day1_candidates":
                return [
                    {
                        "day1_candidate_id": "day1-qualified",
                        "canonical_symbol": "600172.SH",
                        "stock_name": "黄河旋风",
                        "trade_date": "2026-06-22",
                        "candidate_status": "qualified",
                        "is_t_board": True,
                        "float_market_cap_pass": True,
                        "created_at": "2026-06-22T15:10:00",
                    }
                ]
            if entity == "day2_triggers":
                return [
                    {
                        "entry_trigger_id": "entry-valid",
                        "day1_candidate_id": "day1-qualified",
                        "canonical_symbol": "600172.SH",
                        "day2_trade_date": "2026-06-23",
                        "entry_trigger_status": "triggered",
                        "order_consumption_side": "ASK",
                        "order_consumption_amount": "3000000",
                        "relay_consensus_score": "66",
                        "trigger_time": "09:35:00",
                        "created_at": "2026-06-23T09:35:03",
                    }
                ]
            if entity == "post_entry_status":
                return [
                    {
                        "post_entry_monitor_id": "monitor-open",
                        "entry_trigger_id": "entry-valid",
                        "canonical_symbol": "600172.SH",
                        "day2_trade_date": "2026-06-23",
                        "post_entry_status": "FAILED_AFTER_OPEN",
                        "outcome_label": "day2_board_open_after_entry_failed",
                        "created_at": "2026-06-23T14:20:03",
                    }
                ]
            return []

    monkeypatch.setattr(api, "_repository", lambda: FakeRepository())

    item = TestClient(app).get("/t-board-relay/observation-board").json()["items"][0]

    assert item["observation_status"] == "stopped"
    assert item["current_conclusion"] == "触发后开板，停止观察"
    assert item["key_reason"] == "Day2 触发后封板维护出现开板"
    assert item["risk_tip"] == "触发后开板，封板维护失败，Day3退出风险升高"
    assert item["updated_at"] == "2026-06-23T14:20:03"
    assert item["last_monitor_at"] == "2026-06-23T14:20:03"
    assert item["model_score"] == 0.0
    assert item["monitoring_summary"] == "Day2 触发后封板维护已更新，最近更新 14:20:03"


def test_observation_board_orders_by_model_score_before_update_time(monkeypatch) -> None:  # noqa: ANN001
    seen_limits: list[tuple[str, int]] = []

    class FakeRepository:
        def status(self):
            return {"repository_attached": True, "warning_codes": []}

        def list_day1_observation_candidates(self, *, limit=100):  # noqa: ANN001
            seen_limits.append(("day1", limit))
            rows = [
                {
                    "day1_candidate_id": "day1-low",
                    "canonical_symbol": "600769.SH",
                    "stock_name": "祥龙电业",
                    "trade_date": "2026-06-22",
                    "candidate_status": "qualified",
                    "is_t_board": True,
                    "float_market_cap_pass": True,
                    "created_at": "2026-06-22T15:10:00",
                },
                {
                    "day1_candidate_id": "day1-high",
                    "canonical_symbol": "600172.SH",
                    "stock_name": "黄河旋风",
                    "trade_date": "2026-06-22",
                    "candidate_status": "qualified",
                    "is_t_board": True,
                    "float_market_cap_pass": True,
                    "created_at": "2026-06-22T15:09:00",
                },
            ]
            return rows[:limit]

        def list_observation_rows(self, entity, *, limit=100):  # noqa: ANN001
            seen_limits.append((entity, limit))
            if entity == "day2_triggers":
                rows = [
                    {
                        "entry_trigger_id": "entry-low",
                        "day1_candidate_id": "day1-low",
                        "canonical_symbol": "600769.SH",
                        "day2_trade_date": "2026-06-23",
                        "entry_trigger_status": "not_triggered",
                        "not_trigger_reason": "day2_not_near_limit_rolling_5m",
                        "relay_consensus_score": "20",
                        "trigger_time": "10:30:00",
                        "created_at": "2026-06-23T10:30:03",
                    },
                    {
                        "entry_trigger_id": "entry-high",
                        "day1_candidate_id": "day1-high",
                        "canonical_symbol": "600172.SH",
                        "day2_trade_date": "2026-06-23",
                        "entry_trigger_status": "triggered",
                        "order_consumption_side": "ASK",
                        "order_consumption_amount": "3000000",
                        "relay_consensus_score": "84",
                        "trigger_time": "09:35:00",
                        "created_at": "2026-06-23T09:35:03",
                    },
                ]
                return rows[:limit]
            return []

        def list_rows(self, entity, *, limit=100):  # noqa: ANN001, ARG002
            raise AssertionError("observation-board should use lightweight stage rows")

    monkeypatch.setattr(api, "_repository", lambda: FakeRepository())

    items = TestClient(app).get("/t-board-relay/observation-board?limit=1").json()["items"]

    assert [item["stock"]["symbol"] for item in items] == ["600172.SH"]
    assert [item["model_score"] for item in items] == [84.0]
    assert ("day1", api.OBSERVATION_SORT_WINDOW_LIMIT) in seen_limits
    assert ("day2_triggers", api.OBSERVATION_SORT_WINDOW_LIMIT) in seen_limits


def test_observation_monitor_snapshot_persists_current_projection(monkeypatch) -> None:  # noqa: ANN001
    persisted: dict[str, object] = {}

    class FakeRepository:
        def status(self):
            return {"repository_attached": True, "warning_codes": []}

        def list_day1_observation_candidates(self, *, limit=100):  # noqa: ANN001, ARG002
            return [
                {
                    "day1_candidate_pk": 1,
                    "day1_candidate_id": "day1-1",
                    "canonical_symbol": "600172.SH",
                    "stock_name": "黄河旋风",
                    "trade_date": "2026-06-22",
                    "candidate_status": "qualified",
                    "is_t_board": True,
                    "float_market_cap_pass": True,
                    "source_gap_codes": [],
                    "created_at": "2026-06-22T15:20:00+08:00",
                }
            ]

        def list_observation_rows(self, entity, *, limit=100):  # noqa: ANN001, ARG002
            if entity == "day2_triggers":
                return [
                    {
                        "entry_trigger_pk": 1,
                        "entry_trigger_id": "entry-1",
                        "day1_candidate_id": "day1-1",
                        "canonical_symbol": "600172.SH",
                        "day2_trade_date": "2026-06-23",
                        "trigger_time": "09:35:00",
                        "entry_trigger_status": "triggered",
                        "order_consumption_side": "ASK",
                        "order_consumption_amount": "1000000",
                        "relay_consensus_score": 80,
                        "source_gap_codes": [],
                        "created_at": "2026-06-23T09:35:00+08:00",
                    }
                ]
            return []

        def persist_observation_monitor_snapshots(self, **kwargs):  # noqa: ANN001
            persisted.update(kwargs)
            return {"persisted": True, "inserted_count": len(kwargs["items"]), "primary_keys": [11]}

    repo = FakeRepository()
    monkeypatch.setattr(api, "_repository", lambda: repo)

    response = TestClient(app).post(
        "/t-board-relay/observation-monitor/snapshot",
        json={
            "payload": {"trade_date": "2026-06-23", "limit": 20},
            "as_of_time_utc": "2026-06-23T01:40:00Z",
            "run_id": "snapshot-test",
        },
    )

    assert response.status_code == 200
    body = response.json()["structured_output"]
    assert body["repository_write"]["persisted"] is True
    assert body["repository_write"]["inserted_count"] == 1
    assert body["observation_monitor_snapshot"]["snapshot_count"] == 1
    assert persisted["run_id"] == "snapshot-test"
    snapshot_item = persisted["items"][0]
    assert snapshot_item["snapshot_day_index"] == 2
    assert snapshot_item["current_conclusion"] == "接力机会已触发，可买入观察"
    assert snapshot_item["model_score"] is not None


def test_observation_board_uses_latest_monitor_snapshot_when_newer(monkeypatch) -> None:  # noqa: ANN001
    class FakeRepository:
        def status(self):
            return {"repository_attached": True, "warning_codes": []}

        def list_day1_observation_candidates(self, *, limit=100):  # noqa: ANN001, ARG002
            return [
                {
                    "day1_candidate_pk": 1,
                    "day1_candidate_id": "day1-1",
                    "canonical_symbol": "002297.SZ",
                    "stock_name": "博云新材",
                    "trade_date": "2026-06-22",
                    "candidate_status": "qualified",
                    "is_t_board": True,
                    "float_market_cap_pass": True,
                    "source_gap_codes": [],
                    "created_at": "2026-06-22T15:20:00+08:00",
                }
            ]

        def list_observation_rows(self, entity, *, limit=100):  # noqa: ANN001, ARG002
            return []

        def list_observation_monitor_snapshots(self, *, limit=100):  # noqa: ANN001, ARG002
            return [
                {
                    "observation_snapshot_pk": 7,
                    "observation_snapshot_id": "snapshot-7",
                    "day1_candidate_id": "day1-1",
                    "canonical_symbol": "002297.SZ",
                    "stock_name": "博云新材",
                    "trade_date": "2026-06-23",
                    "day_index": 2,
                    "as_of_time": "2026-06-23T02:15:00+00:00",
                    "captured_at": "2026-06-23T02:15:03+00:00",
                    "monitor_interval_minutes": 5,
                    "observation_status": "stopped",
                    "current_stage": "Day2 观察",
                    "current_conclusion": "卖盘主动砸向买盘，停止观察",
                    "key_reason": "Day2 接近涨停时卖盘主动砸向买盘",
                    "risk_tip": "接近涨停时卖盘主动砸向买盘，承接转弱，追高风险高",
                    "model_score": 15,
                    "model_score_label": "弱",
                    "score_state": "scored",
                    "model_score_version": "t_board_relay_observation_score_v1",
                    "relay_strength_label": "弱",
                    "monitoring_summary": "Day2 10:15 监测后结论已更新",
                    "data_gap_count": 0,
                    "data_gap_labels": [],
                    "created_at": "2026-06-23T02:15:03+00:00",
                }
            ]

    monkeypatch.setattr(api, "_repository", lambda: FakeRepository())

    item = TestClient(app).get("/t-board-relay/observation-board").json()["items"][0]

    assert item["updated_at"] == "2026-06-23T02:15:03+00:00"
    assert item["last_monitor_at"] == "2026-06-23T02:15:00+00:00"
    assert item["latest_monitor_snapshot_id"] == "snapshot-7"
    assert item["current_conclusion"] == "卖盘主动砸向买盘，停止观察"
    assert item["model_score"] == 15
