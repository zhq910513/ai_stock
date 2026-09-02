from __future__ import annotations

import os
import time

from source_data_service.models import FetchWorkerRunOnceRequest
from source_data_service.settings import settings
from source_data_service.worker_executor import run_worker_once


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _csv_env(name: str) -> list[str]:
    raw = os.environ.get(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def main() -> None:
    worker_id = os.environ.get("SOURCE_DATA_WORKER_ID", "source-data-worker-1")
    max_jobs = int(os.environ.get("SOURCE_DATA_WORKER_MAX_JOBS", "5"))
    lease_seconds = int(os.environ.get("SOURCE_DATA_WORKER_LEASE_SECONDS", "120"))
    dry_run_provider = _bool_env("SOURCE_DATA_WORKER_DRY_RUN_PROVIDER", True)
    complete_on_structured_error = _bool_env("SOURCE_DATA_WORKER_COMPLETE_ON_PROVIDER_ERROR", False)
    poll_seconds = float(os.environ.get("SOURCE_DATA_WORKER_POLL_SECONDS", str(settings.worker_poll_interval_seconds)))
    providers = _csv_env("SOURCE_DATA_WORKER_PROVIDERS")
    queue_names = _csv_env("SOURCE_DATA_WORKER_QUEUE_NAMES")
    print(
        f"starting source-data worker id={worker_id} max_jobs={max_jobs} "
        f"lease_seconds={lease_seconds} dry_run_provider={dry_run_provider} "
        f"providers={providers or ['*']} queue_names={queue_names or ['*']}",
        flush=True,
    )
    while True:
        result = run_worker_once(
            FetchWorkerRunOnceRequest(
                worker_id=worker_id,
                max_jobs=max_jobs,
                providers=providers,
                queue_names=queue_names,
                lease_seconds=lease_seconds,
                dry_run_provider=dry_run_provider,
                complete_on_structured_provider_error=complete_on_structured_error,
            )
        )
        if result.leased_count or result.failed_count or result.succeeded_count:
            print(result.model_dump_json(), flush=True)
        time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
