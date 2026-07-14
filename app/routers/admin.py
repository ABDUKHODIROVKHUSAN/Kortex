from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Document, SystemFailure, User
from app.schemas.admin import AdminFailureItem, AdminStats, AdminUserItem
from app.utils.auth import get_current_admin

router = APIRouter()


@router.get("/stats")
async def admin_stats(
    _: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0
    total_documents = (await db.execute(select(func.count(Document.id)))).scalar() or 0
    free_users = (
        await db.execute(
            select(func.count(User.id)).where(User.subscription_tier == "free")
        )
    ).scalar() or 0
    pro_users = (
        await db.execute(
            select(func.count(User.id)).where(User.subscription_tier == "pro")
        )
    ).scalar() or 0
    business_users = (
        await db.execute(
            select(func.count(User.id)).where(User.subscription_tier == "business")
        )
    ).scalar() or 0
    unread_failures = (
        await db.execute(
            select(func.count(SystemFailure.id)).where(SystemFailure.is_read.is_(False))
        )
    ).scalar() or 0

    return {
        "success": True,
        "data": AdminStats(
            total_users=total_users,
            total_documents=total_documents,
            free_users=free_users,
            pro_users=pro_users,
            business_users=business_users,
            unread_failures=unread_failures,
        ).model_dump(),
        "message": "Admin stats retrieved",
    }


@router.get("/users")
async def admin_users(
    _: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    doc_counts = (
        await db.execute(
            select(Document.user_id, func.count(Document.id))
            .group_by(Document.user_id)
        )
    ).all()
    count_map = {row[0]: int(row[1]) for row in doc_counts}

    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()

    items = [
        AdminUserItem(
            id=str(u.id),
            email=u.email,
            full_name=u.full_name,
            subscription_tier=u.subscription_tier or "free",
            is_admin=bool(u.is_admin),
            document_count=count_map.get(u.id, 0),
            created_at=u.created_at,
        ).model_dump()
        for u in users
    ]

    return {
        "success": True,
        "data": items,
        "message": "Admin users retrieved",
    }


@router.get("/failures")
async def admin_failures(
    _: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
):
    limit = max(1, min(limit, 200))
    result = await db.execute(
        select(SystemFailure)
        .order_by(SystemFailure.created_at.desc())
        .limit(limit)
    )
    failures = result.scalars().all()
    items = [
        AdminFailureItem(
            id=str(f.id),
            user_id=str(f.user_id) if f.user_id else None,
            user_email=f.user_email,
            document_id=str(f.document_id) if f.document_id else None,
            error_type=f.error_type,
            message=f.message,
            query_preview=f.query_preview,
            is_read=bool(f.is_read),
            created_at=f.created_at,
        ).model_dump()
        for f in failures
    ]
    return {
        "success": True,
        "data": items,
        "message": "Admin failures retrieved",
    }


@router.post("/failures/{failure_id}/read")
async def mark_failure_read(
    failure_id: UUID,
    _: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SystemFailure).where(SystemFailure.id == failure_id)
    )
    failure = result.scalar_one_or_none()
    if not failure:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Failure not found",
        )
    failure.is_read = True
    await db.flush()
    return {
        "success": True,
        "data": {"id": str(failure.id), "is_read": True},
        "message": "Marked as read",
    }


@router.post("/failures/read-all")
async def mark_all_failures_read(
    _: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SystemFailure).where(SystemFailure.is_read.is_(False))
    )
    failures = result.scalars().all()
    for f in failures:
        f.is_read = True
    await db.flush()
    return {
        "success": True,
        "data": {"updated": len(failures)},
        "message": "All failures marked as read",
    }
