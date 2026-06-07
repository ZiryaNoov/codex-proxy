"""CRUD operations for the request_logs table."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select

from .models import request_logs


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def insert_log(session, *, user_id: str | None = None,
                     api_key_id: str | None = None,
                     provider_id: str | None = None,
                     request_id: str = "",
                     model: str = "",
                     method: str = "http",
                     input_tokens: int = 0,
                     output_tokens: int = 0,
                     total_tokens: int = 0,
                     cost_usd: float = 0.0,
                     latency_ms: float = 0.0,
                     status_code: int | None = None,
                     error_message: str | None = None,
                     is_stream: bool = False) -> None:
    """Insert a request log entry. Non-blocking — no commit (caller commits)."""
    await session.execute(
        request_logs.insert().values(
            user_id=user_id, api_key_id=api_key_id,
            provider_id=provider_id, request_id=request_id,
            model=model, method=method,
            input_tokens=input_tokens, output_tokens=output_tokens,
            total_tokens=total_tokens, cost_usd=cost_usd,
            latency_ms=latency_ms, status_code=status_code,
            error_message=error_message, is_stream=is_stream,
            created_at=_now(),
        )
    )


async def get_recent_logs(session, *, limit: int = 50, offset: int = 0) -> list[dict]:
    """Get recent request logs, newest first."""
    result = await session.execute(
        select(request_logs)
        .order_by(request_logs.c.id.desc())
        .limit(limit).offset(offset)
    )
    return [dict(row) for row in result.mappings().all()]


async def get_user_logs(session, user_id: str, *, limit: int = 50,
                        offset: int = 0) -> list[dict]:
    result = await session.execute(
        select(request_logs).where(request_logs.c.user_id == user_id)
        .order_by(request_logs.c.id.desc())
        .limit(limit).offset(offset)
    )
    return [dict(row) for row in result.mappings().all()]


async def count_logs(session, *, since: str | None = None) -> int:
    stmt = select(func.count()).select_from(request_logs)
    if since:
        stmt = stmt.where(request_logs.c.created_at >= since)
    result = await session.execute(stmt)
    return result.scalar() or 0


async def get_error_count(session, *, since: str | None = None) -> int:
    stmt = select(func.count()).select_from(request_logs).where(
        request_logs.c.status_code >= 400  # type: ignore[operator]
    )
    if since:
        stmt = stmt.where(request_logs.c.created_at >= since)
    result = await session.execute(stmt)
    return result.scalar() or 0
