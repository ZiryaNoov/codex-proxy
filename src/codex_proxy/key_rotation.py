"""Multi-key rotation with per-key circuit breakers."""

from __future__ import annotations

import time
from dataclasses import dataclass

from .circuit_breaker import CircuitBreaker

_FAIL_CODES = frozenset({401, 403, 429})


def _mask_key(key: str) -> str:
    """Mask a key for display: show first 3 and last 4 chars."""
    if len(key) <= 7:
        return "***"
    return f"{key[:3]}...{key[-4:]}"


@dataclass
class _KeyEntry:
    key: str
    circuit_breaker: CircuitBreaker
    error_count: int = 0
    success_count: int = 0
    last_used: float = 0.0
    last_error_status: int = 0


class KeyRotator:
    """Round-robin key pool with per-key circuit breakers."""

    def __init__(self, keys: list[str], failure_threshold: int = 3,
                 recovery_timeout: float = 60.0) -> None:
        if not keys:
            raise ValueError("KeyRotator requires at least one key")
        self._keys = keys
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._index = 0
        self._entries: list[_KeyEntry] = []
        self._rebuild_entries(keys)

    def _rebuild_entries(self, keys: list[str]) -> None:
        self._entries = [
            _KeyEntry(
                key=k,
                circuit_breaker=CircuitBreaker(
                    failure_threshold=self._failure_threshold,
                    recovery_timeout=self._recovery_timeout,
                ),
            )
            for k in keys
        ]

    def next_key(self) -> str:
        """Return the best available key (round-robin with skip-bad)."""
        n = len(self._entries)
        for _ in range(n):
            entry = self._entries[self._index % n]
            self._index = (self._index + 1) % n
            if entry.circuit_breaker.can_execute():
                entry.last_used = time.time()
                return entry.key
        # All keys have open circuits — fail-open
        entry = self._entries[0]
        entry.last_used = time.time()
        return entry.key

    def record_success(self, key: str) -> None:
        entry = self._find(key)
        if entry:
            entry.circuit_breaker.record_success()
            entry.success_count += 1

    def record_failure(self, key: str, status_code: int) -> None:
        entry = self._find(key)
        if not entry:
            return
        entry.error_count += 1
        entry.last_error_status = status_code
        if status_code in _FAIL_CODES:
            entry.circuit_breaker.record_failure()

    def _find(self, key: str) -> _KeyEntry | None:
        for e in self._entries:
            if e.key == key:
                return e
        return None

    def get_status(self) -> list[dict]:
        """Return status dicts for each key."""
        return [
            {
                "key": _mask_key(e.key),
                "state": e.circuit_breaker.get_status().get("state", "UNKNOWN"),
                "errors": e.error_count,
                "successes": e.success_count,
                "last_error": e.last_error_status,
            }
            for e in self._entries
        ]

    def reset(self, keys: list[str]) -> None:
        """Rebuild the pool with new keys."""
        self._keys = keys
        self._index = 0
        self._rebuild_entries(keys)
