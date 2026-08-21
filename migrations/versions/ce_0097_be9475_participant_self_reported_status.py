# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9475: let a headless participant report its own status.

Revision ID: ce_0097_be9475_participant_self_reported_status
Revises: ce_0096_pme_fts_git_commits_be9469
Create Date: 2026-08-20

WHY. The Hub's status dot reads ``agent_executions`` through
``latest_execution_status()``, correlated on ``agent_id == participant_id``. A
headless agent -- an operator-driven lane that joins with ``join_thread`` -- never
registers an execution row, so that subquery serves NULL for its whole life. The
client reads NULL-status-with-a-``last_seen_at`` as ``idle``, labelled
"Monitoring". Verified against a live CE database 2026-08-19: such a lane shows
"Monitoring" the entire time it is saturating a core, and no amount of care on
the agent's part changes that. These two columns are the channel it lacks.

WHAT IT DOES NOT DO. ``self_reported_status`` is a FALLBACK, never an override:
the read-side expression coalesces the execution status FIRST, so an agent the
platform is actually running cannot contradict the Jobs board about itself. Both
columns are nullable with no default and no backfill -- an existing row keeps
NULL, and NULL-both-ways is byte-identical to the behaviour before this
migration. Nothing that renders today changes shape.

NO CHECK CONSTRAINT, DELIBERATELY. The vocabulary
(``VALID_SELF_REPORTED_STATUSES``: working / waiting / blocked / idle / sleeping /
complete) is enforced at the MCP write boundary instead. This value arrives from
an AI agent, and a constraint violation surfaces as a 500 -- the wrong answer for
input that should get a 422-shaped refusal naming the valid set. A constraint here
would also make the vocabulary a schema migration to change, on a set whose whole
point is that it tracks the dashboard's colour map.

IDEMPOTENT: the CE installer reruns ``alembic upgrade`` on every boot, and a fresh
install gets these columns straight from ``baseline_v38_unified`` (parity edit
shipped with this migration), so the guard below is the normal path there, not an
edge case.
"""

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "ce_0097_be9475_participant_self_reported_status"
down_revision = "ce_0096_pme_fts_git_commits_be9469"
branch_labels = None
depends_on = None


_TABLE = "comm_participants"

# name -> (type factory, comment). A CALLABLE for the type, not a prebuilt Column:
# op.add_column binds the Column object it is handed to a Table, so a module-level
# instance cannot be reused across the two calls (nor across upgrade/downgrade in one
# process).
#
# THE COMMENTS ARE LOAD-BEARING AND MUST MATCH ``baseline_v38_unified`` EXACTLY.
# ``test_inf5060_squash_baseline_v38.py::test_parity_fast_path_vs_chain_replay`` compares
# column COMMENTS between a fresh baseline install and a full chain replay, and fails on
# any difference. Shipping these on the baseline alone made the two paths diverge -- a
# real parity break that the test caught. If either copy is edited, edit both.
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
