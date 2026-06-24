from datetime import UTC, date, datetime, timedelta, time
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_usage import UserDailyUsage
from app.services.tiers import get_tier_limits, normalize_tier


def _today() -> date:
    return datetime.now(UTC).date()


def _month_start() -> date:
    today = _today()
    return today.replace(day=1)


def _week_start() -> date:
    today = _today()
    return today - timedelta(days=today.weekday())


def _resets_at_iso(period_end: date) -> str:
    next_day = datetime.combine(period_end + timedelta(days=1), time.min, tzinfo=UTC)
    return next_day.isoformat()


def estimate_tokens(*texts: str) -> int:
    total = sum(len(t) for t in texts if t)
    return max(1, total // 4)


async def _aggregate_usage(
    db: AsyncSession, user_id: UUID, since: date
) -> tuple[int, int]:
    result = await db.execute(
        select(
            func.coalesce(func.sum(UserDailyUsage.request_count), 0),
            func.coalesce(func.sum(UserDailyUsage.token_count), 0),
        ).where(
            UserDailyUsage.user_id == user_id,
            UserDailyUsage.usage_date >= since,
        )
    )
    row = result.one()
    return int(row[0]), int(row[1])


def _usage_payload(
    tier: str,
    used_requests: int,
    used_tokens: int,
    req_limit: int,
    tok_limit: int,
    token_period: str,
    resets_at: str,
) -> dict:
    return {
        "subscription_tier": tier,
        "requests_used": used_requests,
        "requests_limit": req_limit,
        "requests_remaining": max(0, req_limit - used_requests),
        "tokens_used": used_tokens,
        "tokens_limit": tok_limit,
        "tokens_remaining": max(0, tok_limit - used_tokens),
        "token_period": token_period,
        "resets_at": resets_at,
    }


async def get_usage(db: AsyncSession, user_id: UUID, subscription_tier: str | None) -> dict:
    tier = normalize_tier(subscription_tier)
    limits = get_tier_limits(tier)

    month_start = _month_start()
    used_requests, _ = await _aggregate_usage(db, user_id, month_start)
    req_limit = limits["questions_per_month"]

    if tier == "free":
        _, used_tokens = await _aggregate_usage(db, user_id, month_start)
        tok_limit = limits["tokens_per_month"]
        token_period = "month"
        month_end = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(
            days=1
        )
        resets_at = _resets_at_iso(max(month_end, _today()))
    else:
        week_start = _week_start()
        _, used_tokens = await _aggregate_usage(db, user_id, week_start)
        tok_limit = limits["tokens_per_week"]
        token_period = "week"
        week_end = week_start + timedelta(days=6)
        resets_at = _resets_at_iso(week_end)

    return _usage_payload(
        tier, used_requests, used_tokens, req_limit, tok_limit, token_period, resets_at
    )


async def ensure_can_chat(
    db: AsyncSession, user_id: UUID, subscription_tier: str | None
) -> dict:
    usage = await get_usage(db, user_id, subscription_tier)
    tier = usage["subscription_tier"]

    if usage["requests_remaining"] <= 0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "You've reached your monthly question limit. "
                "Upgrade to Pro for 500/month."
                if tier == "free"
                else "You've reached your monthly question limit."
            ),
        )
    if usage["tokens_remaining"] <= 0:
        period = usage["token_period"]
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"You've reached your {period}ly token limit. Try again after reset.",
        )
    return usage


async def _get_or_create_row(
    db: AsyncSession, user_id: UUID, usage_date: date
) -> UserDailyUsage:
    result = await db.execute(
        select(UserDailyUsage).where(
            UserDailyUsage.user_id == user_id,
            UserDailyUsage.usage_date == usage_date,
        )
    )
    row = result.scalar_one_or_none()
    if row:
        return row

    row = UserDailyUsage(user_id=user_id, usage_date=usage_date, request_count=0, token_count=0)
    db.add(row)
    await db.flush()
    return row


async def record_chat_usage(
    db: AsyncSession, user_id: UUID, subscription_tier: str | None, tokens: int
) -> dict:
    row = await _get_or_create_row(db, user_id, _today())
    row.request_count += 1
    row.token_count += tokens
    await db.flush()
    return await get_usage(db, user_id, subscription_tier)
