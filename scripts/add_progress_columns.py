"""One-off: add indexing progress columns and stamp alembic to 006."""
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import text

from app.database import engine


async def main() -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "ALTER TABLE documents "
                "ADD COLUMN IF NOT EXISTS progress_percent INTEGER NOT NULL DEFAULT 0"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE documents "
                "ADD COLUMN IF NOT EXISTS progress_stage VARCHAR(32) NOT NULL DEFAULT 'queued'"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS alembic_version ("
                "version_num VARCHAR(32) NOT NULL"
                ")"
            )
        )
        row = await conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
        current = row.scalar()
        if current is None:
            await conn.execute(
                text("INSERT INTO alembic_version (version_num) VALUES ('006')")
            )
        else:
            await conn.execute(
                text("UPDATE alembic_version SET version_num = '006'")
            )
        print("OK: progress columns ready, alembic stamped to 006")


if __name__ == "__main__":
    asyncio.run(main())
