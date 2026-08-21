# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Project status: convert ``projects.status`` from VARCHAR to a Postgres ENUM.

Revision ID: ce_0008_project_status_enum
Revises: ce_0007_users_skills_version_tracking
Create Date: 2026-04-30

BE-5039 Phase 2a -- Single Source of Truth for project status.

Design reference: BE-5039 project-status single-source-of-truth design,
section 3.4 (Decision 4 -- migration strategy).

Operations
----------
1. **Pre-flight orphan remap** (idempotent UPDATEs). Any value outside the
   canonical six is coalesced to a canonical replacement so the
   subsequent ``ALTER COLUMN ... TYPE project_status`` cannot fail on a
   bad cast. Each step logs a ``RAISE NOTICE`` with the affected row
   count so the migration output is auditable in CI / test installs.

2. **Create the ENUM type** ``project_status`` guarded by ``IF NOT EXISTS``
   (Postgres does not support ``CREATE TYPE ... IF NOT EXISTS`` natively
   so we use a ``DO $$`` block).

3. **Drop the partial unique index** ``idx_project_single_active_per_product``.
   Its predicate references ``status::text``; we drop and recreate it
   against the new column type to avoid leaving the planner with a stale
   text-cast expression.

4. **Convert the column type** with a ``USING status::project_status``
   cast, set the default to ``'inactive'::project_status``, and add
   ``NOT NULL``.

5. **Recreate the partial unique index** referencing the enum value.

The plain ``idx_project_status`` btree index does NOT need a rebuild --
ENUM columns are indexable directly.

Idempotency
-----------
* The pre-flight UPDATEs use status::text in WHERE clauses so they
  are safe to re-run against an already-migrated (ENUM) column. Without
  the cast, a re-run crashes with InvalidTextRepresentation because
  Postgres tries to cast literals like 'archived' to the ENUM type
  before comparison. This matters because startup.py's schema-heal can
  reset alembic to baseline and re-run the chain against a DB whose
  column is already ENUM.
* The pre-flight UPDATEs are no-ops if the target rows are already
  canonical (zero matches in the WHERE).
* ``CREATE TYPE`` is guarded by ``IF NOT EXISTS``.
* ``DROP INDEX`` uses ``IF EXISTS``.
* The ``ALTER COLUMN ... TYPE`` is itself idempotent: applying it a
  second time is a no-op when the column is already the target type.
* ``CREATE UNIQUE INDEX`` is guarded with ``IF NOT EXISTS``.

Migration chain rule (HARD)
---------------------------
This migration lives in ``migrations/versions/`` -- the CE chain --
because ``status`` is a column on the CE ``Project`` model. Putting it
in ``migrations/saas_versions/`` would crash CE deployments with
``column "status" does not exist`` because ``startup.py`` only runs
``alembic upgrade head`` against the CE chain.
"""

from alembic import op


revision = "ce_0008_project_status_enum"
down_revision = "ce_0007_users_skills_version_tracking"
branch_labels = None
depends_on = None


# Canonical enum values, kept in sync with
# ``src/giljo_mcp/domain/project_status.py::ProjectStatus`` (declaration order
# matches the Postgres ENUM order).
CANONICAL_STATUSES: tuple[str, ...] = (
    "inactive",
    "active",
    "completed",
    "cancelled",
    "terminated",
    "deleted",
)


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Step 1: Pre-flight orphan remap. Each UPDATE is idempotent (no-op
    # if no rows match). RAISE NOTICE makes the remap auditable in CI /
    # test-install logs.
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Step 2: Create the ENUM type, idempotently.
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Step 3: Drop the partial unique index that references status::text.
    # ------------------------------------------------------------------
    op.execute("DROP INDEX IF EXISTS idx_project_single_active_per_product;")

    # ------------------------------------------------------------------
    # Step 4: Convert the column type.
    #
    # Sequence matters here:
    #   1. DROP DEFAULT first -- Postgres refuses ``ALTER COLUMN ... TYPE``
    #      when the existing default (a VARCHAR literal) cannot be cast
    #      automatically to the target enum type.
    #   2. ALTER TYPE with USING cast.
    #   3. SET DEFAULT against the enum value.
    #   4. SET NOT NULL.
    #
    # Idempotency: applying this sequence a second time is a no-op
    # because Postgres treats ``ALTER COLUMN ... TYPE T`` as a no-op
    # when the column is already T, and ``DROP DEFAULT`` / ``SET DEFAULT``
    # / ``SET NOT NULL`` are all idempotent.
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Step 5: Recreate the partial unique index against the enum value.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_project_single_active_per_product
            ON projects (product_id)
            WHERE status = 'active'::project_status;
        """
    )


def downgrade() -> None:
    # Symmetric reversal: drop the partial unique index, flip the column
    # back to varchar(50) preserving values via ``status::text``, recreate
    # the partial index against ``status = 'active'`` (text predicate),
    # and finally drop the enum type.

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
