"""Category optimistic version.

Revision ID: 0007_category_version
Revises: 0006_auth
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_category_version"
down_revision: str | None = "0006_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "category",
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.create_check_constraint("ck_category_version", "category", "version >= 1")


def downgrade() -> None:
    op.drop_constraint("ck_category_version", "category", type_="check")
    op.drop_column("category", "version")
