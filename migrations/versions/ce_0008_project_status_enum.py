# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from alembic import op


revision = "ce_0008_project_status_enum"
down_revision = "ce_0007_users_skills_version_tracking"
branch_labels = None
depends_on = None


CANONICAL_STATUSES: tuple[str, ...] = (
    "inactive",
    "active",
    "completed",
    "cancelled",
    "terminated",
    "deleted",
)


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            cnt integer;
        BEGIN
            -- Fill NULLs first so the type cast cannot fail on null.
            UPDATE projects SET status = 'inactive' WHERE status IS NULL;
            GET DIAGNOSTICS cnt = ROW_COUNT;
            IF cnt > 0 THEN
                RAISE NOTICE 'ce_0008: remapped % NULL status row(s) -> inactive', cnt;
            END IF;

            -- Coalesce known historical orphans.
            UPDATE projects SET status = 'completed'
                WHERE status::text IN ('archived', 'closed');
            GET DIAGNOSTICS cnt = ROW_COUNT;
            IF cnt > 0 THEN
                RAISE NOTICE 'ce_0008: remapped % archived/closed row(s) -> completed', cnt;
            END IF;

            UPDATE projects SET status = 'inactive'
                WHERE status::text IN ('paused', 'staging');
            GET DIAGNOSTICS cnt = ROW_COUNT;
            IF cnt > 0 THEN
                RAISE NOTICE 'ce_0008: remapped % paused/staging row(s) -> inactive', cnt;
            END IF;

            -- Catch-all: anything still outside the canonical six -> inactive.
            UPDATE projects SET status = 'inactive'
                WHERE status::text NOT IN (
                    'inactive','active','completed','cancelled','terminated','deleted'
                );
            GET DIAGNOSTICS cnt = ROW_COUNT;
            IF cnt > 0 THEN
                RAISE NOTICE
                    'ce_0008: catch-all remapped % non-canonical status row(s) -> inactive',
                    cnt;
            END IF;
        END$$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'project_status') THEN
                CREATE TYPE project_status AS ENUM
                    ('inactive','active','completed','cancelled','terminated','deleted');
            END IF;
        END$$;
        """
    )

    op.execute("DROP INDEX IF EXISTS idx_project_single_active_per_product;")

    op.execute(
        """
        ALTER TABLE projects ALTER COLUMN status DROP DEFAULT;
        ALTER TABLE projects
            ALTER COLUMN status TYPE project_status USING status::project_status;
        ALTER TABLE projects
            ALTER COLUMN status SET DEFAULT 'inactive'::project_status;
        ALTER TABLE projects ALTER COLUMN status SET NOT NULL;
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_project_single_active_per_product
            ON projects (product_id)
            WHERE status = 'active'::project_status;
        """
    )


def downgrade() -> None:

    op.execute("DROP INDEX IF EXISTS idx_project_single_active_per_product;")

    op.execute(
        """
        ALTER TABLE projects
            ALTER COLUMN status DROP NOT NULL,
            ALTER COLUMN status DROP DEFAULT,
            ALTER COLUMN status TYPE varchar(50) USING status::text,
            ALTER COLUMN status SET DEFAULT 'inactive';
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_project_single_active_per_product
            ON projects (product_id)
            WHERE status = 'active';
        """
    )

    op.execute("DROP TYPE IF EXISTS project_status;")
