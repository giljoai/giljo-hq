# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision = "ce_0078_projects_superseded_status_and_successor"
down_revision = "baseline_v38"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE project_status ADD VALUE IF NOT EXISTS 'superseded'")

    bind = op.get_bind()
    inspector = inspect(bind)

    columns = [c["name"] for c in inspector.get_columns("projects")]
    if "successor_project_id" not in columns:
        op.add_column(
            "projects",
            sa.Column(
                "successor_project_id",
                sa.String(length=36),
                nullable=True,
                comment="FK to the project that supersedes this one (audit trail for replaced work)",
            ),
        )

    op.execute(
        """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'projects_successor_project_id_fkey') THEN
                ALTER TABLE ONLY public.projects
                    ADD CONSTRAINT projects_successor_project_id_fkey
                    FOREIGN KEY (successor_project_id)
                    REFERENCES public.projects(id) ON DELETE SET NULL;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE ONLY public.projects DROP CONSTRAINT IF EXISTS projects_successor_project_id_fkey")

    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("projects")]
    if "successor_project_id" in columns:
        op.drop_column("projects", "successor_project_id")
