"""Add chunk_size and chunk_overlap to documents."""

from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "ALTER TABLE documents "
            "ADD COLUMN IF NOT EXISTS chunk_size INTEGER NOT NULL DEFAULT 500"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE documents "
            "ADD COLUMN IF NOT EXISTS chunk_overlap INTEGER NOT NULL DEFAULT 50"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE documents DROP COLUMN IF EXISTS chunk_overlap"))
    op.execute(sa.text("ALTER TABLE documents DROP COLUMN IF EXISTS chunk_size"))
