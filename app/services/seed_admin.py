"""Ensure the designated admin account exists and is flagged is_admin."""

from sqlalchemy import select, text

from app.config import settings
from app.database import async_session, engine
from app.models import User
from app.utils.auth import hash_password


async def ensure_admin_schema() -> None:
    """Add is_admin if the DB was created before the column existed."""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin "
                "BOOLEAN NOT NULL DEFAULT false"
            )
        )


async def ensure_document_schema() -> None:
    """Add chunk settings columns if the DB was created before they existed."""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "ALTER TABLE documents "
                "ADD COLUMN IF NOT EXISTS chunk_size INTEGER NOT NULL DEFAULT 500"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE documents "
                "ADD COLUMN IF NOT EXISTS chunk_overlap INTEGER NOT NULL DEFAULT 50"
            )
        )


async def ensure_admin_user() -> None:
    email = settings.ADMIN_EMAIL.strip().lower()
    password = settings.ADMIN_PASSWORD
    full_name = settings.ADMIN_FULL_NAME.strip() or "Admin"

    async with async_session() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if user:
            user.is_admin = True
            user.full_name = full_name
            # Keep password in sync with configured admin password so login always works.
            user.hashed_password = hash_password(password)
        else:
            session.add(
                User(
                    email=email,
                    hashed_password=hash_password(password),
                    full_name=full_name,
                    subscription_tier="business",
                    is_admin=True,
                )
            )

        await session.commit()
