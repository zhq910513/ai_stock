from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

T = TypeVar("T")


class CircuitOpenError(RuntimeError):
    pass


@dataclass
class CircuitBreaker:
    failure_threshold: int = 5
    recovery_seconds: int = 60
    failure_count: int = 0
    opened_at: float | None = None

    def before_call(self) -> None:
        if self.opened_at is None:
            return
        if time.monotonic() - self.opened_at >= self.recovery_seconds:
            self.failure_count = 0
            self.opened_at = None
            return
        raise CircuitOpenError("provider circuit is open; use backup provider or retry later")

    def record_success(self) -> None:
        self.failure_count = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self.opened_at = time.monotonic()


@dataclass
class RetryPolicy:
    max_retries: int = 2
    base_delay_seconds: float = 0.1
    retry_exceptions: tuple[type[BaseException], ...] = (RuntimeError, TimeoutError, ConnectionError)

    def run(self, func: Callable[[], T]) -> T:
        attempt = 0
        while True:
            try:
                return func()
            except self.retry_exceptions:
                if attempt >= self.max_retries:
                    raise
                time.sleep(self.base_delay_seconds * (2**attempt))
                attempt += 1


@dataclass
class ProviderResilienceState:
    circuits: dict[str, CircuitBreaker] = field(default_factory=dict)

    def get_circuit(self, key: str, *, failure_threshold: int, recovery_seconds: int) -> CircuitBreaker:
        if key not in self.circuits:
            self.circuits[key] = CircuitBreaker(
                failure_threshold=failure_threshold,
                recovery_seconds=recovery_seconds,
            )
        return self.circuits[key]


state = ProviderResilienceState()
