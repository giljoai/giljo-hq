# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from alembic import op
from sqlalchemy import inspect


revision = "ce_0093_drop_export_alias"
down_revision = "ce_0092_product_slug_and_export_alias"
branch_labels = None
depends_on = None


_ASSIGNMENTS = "product_agent_assignments"

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

    if _ASSIGNMENTS in tables:
        if "export_alias" not in _columns(inspector, _ASSIGNMENTS):
            op.execute(f"ALTER TABLE {_ASSIGNMENTS} ADD COLUMN export_alias VARCHAR(128)")
        op.execute(f"COMMENT ON COLUMN {_ASSIGNMENTS}.export_alias IS '{_ALIAS_COMMENT}'")
