"""Add indexing progress fields to documents."""

from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "ALTER TABLE documents "
            "ADD COLUMN IF NOT EXISTS progress_percent INTEGER NOT NULL DEFAULT 0"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE documents "
            "ADD COLUMN IF NOT EXISTS progress_stage VARCHAR(32) NOT NULL DEFAULT 'queued'"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE documents DROP COLUMN IF EXISTS progress_stage"))
    op.execute(sa.text("ALTER TABLE documents DROP COLUMN IF EXISTS progress_percent"))
