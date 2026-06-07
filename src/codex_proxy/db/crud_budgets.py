"""CRUD operations for budgets and cost_alerts tables."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update

from .models import budgets, cost_alerts


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


async def create_budget(session, *, user_id: str,
                        daily_limit: float | None = None,
                        monthly_limit: float | None = None,
                        alert_threshold: float = 0.8,
                        webhook_url: str | None = None) -> dict:
    bid = _new_id()
    now = _now()
    await session.execute(
        budgets.insert().values(
            id=bid, user_id=user_id,
            daily_limit=daily_limit, monthly_limit=monthly_limit,
            alert_threshold=alert_threshold, webhook_url=webhook_url,
            created_at=now, updated_at=now,
        )
    )
    await session.commit()
    return await get_budget_by_id(session, bid)


async def get_budget_by_id(session, budget_id: str) -> dict | None:
    result = await session.execute(select(budgets).where(budgets.c.id == budget_id))
    row = result.mappings().first()
    return dict(row) if row else None


async def get_budget_by_user(session, user_id: str) -> dict | None:
    result = await session.execute(select(budgets).where(budgets.c.user_id == user_id))
    row = result.mappings().first()
    return dict(row) if row else None


async def update_budget(session, budget_id: str, **fields) -> dict | None:
    fields["updated_at"] = _now()
    await session.execute(update(budgets).where(budgets.c.id == budget_id).values(**fields))
    await session.commit()
    return await get_budget_by_id(session, budget_id)


async def check_budget_status(session, user_id: str, current_spend: float) -> dict:
    """Check if a user's current spend is within budget limits.

    Returns dict with: within_budget (bool), daily_limit, monthly_limit,
    daily_spend, monthly_spend, alert_threshold_exceeded.
    """
    from .crud_analytics import user_total_spend

    budget = await get_budget_by_user(session, user_id)
    if not budget:
        return {"within_budget": True, "has_budget": False}

    # Calculate daily and monthly spend
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    daily_spend = await user_total_spend(session, user_id, since=day_start)
    monthly_spend = await user_total_spend(session, user_id, since=month_start)

    within_budget = True
    if budget["daily_limit"] is not None and daily_spend >= budget["daily_limit"]:
        within_budget = False
    if budget["monthly_limit"] is not None and monthly_spend >= budget["monthly_limit"]:
        within_budget = False

    alert_exceeded = False
    threshold = budget.get("alert_threshold", 0.8)
    if budget["daily_limit"] and daily_spend >= budget["daily_limit"] * threshold:
        alert_exceeded = True
    if budget["monthly_limit"] and monthly_spend >= budget["monthly_limit"] * threshold:
        alert_exceeded = True

    return {
        "within_budget": within_budget,
        "has_budget": True,
        "daily_limit": budget["daily_limit"],
        "monthly_limit": budget["monthly_limit"],
        "daily_spend": round(daily_spend, 6),
        "monthly_spend": round(monthly_spend, 6),
        "alert_threshold_exceeded": alert_exceeded,
    }


# ── Cost Alerts ───────────────────────────────────────────────────────────

async def create_alert(session, *, user_id: str, budget_id: str,
                       alert_type: str, message: str,
                       current_spend: float, limit_amount: float) -> dict:
    await session.execute(
        cost_alerts.insert().values(
            user_id=user_id, budget_id=budget_id,
            alert_type=alert_type, message=message,
            current_spend=current_spend, limit_amount=limit_amount,
            is_acknowledged=False, triggered_at=_now(),
        )
    )
    await session.commit()
    # Return the latest alert for this budget
    result = await session.execute(
        select(cost_alerts).where(cost_alerts.c.budget_id == budget_id)
        .order_by(cost_alerts.c.id.desc()).limit(1)
    )
    row = result.mappings().first()
    return dict(row) if row else {}


async def list_unacknowledged_alerts(session, user_id: str) -> list[dict]:
    result = await session.execute(
        select(cost_alerts)
        .where(cost_alerts.c.user_id == user_id, cost_alerts.c.is_acknowledged == False)  # noqa: E712
        .order_by(cost_alerts.c.id.desc())
    )
    return [dict(row) for row in result.mappings().all()]


async def acknowledge_alert(session, alert_id: int) -> None:
    await session.execute(
        update(cost_alerts).where(cost_alerts.c.id == alert_id)
        .values(is_acknowledged=True, acknowledged_at=_now())
    )
    await session.commit()
