# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9514: record which DOOR decided an approval, not a fake user.

Revision ID: ce_0098_be9514_approval_decided_via_channel
Revises: ce_0097_be9475_participant_self_reported_status
Create Date: 2026-08-27

WHY. Approvals can be answered from more than one channel, and not every
channel carries a user back-reference, so ``decided_by_user_id`` alone cannot
describe how a decision arrived.

THE REJECTED FIX. Writing a sentinel like ``"agent"`` into ``decided_by_user_id``
is wrong: that column is a USER IDENTIFIER (FK to ``users.id``). A sentinel
string corrupts its meaning and breaks anything that resolves it to a person.

THE ACTUAL DESIGN. Record the CHANNEL beside the actor, not instead of it.
``decided_by_user_id`` is UNCHANGED -- still NULL when there genuinely is no
person. This column, ``decided_via`` (``'ui'`` | ``'mcp'``), is what answers
the question an approval audit row actually needs to answer: per ADR-009 the
tenant is permanently single-user, so *who* is never ambiguous -- it is the
account owner, always. The real question is HUMAN or MACHINE, and that is what
this column carries. Populated in the ONE writer both doors already share,
``UserApprovalService.mark_decided`` -- never at a call site, so there is no
second source of truth to drift.

NULLABLE, NO BACKFILL, DELIBERATELY. Existing rows predate this column and
genuinely do not know which door decided them -- inventing an answer would be
worse than admitting the gap. Readers must tolerate NULL; the CHECK constraint
below allows NULL and constrains only a non-NULL value to the closed
('ui', 'mcp') vocabulary, since this value is server-derived (never raw agent
input), matching the existing ``ck_user_approvals_status`` pattern.

IDEMPOTENT: the CE installer reruns ``alembic upgrade`` on every boot, and a
fresh install gets this column + constraint straight from
``baseline_v38_unified`` (parity edit shipped with this migration), so the
guards below are the normal path there, not an edge case.
"""

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "ce_0098_be9514_approval_decided_via_channel"
down_revision = "ce_0097_be9475_participant_self_reported_status"
branch_labels = None
depends_on = None


_TABLE = "user_approvals"
_COLUMN = "decided_via"
_CONSTRAINT = "ck_user_approvals_decided_via"
# THE COMMENT IS LOAD-BEARING AND MUST MATCH ``baseline_v38_unified`` EXACTLY --
# see ce_0097's note on why (test_inf5060_squash_baseline_v38.py compares column
# comments between the fresh-install and chain-replay paths).
_COMMENT = "BE-9514: which door decided this ('ui' | 'mcp'); NULL for legacy rows predating the column"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return

    existing_columns = {c["name"] for c in inspector.get_columns(_TABLE)}
    if _COLUMN not in existing_columns:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(length=10), nullable=True, comment=_COMMENT))

    existing_constraints = {c["name"] for c in inspector.get_check_constraints(_TABLE)}
    if _CONSTRAINT not in existing_constraints:
        op.create_check_constraint(
            _CONSTRAINT,
            _TABLE,
            f"{_COLUMN} IS NULL OR {_COLUMN} IN ('ui', 'mcp')",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return

    existing_constraints = {c["name"] for c in inspector.get_check_constraints(_TABLE)}
    if _CONSTRAINT in existing_constraints:
        op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")

    existing_columns = {c["name"] for c in inspector.get_columns(_TABLE)}
    if _COLUMN in existing_columns:
        op.drop_column(_TABLE, _COLUMN)
