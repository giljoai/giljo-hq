# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0009_drop_per_user_skills_tracking_add_system_announce"
down_revision = "ce_0008_project_status_enum"
branch_labels = None
depends_on = None


USERS_TABLE = "users"
COL_VERSION = "last_installed_skills_version"
COL_REMINDER = "last_update_reminder_at"
SYSTEM_SETTINGS_TABLE = "system_settings"
ANNOUNCED_KEY = "skills_version_announced"


def _has_column(conn, table: str, column: str) -> bool:
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.columns WHERE table_name = :table AND column_name = :column"),
        {"table": table, "column": column},
    )
    return result.first() is not None


def _has_table(conn, table: str) -> bool:
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = :table"),
        {"table": table},
    )
    return result.first() is not None


def _bundled_skills_version() -> str:
    try:
        from giljo_mcp.tools.slash_command_templates import SKILLS_VERSION

        return SKILLS_VERSION
    except Exception:  # noqa: BLE001 -- migration must not fail on import error
        return "0.0.0"


def upgrade() -> None:
    conn = op.get_bind()

    if _has_column(conn, USERS_TABLE, COL_VERSION):
        op.drop_column(USERS_TABLE, COL_VERSION)

    if _has_column(conn, USERS_TABLE, COL_REMINDER):
        op.drop_column(USERS_TABLE, COL_REMINDER)

    if not _has_table(conn, SYSTEM_SETTINGS_TABLE):
        op.create_table(
            SYSTEM_SETTINGS_TABLE,
            sa.Column("key", sa.String(length=64), primary_key=True),
            sa.Column("value", sa.Text(), nullable=False),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
        )

    seed_value = _bundled_skills_version()
    conn.execute(
        sa.text(
            "INSERT INTO system_settings (key, value, updated_at) "
            "VALUES (:key, :value, CURRENT_TIMESTAMP) "
            "ON CONFLICT (key) DO NOTHING"
        ),
        {"key": ANNOUNCED_KEY, "value": seed_value},
    )


def downgrade() -> None:
    conn = op.get_bind()

    if _has_table(conn, SYSTEM_SETTINGS_TABLE):
        op.drop_table(SYSTEM_SETTINGS_TABLE)

    if not _has_column(conn, USERS_TABLE, COL_REMINDER):
        op.add_column(
            USERS_TABLE,
            sa.Column(COL_REMINDER, sa.DateTime(timezone=True), nullable=True),
        )

    if not _has_column(conn, USERS_TABLE, COL_VERSION):
        op.add_column(
            USERS_TABLE,
            sa.Column(COL_VERSION, sa.String(length=32), nullable=True),
        )
