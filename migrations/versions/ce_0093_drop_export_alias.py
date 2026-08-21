# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Drop product_agent_assignments.export_alias.

Revision ID: ce_0093_drop_export_alias
Revises: ce_0092_product_slug_and_export_alias
Create Date: 2026-08-10

BE-9396 -- retracts the export-alias enforcement layer that ce_0092 added one day
earlier. giljo_setup is the canonical agent installation tool and it guarantees
server -> disk: files it wrote it may refresh or relocate, files it did not write
it never touches. A file the user renames by hand leaves that guarantee, and the
install prose now says so plainly instead of the server persisting a rename and
resolving spawns through it.

Why a DROP is correct here, and not a deprecation
-------------------------------------------------
Dropping a shipped column would normally be the wrong instrument. This one was
never shipped: **no customer database ever carried it.** Production is pre-BE-9385a,
public CE never released it, and the LAN staging/test-install path re-migrates from the
chain. The column existed on private master and LAN staging for a single day. So
there is no data to preserve and no deployed reader to strand -- the conditions a
deprecation window exists to protect simply are not present.

ce_0092 is left completely untouched, filename included. A shipped migration is
never rewritten: replaying the chain must still produce the historical shape at
each step, and this revision is how the chain arrives at the current one. That is
also why ce_0092's *slug* arms are none of this migration's business -- products.slug,
its unique index and its backfill are the collision-prevention layer, they stay,
and FE-9385c depends on them.

Chain routing
-------------
``product_agent_assignments`` is a CE table, so this belongs in
``migrations/versions/``, never ``saas_versions/``.

Baseline parity (INF-5060)
--------------------------
Paired with the matching removal of the column from ``baseline_v38_unified.py``,
the same way ce_0092 was paired with its addition. Both paths converge on the
column being absent: a fresh install no longer declares it in create_table, and an
existing database gets it added by ce_0092 and removed here. The column was
declared LAST in the baseline and appended by ALTER on the chain path, so nothing
sits behind it to shift -- ``test_parity_fast_path_vs_chain_replay`` compares by
ordinal position, and dropping the final column moves no other column's ordinal.

The COMMENT that ce_0092 set is schema the parity test compares, and it leaves
with the column it described -- there is nothing left to keep the two paths in
agreement about.

Idempotency
-----------
The CE installer reruns the whole chain on every boot, so the drop is
existence-guarded on both the table and the column. A second run does nothing.
There is no index, constraint or foreign key on this column -- it is a plain
VARCHAR(128) with a comment -- so the single ALTER is the whole teardown.
"""

from alembic import op
from sqlalchemy import inspect


revision = "ce_0093_drop_export_alias"
down_revision = "ce_0092_product_slug_and_export_alias"
branch_labels = None
depends_on = None


_ASSIGNMENTS = "product_agent_assignments"

# Must match ce_0092's _ALIAS_COMMENT byte-for-byte: downgrade() restores the
# column, and the INF-5060 parity test compares column comments between the fast
# path and a chain replay.
_ALIAS_COMMENT = "BE-9385b: server-persisted export rename, so a renamed agent still spawns"


def _columns(inspector, table: str) -> set[str]:
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if _ASSIGNMENTS in tables and "export_alias" in _columns(inspector, _ASSIGNMENTS):
        op.execute(f"ALTER TABLE {_ASSIGNMENTS} DROP COLUMN export_alias")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    # Restores the column ce_0092 added, comment included, so downgrading to that
    # revision lands on the shape it defined rather than a silently narrower one.
    if _ASSIGNMENTS in tables:
        if "export_alias" not in _columns(inspector, _ASSIGNMENTS):
            op.execute(f"ALTER TABLE {_ASSIGNMENTS} ADD COLUMN export_alias VARCHAR(128)")
        op.execute(f"COMMENT ON COLUMN {_ASSIGNMENTS}.export_alias IS '{_ALIAS_COMMENT}'")
