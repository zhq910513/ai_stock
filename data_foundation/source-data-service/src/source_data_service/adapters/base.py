from __future__ import annotations

from abc import ABC, abstractmethod
import hashlib
import json
import math
from typing import Any

from source_data_service.models import Provider, RawFetchResult, RawRow
from source_data_service.provider_registry import get_api_spec


def stable_json_hash(payload: Any) -> str:
    """Return a deterministic sha256 hash for request/response audit fields."""

    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "item"):
        try:
            return _jsonable(value.item())
        except Exception:
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


class ProviderAdapter(ABC):
    provider: Provider

    @abstractmethod
    def fetch(self, api_name: str, params: dict[str, Any], *, dry_run: bool = False) -> RawFetchResult:
        raise NotImplementedError

    def build_result(
        self,
        api_name: str,
        params: dict[str, Any],
        rows: list[dict[str, Any]],
        *,
        dry_run: bool = False,
        warning: str | None = None,
    ) -> RawFetchResult:
        spec = get_api_spec(self.provider, api_name)
        request_hash = stable_json_hash({"provider": self.provider.value, "api_name": api_name, "params": params})
        schema_fields = sorted({key for row in rows for key in row.keys()})
        response_schema_hash = stable_json_hash(schema_fields) if schema_fields else None
        raw_rows = [
            RawRow(
                provider=self.provider,
                api_name=api_name,
                raw_table_name=spec.raw_table_name,
                request_params=params,
                row=row,
                request_hash=request_hash,
                response_schema_hash=response_schema_hash,
                response_row_hash=stable_json_hash(row),
            )
            for row in rows
        ]
        return RawFetchResult(
            provider=self.provider,
            api_name=api_name,
            raw_table_name=spec.raw_table_name,
            request_params=params,
            dry_run=dry_run,
            row_count=len(raw_rows),
            rows=raw_rows,
            request_hash=request_hash,
            response_schema_hash=response_schema_hash,
            warning=warning,
        )


def dataframe_to_rows(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    if hasattr(frame, "to_dict"):
        return [_jsonable(dict(row)) for row in frame.to_dict(orient="records")]
    if isinstance(frame, list):
        return [_jsonable(dict(row) if isinstance(row, dict) else {"value": row}) for row in frame]
    raise TypeError(f"unsupported provider dataframe/result type: {type(frame)!r}")
