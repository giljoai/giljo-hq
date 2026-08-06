# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Message Hub identity foundation: message ``from_kind`` + participant ``harness`` / ``last_seen_at``.

Revision ID: ce_0086_hub_identity_foundation
Revises: ce_0085_heal_giljo_hq_bootstrap_rebrand
Create Date: 2026-07-25

BE-9289a -- the SERVER takes ownership of Hub identity. Three columns:

``messages.from_kind`` ('agent' | 'user')
    Who the author IS, resolved server-side at post time. ``from_agent_id`` is the
    FUNCTIONAL identity (recipient self-exclusion, baton matching, read cursors) and is
    self-declared, so its SHAPE carries no information about the author's kind -- an
    agent may legitimately post under a UUID slug. Readers previously guessed from that
    shape and rendered such agents as the human user.

``comm_participants.harness``
    Which CLI / agent app drives the session, stamped from the MCP ``initialize``
    handshake (harness_resolver.harness_from_client_info) and never self-declared.

``comm_participants.last_seen_at``
    Last activity of any kind on the thread, so a live/idle indicator is derivable.

Operations
----------
1. Add nullable ``from_kind`` (String(10)) to ``messages`` -- deliberately WITHOUT a
   default at this point, so the backfill below can still see which rows are unset.
2. Backfill ``from_kind`` for every pre-existing row (see "Data-facing DoD").
3. Set ``from_kind`` DEFAULT 'agent' and NOT NULL, now that no NULLs remain.
4. Add nullable ``harness`` (String(32)) to ``comm_participants``.
5. Add nullable ``last_seen_at`` (DateTime(timezone=True)) to ``comm_participants``.

Chain routing
-------------
All three are columns on CE models (``models/tasks.py``, ``models/comm.py``), so this
lives in ``migrations/versions/`` (the CE chain), NEVER ``saas_versions/``. Paired with
a parity edit to ``baseline_v38_unified.py`` declaring the same columns at the END of
their create_table blocks -- this migration APPENDS them, so declaring them last in the
baseline keeps the fresh-install and chain-replay schemas byte-identical (the INF-5060
parity invariant covers column ORDER).

Idempotency
-----------
The column adds are guarded by ``inspect()`` existence checks. The backfill UPDATEs are
all predicated on ``from_kind IS NULL``, so a second run matches zero rows. SET DEFAULT
and SET NOT NULL are idempotent in PostgreSQL. The CE installer reruns the chain on
every boot, so every step must be re-runnable.

Data-facing DoD
---------------
``from_kind`` is a NEW fact about EXISTING rows, so option (b) applies: an idempotent
migration rewrites them, in three deterministic passes, most authoritative first.

  1. The participant directory, where a row exists for the poster on that thread --
     ``participant_type`` is exactly this fact, already recorded. Unique on
     (thread_id, participant_id), so the join resolves to at most one row.
  2. Otherwise, a ``from_agent_id`` that resolves to a real ``users`` row is a user
     post (the principal-fallback path wrote the user id into that field).
  3. Everything else on this board is agent traffic.

Making the column NOT NULL with a server default is the point of the exercise: a
nullable column would force every reader to keep exactly the fallback heuristic this
project exists to delete. The default is 'agent' because every non-Hub insert path into
``messages`` (the project bus, agent job messaging, forwarding) is agent traffic; only
CommThreadService.post() can produce a 'user' row, and it stamps that explicitly.

Edition Scope: Both -- CE tables, inherited unchanged by SaaS via its next preDeploy
alembic run.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision = "ce_0086_hub_identity_foundation"
down_revision = "ce_0085_heal_giljo_hq_bootstrap_rebrand"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    message_columns = [c["name"] for c in inspector.get_columns("messages")]
    if "from_kind" not in message_columns:
        op.add_column(
            "messages",
            sa.Column(
                "from_kind",
                sa.String(length=10),
                nullable=True,
                comment="BE-9289a: author kind ('agent'|'user'), resolved server-side at post time",
            ),
        )

    # Backfill BEFORE the default/NOT NULL lands, so "unset" is still observable.
    # Pass 1 -- the participant directory already records this fact authoritatively.
    op.execute(
        sa.text(
            """
            UPDATE messages AS m
               SET from_kind = p.participant_type
              FROM comm_participants AS p
             WHERE p.thread_id = m.thread_id
               AND p.participant_id = m.from_agent_id
               AND p.tenant_key = m.tenant_key
               AND m.from_kind IS NULL
            """
        )
    )
    # Pass 2 -- the principal-fallback path stamped a real user id into from_agent_id.
    op.execute(
        sa.text(
            """
            UPDATE messages AS m
               SET from_kind = 'user'
              FROM users AS u
             WHERE u.id = m.from_agent_id
               AND m.from_kind IS NULL
            """
        )
    )
    # Pass 3 -- everything else on this board is agent traffic.
    op.execute(sa.text("UPDATE messages SET from_kind = 'agent' WHERE from_kind IS NULL"))

    # No NULLs remain: pin it so no reader ever has to guess again.
    op.execute(sa.text("ALTER TABLE messages ALTER COLUMN from_kind SET DEFAULT 'agent'"))
    op.execute(sa.text("ALTER TABLE messages ALTER COLUMN from_kind SET NOT NULL"))

    participant_columns = [c["name"] for c in inspector.get_columns("comm_participants")]
    if "harness" not in participant_columns:
        op.add_column(
            "comm_participants",
            sa.Column(
                "harness",
                sa.String(length=32),
                nullable=True,
                comment="BE-9289a: harness token stamped from the MCP handshake; never self-declared",
            ),
        )
    if "last_seen_at" not in participant_columns:
        op.add_column(
            "comm_participants",
            sa.Column(
                "last_seen_at",
                sa.DateTime(timezone=True),
                nullable=True,
                comment="BE-9289a: last post/read/poll on this thread; drives the live-idle indicator",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    participant_columns = [c["name"] for c in inspector.get_columns("comm_participants")]
    if "last_seen_at" in participant_columns:
        op.drop_column("comm_participants", "last_seen_at")
    if "harness" in participant_columns:
        op.drop_column("comm_participants", "harness")

    message_columns = [c["name"] for c in inspector.get_columns("messages")]
    if "from_kind" in message_columns:
        op.drop_column("messages", "from_kind")
