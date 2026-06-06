"""Async circuit breaker for upstream provider protection."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("codex-proxy")


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    """Simple circuit breaker for upstream requests.

    - CLOSED: requests flow normally
    - OPEN: requests are rejected immediately (fail fast)
    - HALF_OPEN: one request is allowed through to test recovery
    """

    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    half_open_max: int = 1

    state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    failure_count: int = field(default=0, init=False)
    last_failure_time: float = field(default=0.0, init=False)
    half_open_count: int = field(default=0, init=False)

    def can_execute(self) -> bool:
        """Check if a request can proceed."""
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time >= self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                self.half_open_count = 1
                logger.info("Circuit breaker: OPEN -> HALF_OPEN")
                return True
            return False
        # HALF_OPEN
        if self.half_open_count < self.half_open_max:
            self.half_open_count += 1
            return True
        return False

    def record_success(self) -> None:
        """Record a successful request."""
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            logger.info("Circuit breaker: HALF_OPEN -> CLOSED")
        elif self.state == CircuitState.CLOSED:
            self.failure_count = 0

    def record_failure(self) -> None:
        """Record a failed request."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
            logger.warning("Circuit breaker: HALF_OPEN -> OPEN")
        elif self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning(
                "Circuit breaker: CLOSED -> OPEN (failures=%d)", self.failure_count,
            )

    def get_status(self) -> dict:
        """Return circuit breaker status for monitoring."""
        return {
            "state": self.state.value,
            "failure_count": self.failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
            "last_failure_time": self.last_failure_time,
        }
