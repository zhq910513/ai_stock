from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from research_service.repository import jsonable
from research_service.task_registry import TaskRequirement


@dataclass(frozen=True)
class OwnerCallResult:
    owner_service: str
    endpoint: str
    url: str
    request_body: dict[str, Any]
    status_code: int
    response_body: dict[str, Any]

    @property
    def accepted(self) -> bool:
        return 200 <= self.status_code < 300


class ModelOwnerClient:
    def __init__(
        self,
        *,
        hot_candidates_base_url: str,
        candidate_memory_base_url: str,
        ambush_watchlist_base_url: str,
        t_board_relay_base_url: str,
        request_timeout_seconds: float,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_urls = {
            "hot-candidates-service": hot_candidates_base_url.rstrip("/"),
            "candidate-memory-service": candidate_memory_base_url.rstrip("/"),
            "ambush-watchlist-service": ambush_watchlist_base_url.rstrip("/"),
            "t-board-relay-service": t_board_relay_base_url.rstrip("/"),
        }
        self.timeout = request_timeout_seconds
        self.client = client or httpx.Client()

    def call_owner(self, task: TaskRequirement, *, payload: dict[str, Any], run_id: str, as_of_time_utc: str | None) -> OwnerCallResult:
        if task.owner_service == "candidate-memory-service" and task.task_code == "memory.seed.from_hot_signals":
            return self._call_memory_seed_and_entity(task, payload=payload, run_id=run_id, as_of_time_utc=as_of_time_utc)
        body = self._request_body(task, payload=payload, run_id=run_id, as_of_time_utc=as_of_time_utc)
        return self._post(task.owner_service, task.endpoint, body)

    def _call_memory_seed_and_entity(
        self,
        task: TaskRequirement,
        *,
        payload: dict[str, Any],
        run_id: str,
        as_of_time_utc: str | None,
    ) -> OwnerCallResult:
        seed_body = self._request_body(task, payload=payload, run_id=run_id, as_of_time_utc=as_of_time_utc)
        seed_result = self._post(task.owner_service, task.endpoint, seed_body)
        if not seed_result.accepted:
            return seed_result
        seed = _structured(seed_result.response_body).get("memory_seed") or {}
        entity_task = TaskRequirement(
            task_code="memory.entity.from_seed",
            task_kind=task.task_kind,
            owner_service=task.owner_service,
            schedule_hint=task.schedule_hint,
            frequency_hint=task.frequency_hint,
            model_code=task.model_code,
            model_phase="memory_entity_build",
            endpoint="/production/entity/build",
            source_tables=task.source_tables,
            upstream_tables=task.upstream_tables,
            official_publish=False,
            append_only=True,
            source_preflight_required=False,
            notes="Research execution chained entity build after seed build.",
        )
        row = dict(seed_body.get("row") or {})
        row["seed"] = seed
        entity_body = {"row": row, "run_id": run_id, "as_of_time_utc": as_of_time_utc}
        entity_result = self._post(task.owner_service, entity_task.endpoint, entity_body)
        combined_status = entity_result.status_code if not entity_result.accepted else seed_result.status_code
        combined = {
            "model_name": "candidate_memory",
            "model_version": entity_result.response_body.get("model_version") or seed_result.response_body.get("model_version"),
            "structured_output": {
                "memory_seed": seed,
                "memory_entity": _structured(entity_result.response_body).get("memory_entity") or {},
            },
            "jarvis_payload": {},
            "contract_gaps": sorted(
                set(list(seed_result.response_body.get("contract_gaps") or []) + list(entity_result.response_body.get("contract_gaps") or []))
            ),
            "owner_call_sequence": [
                {"endpoint": seed_result.endpoint, "status_code": seed_result.status_code},
                {"endpoint": entity_result.endpoint, "status_code": entity_result.status_code},
            ],
        }
        return OwnerCallResult(
            owner_service=task.owner_service,
            endpoint=f"{task.endpoint} -> {entity_task.endpoint}",
            url=f"{seed_result.url} -> {entity_result.url}",
            request_body={"seed": seed_body, "entity": entity_body},
            status_code=combined_status,
            response_body=jsonable(combined),
        )

    def _request_body(self, task: TaskRequirement, *, payload: dict[str, Any], run_id: str, as_of_time_utc: str | None) -> dict[str, Any]:
        if task.owner_service == "hot-candidates-service":
            return {"payload": payload, "run_id": run_id, "as_of_time_utc": as_of_time_utc}
        if task.owner_service == "candidate-memory-service":
            return {"row": self._memory_row(task, payload), "run_id": run_id, "as_of_time_utc": as_of_time_utc}
        if task.owner_service == "ambush-watchlist-service":
            return self._ambush_body(task, payload, as_of_time_utc)
        if task.owner_service == "t-board-relay-service":
            body = {
                "payload": payload.get("payload") or payload,
                "trade_date": payload.get("trade_date"),
                "as_of_time_utc": as_of_time_utc,
                "run_id": run_id,
                "mode": "production",
            }
            if task.task_code == "t_relay.day1.scan.close":
                body["row"] = (payload.get("rows") or [{}])[0] if isinstance(payload.get("rows"), list) else payload.get("row") or {}
                body["rows"] = payload.get("rows") or []
            return body
        return payload

    def _memory_row(self, task: TaskRequirement, payload: dict[str, Any]) -> dict[str, Any]:
        row = dict(payload)
        upstream = payload.get("upstream_model_facts") if isinstance(payload.get("upstream_model_facts"), dict) else {}
        if task.task_code == "memory.seed.from_hot_signals":
            hot_signal = _first_upstream(upstream, "decision_hot.hot_signal_fact_v1")
            row.update(hot_signal)
            row.setdefault("first_source_model", "hot_candidates")
            row.setdefault("first_source_signal_id", hot_signal.get("hot_signal_id"))
            row.setdefault("first_source_case_id", hot_signal.get("hot_case_id"))
            row.setdefault("first_selected_date", hot_signal.get("signal_date"))
        elif task.task_code in {"memory.pre_signal.scan", "memory.release_gate.close"}:
            entity = _first_upstream(upstream, "decision_memory.memory_entity_v1")
            pre_signal = _first_upstream(upstream, "decision_memory.memory_pre_signal_case_v1")
            score = _first_upstream(upstream, "decision_memory.memory_score_fact_v1")
            row.update(entity)
            if pre_signal:
                row["pre_signal_case"] = pre_signal
                row.update({key: value for key, value in pre_signal.items() if key not in row or row[key] is None})
            if score:
                row.update({key: value for key, value in score.items() if key not in row or row[key] is None})
        return row

    def _ambush_body(self, task: TaskRequirement, payload: dict[str, Any], as_of_time_utc: str | None) -> dict[str, Any]:
        body = {
            "instrument": payload.get("instrument") or {},
            "bars": payload.get("bars") or [],
            "weekly_bars": payload.get("weekly_bars") or [],
            "as_of_trading_day": payload.get("as_of_trading_day") or payload.get("trade_date"),
            "as_of_time": as_of_time_utc,
            "window_days": payload.get("window_days") or 60,
            "moneyflow_context": payload.get("moneyflow_context"),
            "sector_context": payload.get("sector_context"),
            "market_context": payload.get("market_context"),
            "tradability_context": payload.get("tradability_context"),
        }
        upstream = payload.get("upstream_model_facts") if isinstance(payload.get("upstream_model_facts"), dict) else {}
        if task.task_code in {"ambush.phase3.release_gate.close", "ambush.buy_point.reference"}:
            valley = _first_upstream(upstream, "decision_ambush.valley_watch_pool_v1")
            anchor = _first_upstream(upstream, "decision_ambush.effective_turn_anchor_v1")
            pool = _first_upstream(upstream, "decision_ambush.effective_turn_pool_v1")
            body["valley_watch"] = valley or pool
            body["effective_turn_anchor"] = anchor or pool
        return {key: value for key, value in body.items() if value is not None}

    def _post(self, owner_service: str, endpoint: str, body: dict[str, Any]) -> OwnerCallResult:
        url = f"{self.base_urls[owner_service]}{endpoint}"
        response = self.client.post(url, json=jsonable(body), timeout=self.timeout)
        try:
            response_body = response.json()
        except Exception:  # noqa: BLE001
            response_body = {"error": getattr(response, "text", "")}
        return OwnerCallResult(
            owner_service=owner_service,
            endpoint=endpoint,
            url=url,
            request_body=jsonable(body),
            status_code=int(response.status_code),
            response_body=jsonable(response_body),
        )


def _structured(body: dict[str, Any]) -> dict[str, Any]:
    value = body.get("structured_output") if isinstance(body, dict) else {}
    return value if isinstance(value, dict) else {}


def _first_upstream(upstream: dict[str, Any], table_name: str) -> dict[str, Any]:
    table = upstream.get(table_name)
    if not isinstance(table, dict):
        return {}
    for rows in table.values():
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            return rows[0]
    return {}
