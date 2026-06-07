"""Aggregation queries for analytics — cost, usage, latency."""

from __future__ import annotations

from sqlalchemy import func, select

from .models import request_logs


async def aggregate_usage(session, *, user_id: str | None = None,
                          since: str | None = None,
                          until: str | None = None,
                          group_by: str = "model") -> list[dict]:
    """Aggregate token usage grouped by a field.

    Args:
        group_by: One of 'model', 'provider_id', 'user_id', 'method'.
    """
    valid_groups = {"model", "provider_id", "user_id", "method"}
    if group_by not in valid_groups:
        group_by = "model"

    group_col = getattr(request_logs.c, group_by)
    stmt = select(
        group_col.label("group_key"),
        func.count().label("request_count"),
        func.sum(request_logs.c.input_tokens).label("total_input_tokens"),
        func.sum(request_logs.c.output_tokens).label("total_output_tokens"),
        func.sum(request_logs.c.total_tokens).label("total_tokens"),
    ).group_by(group_col)

    if user_id:
        stmt = stmt.where(request_logs.c.user_id == user_id)
    if since:
        stmt = stmt.where(request_logs.c.created_at >= since)
    if until:
        stmt = stmt.where(request_logs.c.created_at < until)

    result = await session.execute(stmt)
    return [dict(row) for row in result.mappings().all()]


async def aggregate_costs(session, *, user_id: str | None = None,
                          since: str | None = None,
                          until: str | None = None,
                          group_by: str = "model") -> list[dict]:
    """Aggregate costs grouped by a field."""
    valid_groups = {"model", "provider_id", "user_id"}
    if group_by not in valid_groups:
        group_by = "model"

    group_col = getattr(request_logs.c, group_by)
    stmt = select(
        group_col.label("group_key"),
        func.sum(request_logs.c.cost_usd).label("total_cost"),
        func.count().label("request_count"),
        func.avg(request_logs.c.cost_usd).label("avg_cost"),
    ).group_by(group_col)

    if user_id:
        stmt = stmt.where(request_logs.c.user_id == user_id)
    if since:
        stmt = stmt.where(request_logs.c.created_at >= since)
    if until:
        stmt = stmt.where(request_logs.c.created_at < until)

    result = await session.execute(stmt)
    return [dict(row) for row in result.mappings().all()]


async def aggregate_latency(session, *, user_id: str | None = None,
                            since: str | None = None,
                            group_by: str = "model") -> list[dict]:
    """Aggregate latency statistics grouped by a field."""
    valid_groups = {"model", "provider_id"}
    if group_by not in valid_groups:
        group_by = "model"

    group_col = getattr(request_logs.c, group_by)
    stmt = select(
        group_col.label("group_key"),
        func.avg(request_logs.c.latency_ms).label("avg_latency_ms"),
        func.min(request_logs.c.latency_ms).label("min_latency_ms"),
        func.max(request_logs.c.latency_ms).label("max_latency_ms"),
        func.count().label("request_count"),
    ).group_by(group_col)

    if user_id:
        stmt = stmt.where(request_logs.c.user_id == user_id)
    if since:
        stmt = stmt.where(request_logs.c.created_at >= since)

    result = await session.execute(stmt)
    return [dict(row) for row in result.mappings().all()]


async def daily_cost_series(session, *, user_id: str | None = None,
                            days: int = 30) -> list[dict]:
    """Get daily cost totals for the last N days."""
    stmt = select(
        func.substr(request_logs.c.created_at, 1, 10).label("date"),
        func.sum(request_logs.c.cost_usd).label("total_cost"),
        func.count().label("request_count"),
        func.sum(request_logs.c.total_tokens).label("total_tokens"),
    ).group_by(func.substr(request_logs.c.created_at, 1, 10))

    if user_id:
        stmt = stmt.where(request_logs.c.user_id == user_id)

    # Simple day filter using string comparison
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()[:10]
    stmt = stmt.where(request_logs.c.created_at >= cutoff)
    stmt = stmt.order_by("date")

    result = await session.execute(stmt)
    return [dict(row) for row in result.mappings().all()]


async def user_total_spend(session, user_id: str, *, since: str | None = None) -> float:
    """Get total spend for a user."""
    stmt = select(func.coalesce(func.sum(request_logs.c.cost_usd), 0.0))
    if since:
        stmt = stmt.where(request_logs.c.created_at >= since)
    stmt = stmt.where(request_logs.c.user_id == user_id)
    result = await session.execute(stmt)
    return float(result.scalar() or 0.0)
