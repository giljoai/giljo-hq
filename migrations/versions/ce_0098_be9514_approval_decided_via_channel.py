# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0098_be9514_approval_decided_via_channel"
down_revision = "ce_0097_be9475_participant_self_reported_status"
branch_labels = None
depends_on = None


_TABLE = "user_approvals"
_COLUMN = "decided_via"
_CONSTRAINT = "ck_user_approvals_decided_via"
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
