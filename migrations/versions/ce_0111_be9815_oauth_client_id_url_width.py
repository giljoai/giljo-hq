# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0111_be9815_oauth_client_id_url_width"
down_revision = "ce_0110_fe9789b_retire_tenant_prompt_rung"
branch_labels = None
depends_on = None

_TABLES = ("oauth_authorization_codes", "oauth_refresh_tokens")
_WIDE = 256
_NARROW = 64


def _client_id_length(inspector: sa.Inspector, table: str) -> int | None:
    if table not in inspector.get_table_names():
        return None
    for column in inspector.get_columns(table):
        if column["name"] == "client_id":
            return getattr(column["type"], "length", None)
    return None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table in _TABLES:
        length = _client_id_length(inspector, table)
        if length is not None and length < _WIDE:
            op.alter_column(
                table,
                "client_id",
                existing_type=sa.String(length=length),
                type_=sa.String(length=_WIDE),
                existing_nullable=False,
            )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table in _TABLES:
        length = _client_id_length(inspector, table)
        if length is None or length <= _NARROW:
            continue
        op.execute(sa.text(f"DELETE FROM {table} WHERE length(client_id) > {_NARROW}"))  # noqa: S608 - constant table names
        op.alter_column(
            table,
            "client_id",
            existing_type=sa.String(length=length),
            type_=sa.String(length=_NARROW),
            existing_nullable=False,
        )
