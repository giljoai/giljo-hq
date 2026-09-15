# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0014_rename_project_types_to_taxonomy_types"
down_revision = "ce_0013_drop_orphan_cols_batch"
branch_labels = None
depends_on = None


OLD_TABLE = "project_types"
NEW_TABLE = "taxonomy_types"

OLD_UQ = "uq_project_type_abbr"
NEW_UQ = "uq_taxonomy_type_abbr"

OLD_TENANT_IDX = "idx_project_type_tenant"
NEW_TENANT_IDX = "idx_taxonomy_type_tenant"

OLD_FK = "projects_project_type_id_fkey"
NEW_FK = "projects_taxonomy_type_id_fkey"

OLD_PK = "project_types_pkey"
NEW_PK = "taxonomy_types_pkey"


def _has_table(conn, table: str) -> bool:
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = :table"),
        {"table": table},
    )
    return result.first() is not None


def _has_constraint(conn, table: str, constraint: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE table_name = :table AND constraint_name = :constraint"
        ),
        {"table": table, "constraint": constraint},
    )
    return result.first() is not None


def _has_index(conn, index: str) -> bool:
    result = conn.execute(
        sa.text("SELECT 1 FROM pg_indexes WHERE indexname = :index"),
        {"index": index},
    )
    return result.first() is not None


def upgrade() -> None:
    conn = op.get_bind()

    if _has_table(conn, OLD_TABLE) and not _has_table(conn, NEW_TABLE):
        op.rename_table(OLD_TABLE, NEW_TABLE)

    if _has_constraint(conn, NEW_TABLE, OLD_UQ):
        op.execute(f"ALTER TABLE {NEW_TABLE} RENAME CONSTRAINT {OLD_UQ} TO {NEW_UQ}")

    if _has_index(conn, OLD_TENANT_IDX) and not _has_index(conn, NEW_TENANT_IDX):
        op.execute(f"ALTER INDEX {OLD_TENANT_IDX} RENAME TO {NEW_TENANT_IDX}")

    if _has_constraint(conn, "projects", OLD_FK):
        op.execute(f"ALTER TABLE projects RENAME CONSTRAINT {OLD_FK} TO {NEW_FK}")

    if _has_constraint(conn, NEW_TABLE, OLD_PK):
        op.execute(f"ALTER TABLE {NEW_TABLE} RENAME CONSTRAINT {OLD_PK} TO {NEW_PK}")


def downgrade() -> None:
    conn = op.get_bind()

    if _has_constraint(conn, NEW_TABLE, NEW_PK):
        op.execute(f"ALTER TABLE {NEW_TABLE} RENAME CONSTRAINT {NEW_PK} TO {OLD_PK}")

    if _has_constraint(conn, "projects", NEW_FK):
        op.execute(f"ALTER TABLE projects RENAME CONSTRAINT {NEW_FK} TO {OLD_FK}")

    if _has_index(conn, NEW_TENANT_IDX) and not _has_index(conn, OLD_TENANT_IDX):
        op.execute(f"ALTER INDEX {NEW_TENANT_IDX} RENAME TO {OLD_TENANT_IDX}")

    if _has_constraint(conn, NEW_TABLE, NEW_UQ):
        op.execute(f"ALTER TABLE {NEW_TABLE} RENAME CONSTRAINT {NEW_UQ} TO {OLD_UQ}")

    if _has_table(conn, NEW_TABLE) and not _has_table(conn, OLD_TABLE):
        op.rename_table(NEW_TABLE, OLD_TABLE)
