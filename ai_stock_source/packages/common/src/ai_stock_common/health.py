from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def health_payload(*, service: str, version: str, status: str = "ok", extra: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": status,
        "service": service,
        "version": version,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        payload.update(extra)
    return payload
