"""Simple in-memory rate limiter for per-client request throttling."""

from __future__ import annotations

import time
from collections import defaultdict


class RateLimiter:
    """Sliding-window rate limiter keyed by client identifier.

    Tracks request timestamps per client and rejects requests that
    exceed the configured limit within the rolling window.
    """

    def __init__(self, max_requests: int = 60, window_seconds: int = 60) -> None:
        self.max_requests = max_requests
        self.window = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    def allow(self, client_id: str) -> bool:
        """Check whether *client_id* is allowed to make a request right now."""
        now = time.time()
        reqs = self._requests[client_id]
        # Prune timestamps outside the window
        reqs[:] = [t for t in reqs if now - t < self.window]
        if len(reqs) >= self.max_requests:
            return False
        reqs.append(now)
        return True

    def reset(self, client_id: str | None = None) -> None:
        """Clear rate-limit state for a specific client or all clients."""
        if client_id is None:
            self._requests.clear()
        else:
            self._requests.pop(client_id, None)

    def get_status(self) -> dict:
        """Return a summary of rate-limiter state for monitoring."""
        return {
            "max_requests": self.max_requests,
            "window_seconds": self.window,
            "active_clients": len(self._requests),
        }
