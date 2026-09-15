# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0097_be9475_participant_self_reported_status"
down_revision = "ce_0096_pme_fts_git_commits_be9469"
branch_labels = None
depends_on = None


_TABLE = "comm_participants"

_COLUMNS = (
    (
        "self_reported_status",
        lambda: sa.String(length=20),
        "BE-9475: participant's own status claim; FALLBACK only -- agent_executions wins",
    ),
    (
        "self_reported_status_at",
        lambda: sa.DateTime(timezone=True),
        "BE-9475: when that claim was made; recorded for forensics, never aged out",
    ),
)


def _existing_columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(_TABLE)}


def upgrade() -> None:
    existing = _existing_columns()
    for name, make_type, comment in _COLUMNS:
        if name not in existing:
            op.add_column(_TABLE, sa.Column(name, make_type(), nullable=True, comment=comment))


def downgrade() -> None:
    existing = _existing_columns()
    for name, _make_type, _comment in reversed(_COLUMNS):
        if name in existing:
            op.drop_column(_TABLE, name)
