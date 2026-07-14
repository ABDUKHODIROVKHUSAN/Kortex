from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UpdateProfileRequest,
    UserResponse,
)
from app.utils.auth import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)

router = APIRouter()


def _user_response(user: User) -> UserResponse:
    return UserResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        phone=user.phone,
        avatar_url=user.avatar_url,
        subscription_tier=user.subscription_tier or "free",
        is_admin=bool(getattr(user, "is_admin", False)),
    )


@router.post("/register")
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        is_admin=False,
    )
    db.add(user)
    await db.flush()

    token = create_access_token({"sub": str(user.id)})
    return {
        "success": True,
        "data": TokenResponse(
            access_token=token,
            user=_user_response(user),
        ).model_dump(),
        "message": "Registration successful",
    }


@router.post("/login")
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = create_access_token({"sub": str(user.id)})
    return {
        "success": True,
        "data": TokenResponse(
            access_token=token,
            user=_user_response(user),
        ).model_dump(),
        "message": "Login successful",
    }


@router.get("/me")
async def me(current_user: User = Depends(get_current_user)):
    return {
        "success": True,
        "data": _user_response(current_user).model_dump(),
        "message": "User retrieved",
    }


async def _update_me(
    body: UpdateProfileRequest,
    current_user: User,
    db: AsyncSession,
):
    if body.email and body.email != current_user.email:
        existing = await db.execute(select(User).where(User.email == body.email))
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already in use",
            )
        current_user.email = body.email

    if body.full_name is not None:
        current_user.full_name = body.full_name

    if body.phone is not None:
        current_user.phone = body.phone or None

    if body.avatar_url is not None:
        if body.avatar_url and len(body.avatar_url) > 500_000:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Profile picture is too large",
            )
        current_user.avatar_url = body.avatar_url or None

    await db.flush()

    return {
        "success": True,
        "data": _user_response(current_user).model_dump(),
        "message": "Profile updated",
    }


@router.patch("/me")
async def update_me_patch(
    body: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _update_me(body, current_user, db)


@router.put("/me")
async def update_me_put(
    body: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _update_me(body, current_user, db)
