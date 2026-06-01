"""Tests for circuit breaker."""

import time

from codex_proxy.circuit_breaker import CircuitBreaker, CircuitState


class TestInitialState:
    def test_starts_closed(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED

    def test_can_execute_when_closed(self):
        cb = CircuitBreaker()
        assert cb.can_execute() is True

    def test_zero_failures_initially(self):
        cb = CircuitBreaker()
        assert cb.failure_count == 0


class TestOpenOnThreshold:
    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_rejects_when_open(self):
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.can_execute() is False

    def test_does_not_open_before_threshold(self):
        cb = CircuitBreaker(failure_threshold=5)
        for _ in range(4):
            cb.record_failure()
        assert cb.state == CircuitState.CLOSED


class TestHalfOpenAfterTimeout:
    def test_transitions_to_half_open(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.0)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.01)
        assert cb.can_execute() is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_allows_limited_requests(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.0, half_open_max=1)
        cb.record_failure()
        time.sleep(0.01)
        assert cb.can_execute() is True
        assert cb.can_execute() is False


class TestRecovery:
    def test_success_closes_from_half_open(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.0)
        cb.record_failure()
        time.sleep(0.01)
        cb.can_execute()
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.failure_count == 0

    def test_failure_reopens_from_half_open(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.0)
        cb.record_failure()
        time.sleep(0.01)
        cb.can_execute()
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN


class TestGetStatus:
    def test_status_dict(self):
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0)
        status = cb.get_status()
        assert status["state"] == "closed"
        assert status["failure_count"] == 0
        assert status["failure_threshold"] == 5
        assert status["recovery_timeout"] == 30.0

    def test_status_after_failure(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        status = cb.get_status()
        assert status["failure_count"] == 1
        assert status["state"] == "closed"
