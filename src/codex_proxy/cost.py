"""Cost calculation module for codex-proxy v5.

Calculates request costs using model pricing from the database.
Falls back to $0 when no pricing data is available.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("codex-proxy.cost")

# ── Known model pricing (fallback when DB has no data) ──────────────────
# Prices per million tokens (input, output) — approximate as of 2026

KNOWN_PRICING: dict[str, tuple[float, float]] = {
    # Z.AI / GLM
    "glm-5.1": (0.5, 1.5),
    "glm-5": (0.5, 1.5),
    "glm-4.7": (0.35, 1.0),
    "glm-4.6": (0.25, 0.75),
    "glm-4.5-air": (0.1, 0.3),
    # OpenAI
    "gpt-4.1": (2.0, 8.0),
    "gpt-4.1-mini": (0.4, 1.6),
    "gpt-4.1-nano": (0.1, 0.4),
    "o3": (10.0, 40.0),
    "o4-mini": (1.5, 6.0),
    # Anthropic
    "claude-sonnet-4-20250514": (3.0, 15.0),
    "claude-opus-4-20250514": (15.0, 75.0),
    "claude-haiku-4-5-20251001": (0.8, 4.0),
    # Google
    "gemini-2.5-flash": (0.15, 0.6),
    "gemini-2.5-pro": (1.25, 10.0),
    # DeepSeek
    "deepseek-chat": (0.27, 1.1),
    "deepseek-reasoner": (0.55, 2.19),
    # Groq
    "llama-4-maverick-17b": (0.2, 0.6),
    "mixtral-8x7b-32768": (0.24, 0.24),
    # Mistral
    "mistral-large-latest": (2.0, 6.0),
    "codestral-latest": (0.3, 0.9),
    # Together
    "meta-llama/Llama-3.3-70B-Instruct-Turbo": (0.88, 0.88),
    # OpenRouter (varies, use rough avg)
    "deepseek/deepseek-chat-v3-0324": (0.27, 1.1),
    # Cohere
    "command-a-03-2025": (2.5, 10.0),
    # NVIDIA
    "nvidia/llama-3.1-nemotron-ultra-253b-v1": (0.8, 0.8),
    # Ollama (local — free)
    "qwen3:32b": (0.0, 0.0),
    "codellama:34b": (0.0, 0.0),
}


async def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    db_session_factory: Any = None,
) -> float:
    """Calculate the cost of a request in USD.

    Tries DB pricing first, falls back to KNOWN_PRICING, then $0.
    """
    # Try DB lookup
    if db_session_factory:
        try:
            from .db import crud_providers
            async with db_session_factory() as session:
                pricing = await crud_providers.get_model_pricing(session, model)
                if pricing and (pricing["input_price_per_million"] > 0 or
                                pricing["output_price_per_million"] > 0):
                    return _compute(
                        input_tokens, output_tokens,
                        pricing["input_price_per_million"],
                        pricing["output_price_per_million"],
                    )
        except Exception as e:
            logger.debug("DB pricing lookup failed for %s: %s", model, e)

    # Fallback to known pricing
    if model in KNOWN_PRICING:
        inp_price, out_price = KNOWN_PRICING[model]
        return _compute(input_tokens, output_tokens, inp_price, out_price)

    # No pricing data
    return 0.0


def calculate_cost_sync(model: str, input_tokens: int, output_tokens: int) -> float:
    """Synchronous cost calculation using only KNOWN_PRICING (no DB)."""
    if model in KNOWN_PRICING:
        inp_price, out_price = KNOWN_PRICING[model]
        return _compute(input_tokens, output_tokens, inp_price, out_price)
    return 0.0


def _compute(input_tokens: int, output_tokens: int,
             input_price_per_m: float, output_price_per_m: float) -> float:
    """Compute cost from token counts and per-million prices."""
    return (input_tokens * input_price_per_m / 1_000_000) + \
           (output_tokens * output_price_per_m / 1_000_000)


async def seed_pricing_to_db(db_session_factory, default_provider_id: str | None = None) -> int:
    """Seed KNOWN_PRICING into the DB models table.

    Only inserts models that don't already exist (idempotent).
    Returns count of models inserted.
    """
    from .db import crud_providers, crud_logs
    from sqlalchemy import func, select
    from .db.models import models as models_table

    inserted = 0
    async with db_session_factory() as session:
        # Get or create a default provider for pricing data
        if not default_provider_id:
            providers = await crud_providers.list_providers(session)
            if providers:
                default_provider_id = providers[0]["id"]
            else:
                # Create a generic pricing provider
                p = await crud_providers.create_provider(
                    session, name="_pricing", display_name="Pricing Reference",
                    base_url="", adapter_name="default")
                default_provider_id = p["id"]

        for model_id, (inp_price, out_price) in KNOWN_PRICING.items():
            existing = await crud_providers.get_model(session, default_provider_id, model_id)
            if not existing:
                await crud_providers.create_model(
                    session, provider_id=default_provider_id, model_id=model_id,
                    input_price_per_million=inp_price,
                    output_price_per_million=out_price,
                )
                inserted += 1

    if inserted:
        logger.info("Seeded %d model prices to DB", inserted)
    return inserted
