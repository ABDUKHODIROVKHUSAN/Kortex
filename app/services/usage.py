from datetime import UTC, date, datetime, timedelta, time
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user_usage import UserDailyUsage


def _today() -> date:
    return datetime.now(UTC).date()


def _resets_at_iso() -> str:
    tomorrow = datetime.combine(_today() + timedelta(days=1), time.min, tzinfo=UTC)
    return tomorrow.isoformat()


def estimate_tokens(*texts: str) -> int:
    total = sum(len(t) for t in texts if t)
    return max(1, total // 4)


def _usage_payload(used_requests: int, used_tokens: int) -> dict:
    req_limit = settings.DAILY_CHAT_REQUEST_LIMIT
    tok_limit = settings.DAILY_CHAT_TOKEN_LIMIT
    return {
        "requests_used": used_requests,
        "requests_limit": req_limit,
        "requests_remaining": max(0, req_limit - used_requests),
        "tokens_used": used_tokens,
        "tokens_limit": tok_limit,
        "tokens_remaining": max(0, tok_limit - used_tokens),
        "resets_at": _resets_at_iso(),
    }


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


async def get_usage(db: AsyncSession, user_id: UUID) -> dict:
    row = await _get_or_create_row(db, user_id, _today())
    return _usage_payload(row.request_count, row.token_count)


async def ensure_can_chat(db: AsyncSession, user_id: UUID) -> dict:
    usage = await get_usage(db, user_id)
    if usage["requests_remaining"] <= 0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Daily chat request limit reached. Try again after reset.",
        )
    if usage["tokens_remaining"] <= 0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Daily token limit reached. Try again after reset.",
        )
    return usage


async def record_chat_usage(
    db: AsyncSession, user_id: UUID, tokens: int
) -> dict:
    row = await _get_or_create_row(db, user_id, _today())
    row.request_count += 1
    row.token_count += tokens
    await db.flush()
    return _usage_payload(row.request_count, row.token_count)
