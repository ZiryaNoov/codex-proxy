"""Smart routing engine for codex-proxy v5.

Strategies:
- fallback: try providers in config order
- cost: route to cheapest provider for the model
- latency: route to provider with lowest recent latency
- weighted: distribute requests across providers by weight
"""

from __future__ import annotations

import logging
import random
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("codex-proxy.router")

# ── Latency tracker ─────────────────────────────────────────────────────

@dataclass
class ProviderLatency:
    """Tracks rolling average latency for a provider."""
    samples: deque = field(default_factory=lambda: deque(maxlen=100))
    last_error: float = 0.0  # monotonic timestamp of last error

    def record(self, latency_ms: float, success: bool) -> None:
        self.samples.append((time.monotonic(), latency_ms, success))
        if not success:
            self.last_error = time.monotonic()

    def average_ms(self) -> float:
        if not self.samples:
            return float("inf")
        successful = [s for s in self.samples if s[2]]
        if not successful:
            return float("inf")
        return sum(s[1] for s in successful) / len(successful)

    def error_rate(self) -> float:
        if not self.samples:
            return 0.0
        errors = sum(1 for s in self.samples if not s[2])
        return errors / len(self.samples)

    def is_healthy(self, max_error_rate: float = 0.5) -> bool:
        """Consider unhealthy if >50% errors in recent samples."""
        return self.error_rate() < max_error_rate


# ── Smart Router ────────────────────────────────────────────────────────

class SmartRouter:
    """Routes requests to the best provider based on strategy."""

    def __init__(self, strategy: str = "fallback", providers_map: dict | None = None):
        self.strategy = strategy
        self._latency: dict[str, ProviderLatency] = {}
        self._weights: dict[str, float] = {}
        self._fallback_order: list[str] = []

        if providers_map:
            for name in providers_map:
                self._latency[name] = ProviderLatency()
                self._weights[name] = 1.0
                self._fallback_order.append(name)

    def record_latency(self, provider_name: str, latency_ms: float,
                       success: bool = True) -> None:
        """Record a request outcome for latency tracking."""
        if provider_name not in self._latency:
            self._latency[provider_name] = ProviderLatency()
        self._latency[provider_name].record(latency_ms, success)

    def set_weights(self, weights: dict[str, float]) -> None:
        """Set routing weights (for weighted strategy)."""
        total = sum(weights.values()) or 1.0
        self._weights = {k: v / total for k, v in weights.items()}

    def select_provider(self, model: str, providers_map: dict,
                        db_session_factory: Any = None) -> tuple[str, str]:
        """Select the best provider for a given model.

        Returns (provider_name, resolved_model).
        Falls back to first available provider on error.
        """
        # Filter providers that support this model
        candidates: dict[str, list[str]] = {}  # provider_name -> list of model names
        for name, ps in providers_map.items():
            if model in ps.config.models:
                candidates[name] = ps.config.models

        # If only one candidate, use it directly
        if len(candidates) == 1:
            return next(iter(candidates)), model

        # No exact match — try any provider
        if not candidates:
            # If only one provider total, use it
            if len(providers_map) == 1:
                return next(iter(providers_map)), model
            # Try first provider as fallback
            return self._fallback_order[0] if self._fallback_order else next(iter(providers_map)), model

        try:
            if self.strategy == "cost":
                return self._route_cost(model, candidates, db_session_factory)
            elif self.strategy == "latency":
                return self._route_latency(candidates)
            elif self.strategy == "weighted":
                return self._route_weighted(candidates)
            else:  # fallback
                return self._route_fallback(candidates)
        except Exception as e:
            logger.warning("Router error, falling back: %s", e)
            return next(iter(candidates)), model

    def _route_fallback(self, candidates: dict) -> tuple[str, str]:
        """Try providers in config order, skip unhealthy ones."""
        for name in self._fallback_order:
            if name in candidates:
                latency = self._latency.get(name)
                if latency and not latency.is_healthy():
                    continue
                return name, ""  # model resolved by caller
        # All unhealthy — use first anyway
        return next(iter(candidates)), ""

    def _route_cost(self, model: str, candidates: dict,
                    db_session_factory: Any) -> tuple[str, str]:
        """Route to the cheapest provider for this model."""
        best_name = None
        best_price = float("inf")

        for name in candidates:
            # Try DB pricing
            price = self._get_model_price(name, model, db_session_factory)
            if price < best_price:
                best_price = price
                best_name = name

        return best_name or next(iter(candidates)), ""

    def _route_latency(self, candidates: dict) -> tuple[str, str]:
        """Route to the provider with lowest recent latency."""
        best_name = None
        best_latency = float("inf")

        for name in candidates:
            latency = self._latency.get(name)
            if not latency:
                # No data yet — prefer this one to collect samples
                return name, ""
            avg = latency.average_ms()
            if avg < best_latency and latency.is_healthy():
                best_latency = avg
                best_name = name

        return best_name or next(iter(candidates)), ""

    def _route_weighted(self, candidates: dict) -> tuple[str, str]:
        """Route randomly based on weights."""
        names = [n for n in candidates if n in self._weights]
        if not names:
            return next(iter(candidates)), ""

        weights = [self._weights.get(n, 0.1) for n in names]
        total = sum(weights) or 1.0
        weights = [w / total for w in weights]

        chosen = random.choices(names, weights=weights, k=1)[0]
        return chosen, ""

    def _get_model_price(self, provider_name: str, model: str,
                         db_session_factory: Any) -> float:
        """Get output price per million tokens for a model (proxy for cost)."""
        # Sync fallback — use cost module's known pricing
        from .cost import KNOWN_PRICING
        if model in KNOWN_PRICING:
            return KNOWN_PRICING[model][1]  # output price as proxy
        return float("inf")

    def get_status(self) -> dict:
        """Return routing status for /status endpoint."""
        latency_info = {}
        for name, lat in self._latency.items():
            latency_info[name] = {
                "avg_latency_ms": round(lat.average_ms(), 1) if lat.average_ms() != float("inf") else None,
                "error_rate": round(lat.error_rate(), 3),
                "healthy": lat.is_healthy(),
                "samples": len(lat.samples),
            }
        return {
            "strategy": self.strategy,
            "providers": latency_info,
            "weights": self._weights,
        }
