"""Initial tenant and user schema with RLS.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'keep_rollin_app') THEN
            CREATE ROLE keep_rollin_app NOLOGIN NOSUPERUSER NOBYPASSRLS NOINHERIT;
          END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        DO $$
        DECLARE
          role_is_super boolean;
          role_bypasses_rls boolean;
        BEGIN
          SELECT rolsuper, rolbypassrls
          INTO role_is_super, role_bypasses_rls
          FROM pg_roles
          WHERE rolname = 'keep_rollin_app';

          IF role_is_super OR role_bypasses_rls THEN
            RAISE EXCEPTION
              'keep_rollin_app must not be SUPERUSER or BYPASSRLS';
          END IF;
        END
        $$;
        """
    )

    op.create_table(
        "tenant",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", postgresql.CITEXT(), nullable=False),
        sa.Column("domain", postgresql.CITEXT(), nullable=False),
        sa.Column("subdomain", postgresql.CITEXT(), nullable=True),
        sa.Column("timezone", sa.String(length=64), server_default="Europe/Moscow", nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="RUB", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tenant"),
        sa.UniqueConstraint("domain", name="uq_tenant_domain"),
        sa.UniqueConstraint("slug", name="uq_tenant_slug"),
        sa.UniqueConstraint("subdomain", name="uq_tenant_subdomain"),
    )

    op.create_table(
        "user",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=16), server_default="user", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('owner', 'admin', 'user')", name="ck_user_role"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name="fk_user_tenant_id_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user"),
        sa.UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),
    )
    op.create_index("ix_user_tenant_id", "user", ["tenant_id"], unique=False)

    op.execute('ALTER TABLE "tenant" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "user" ENABLE ROW LEVEL SECURITY')
    op.execute(
        """
        CREATE POLICY tenant_isolation ON "tenant"
        USING (id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )
    op.execute(
        """
        CREATE POLICY user_isolation ON "user"
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )

    op.execute(
        """
        CREATE FUNCTION public.resolve_tenant(request_host text, lookup_kind text)
        RETURNS uuid
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
          SELECT id
          FROM public.tenant
          WHERE is_active
            AND (
              (lookup_kind = 'domain' AND domain = request_host::citext)
              OR (lookup_kind = 'subdomain' AND subdomain = request_host::citext)
            )
          LIMIT 1
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION public.resolve_tenant(text, text) FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA public TO keep_rollin_app")
    op.execute('GRANT SELECT, INSERT, UPDATE, DELETE ON "tenant", "user" TO keep_rollin_app')
    op.execute("GRANT EXECUTE ON FUNCTION public.resolve_tenant(text, text) TO keep_rollin_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.resolve_tenant(text, text)")
    op.drop_index("ix_user_tenant_id", table_name="user")
    op.drop_table("user")
    op.drop_table("tenant")
    # keep_rollin_app is a cluster-wide role and may be used by another
    # database on the same server; downgrading one database must not drop it.
    op.execute("DROP EXTENSION IF EXISTS btree_gist")
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
    op.execute("DROP EXTENSION IF EXISTS citext")
