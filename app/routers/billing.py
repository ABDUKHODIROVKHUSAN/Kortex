from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.schemas.auth import UserResponse
from app.schemas.billing import UpgradeTierRequest, UpgradeTierResponse
from app.services.tiers import VALID_TIERS, normalize_tier
from app.utils.auth import get_current_user

router = APIRouter()


def _tier_label(tier: str) -> str:
    return tier.capitalize()


@router.post("/upgrade-tier", response_model=UpgradeTierResponse)
async def upgrade_tier(
    body: UpgradeTierRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tier = body.tier.strip().lower()
    if tier not in VALID_TIERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid tier. Must be one of: free, pro, business",
        )

    if tier == "free":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot downgrade via this endpoint",
        )

    try:
        current_user.subscription_tier = tier
        await db.flush()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update subscription tier",
        ) from exc

    return UpgradeTierResponse(
        success=True,
        message=f"Upgraded to {_tier_label(tier)}",
        userTier=tier,
    )


@router.get("/me-tier")
async def get_my_tier(current_user: User = Depends(get_current_user)):
    tier = normalize_tier(current_user.subscription_tier)
    return {
        "success": True,
        "data": UserResponse(
            id=str(current_user.id),
            email=current_user.email,
            full_name=current_user.full_name,
            phone=current_user.phone,
            avatar_url=current_user.avatar_url,
            subscription_tier=tier,
        ).model_dump(),
        "message": "Tier retrieved",
    }
