# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision = "ce_0087_comm_threads_sequence_run_fk"
down_revision = "ce_0086_hub_identity_foundation"
branch_labels = None
depends_on = None


_FK_NAME = "comm_threads_sequence_run_id_fkey"
_INDEX_NAME = "idx_comm_thread_sequence_run"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    columns = [c["name"] for c in inspector.get_columns("comm_threads")]
    if "sequence_run_id" not in columns:
        op.add_column(
            "comm_threads",
            sa.Column(
                "sequence_run_id",
                sa.String(length=36),
                nullable=True,
                comment="BE-9291: the chain run this thread is the coordination hub for (NULL = not a hub)",
            ),
        )

    op.execute(
        sa.text(
            f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{_FK_NAME}') THEN
                    ALTER TABLE ONLY public.comm_threads
                        ADD CONSTRAINT {_FK_NAME}
                        FOREIGN KEY (sequence_run_id) REFERENCES public.sequence_runs(id)
                        ON DELETE SET NULL;
                END IF;
            END $$;
            """
        )
    )

    op.execute(
        sa.text(
            f"CREATE INDEX IF NOT EXISTS {_INDEX_NAME} ON public.comm_threads "
            "USING btree (tenant_key, sequence_run_id) WHERE sequence_run_id IS NOT NULL"
        )
    )

    op.execute(
        sa.text(
            """
            WITH candidate AS (
                SELECT t.id AS thread_id, min(r.id) AS run_id
                  FROM comm_threads AS t
                  JOIN sequence_runs AS r
                    ON r.tenant_key = t.tenant_key
                   AND position(r.id in t.subject) > 0
                 WHERE t.sequence_run_id IS NULL
                   AND t.subject IS NOT NULL
                 GROUP BY t.id
                HAVING count(*) = 1
            ),
            unhubbed AS (
                SELECT c.run_id
                  FROM candidate AS c
                 WHERE NOT EXISTS (
                           SELECT 1
                             FROM comm_threads AS linked
                            WHERE linked.sequence_run_id = c.run_id
                       )
                 GROUP BY c.run_id
                HAVING count(*) = 1
            )
            UPDATE comm_threads AS t
               SET sequence_run_id = c.run_id
              FROM candidate AS c
              JOIN unhubbed AS u ON u.run_id = c.run_id
             WHERE t.id = c.thread_id
               AND t.sequence_run_id IS NULL
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    op.execute(sa.text(f"DROP INDEX IF EXISTS {_INDEX_NAME}"))
    op.execute(sa.text(f"ALTER TABLE public.comm_threads DROP CONSTRAINT IF EXISTS {_FK_NAME}"))

    columns = [c["name"] for c in inspector.get_columns("comm_threads")]
    if "sequence_run_id" in columns:
        op.drop_column("comm_threads", "sequence_run_id")
