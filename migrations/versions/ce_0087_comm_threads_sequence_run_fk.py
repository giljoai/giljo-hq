# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Chain-hub discovery gets a real link: ``comm_threads.sequence_run_id``.

Revision ID: ce_0087_comm_threads_sequence_run_fk
Revises: ce_0086_hub_identity_foundation
Create Date: 2026-07-25

BE-9291 -- a chain hub was discovered by substring-searching its own SUBJECT for the
run_id. The conductor's seed instruction created the thread as
``"Chain ... - run {run_id}"`` and told every sub-orchestrator to find it again with
``search_threads(query="{run_id}")``, so a free-text display field was carrying lookup
machinery. The failure mode is what makes this worth a schema change: nothing raises
when it breaks -- the sub-orchestrator simply never finds its hub and goes quiet.

Operations
----------
1. Add nullable ``comm_threads.sequence_run_id`` (String(36)). Nullable because nearly
   every thread on the board is not a chain hub.
2. Add the FK to ``sequence_runs(id)`` with ``ON DELETE SET NULL``.
3. Add the PARTIAL index ``idx_comm_thread_sequence_run`` on the non-NULL rows.
4. Backfill existing hubs by reading the old convention out of the subject, ONCE.

Why ON DELETE SET NULL specifically
-----------------------------------
A finished run is PURGED (``SequenceRunService.purge_run``, BE-6189): the chain
grouping is deliberately ephemeral, while each project row and its 360 memory are the
durable record. The hub THREAD is durable too -- it holds the coordination history.

  * CASCADE would delete the hub thread and its entire message history every time a
    chain completed normally. That is data loss on the happy path.
  * RESTRICT / NO ACTION would make ``purge_run`` raise a ForeignKeyViolation and
    break chain completion.
  * SET NULL leaves the thread standing with a NULL link, which is exactly right:
    once the run is purged there is no run left to discover a hub for.

``purge_run``'s docstring previously stated "No FK references it, so this cascades to
nothing." This revision makes that false, and that docstring is corrected in the same
commit.

Backfill (Data-facing DoD, option (b))
--------------------------------------
``sequence_run_id`` is a new fact about existing rows, so the migration rewrites them
rather than leaving the old shape stranded. The match is deliberately conservative:

  * a candidate is a LIVE-or-deleted thread with a subject containing the id of a
    ``sequence_runs`` row IN THE SAME TENANT -- ``position(r.id in t.subject) > 0``.
    Tenant-scoped, so a run id can never pull in another tenant's thread;
  * only threads matching EXACTLY ONE run are written (``candidate``'s
    ``HAVING count(*) = 1``). An ambiguous subject naming two runs is left NULL rather
    than guessed at, because ``UPDATE ... FROM`` would otherwise pick one
    non-deterministically;
  * and SYMMETRICALLY, only runs claimed by exactly one candidate thread are written
    (``unhubbed``). A run whose id appears in two subjects is skipped entirely, and so
    is one that already carries a link;
  * a run already purged is simply not in the table, so its hub stays NULL -- correct,
    and the only shape the FK would accept anyway.

Why the second guard is not optional
------------------------------------
``HAVING count(*) = 1`` on ``candidate`` bounds RUNS PER THREAD. It does not bound
THREADS PER RUN, and nothing else did either: ``idx_comm_thread_sequence_run`` is a
plain index rather than a unique one. Two threads naming the same run therefore both
got stamped, and both then landed in the FK branch of the resolver's CASE -- so the
AUTHORITATIVE branch stopped discriminating and the only tiebreak left was
``created_at`` ascending. The oldest thread mentioning a run id is not necessarily
its hub, so resolution answered with the wrong thread and raised nothing.

That shape needs no misbehaviour, only a retry: a conductor whose ``create_thread``
succeeds at chain staging step 0 but which dies before recording the id will re-run
step 0 and leave two hubs behind. Skipping such a run costs nothing that was not
already lost -- resolution still reaches both threads down the legacy subject branch,
which is exactly the pre-``ce_0087`` behaviour. The migration declines to assert an
authoritative link it cannot determine, rather than asserting a wrong one.

The ``NOT EXISTS`` half covers the same collision arriving from the other direction:
the CE installer reruns the chain on every boot, so this backfill meets databases that
already carry conductor-stamped links, and a legacy thread naming an already-hubbed run
must not become its second hub. It is deliberately not tenant-qualified --
``sequence_runs.id`` is globally unique, so a link anywhere is a link to that same run,
and the check only ever PREVENTS a write.

Rows the backfill cannot reach are NOT stranded: resolution falls back to the legacy
subject substring (``_comm_thread_chain_hub_mixin``), so option (a) covers the tail.
That tolerance is why dropping the run_id from FUTURE subjects is safe.

Idempotency
-----------
The column, constraint and index adds are existence-guarded (``inspect()`` /
``IF NOT EXISTS`` / ``pg_constraint`` lookup). The backfill is predicated on
``sequence_run_id IS NULL``, so a second run matches zero rows. The CE installer
reruns the chain on every boot, so every step is re-runnable.

Edition Scope: Both -- ``comm_threads`` and ``sequence_runs`` are CE tables, so this
lives in the CE chain and SaaS inherits it unchanged on its next preDeploy alembic run.
"""

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

    # Backfill: read the old subject convention ONCE, for hubs that predate the column.
    # Unambiguous in BOTH directions -- see "Backfill" in the module docstring.
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
