# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from alembic import op
from sqlalchemy import inspect, text


revision = "ce_0092_product_slug_and_export_alias"
down_revision = "ce_0091_backfill_product_agent_assignments"
branch_labels = None
depends_on = None


_PRODUCTS = "products"
_ASSIGNMENTS = "product_agent_assignments"
_SLUG_INDEX = "idx_product_slug_unique_per_tenant"

_SLUG_COMMENT = "BE-9385b: stable URL-safe short name qualifying exported agent filenames"
_ALIAS_COMMENT = "BE-9385b: server-persisted export rename, so a renamed agent still spawns"

_BACKFILL_SLUGS_SQL = text(
    """
    UPDATE products AS p
    SET slug = d.base || CASE WHEN d.rn = 1 THEN '' ELSE '-' || d.rn END
    FROM (
        SELECT
            id,
            base,
            row_number() OVER (PARTITION BY tenant_key, base ORDER BY created_at, id) AS rn
        FROM (
            SELECT
                id,
                tenant_key,
                created_at,
                COALESCE(
                    NULLIF(
                        trim(BOTH '-' FROM left(
                            trim(BOTH '-' FROM regexp_replace(lower(name), '[^a-z0-9]+', '-', 'g')),
                            48
                        )),
                        ''
                    ),
                    'product'
                ) AS base
            FROM products
            WHERE slug IS NULL AND deleted_at IS NULL
        ) AS s
    ) AS d
    WHERE p.id = d.id
    """
)


def _columns(inspector, table: str) -> set[str]:
    return {c["name"] for c in inspector.get_columns(table)}


def _indexes(inspector, table: str) -> set[str]:
    return {i["name"] for i in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if _PRODUCTS in tables:
        if "slug" not in _columns(inspector, _PRODUCTS):
            op.execute("ALTER TABLE products ADD COLUMN slug VARCHAR(64)")
        op.execute(f"COMMENT ON COLUMN products.slug IS '{_SLUG_COMMENT}'")

        backfilled = bind.execute(_BACKFILL_SLUGS_SQL).rowcount

        if _SLUG_INDEX not in _indexes(inspector, _PRODUCTS):
            op.execute(
                f"CREATE UNIQUE INDEX {_SLUG_INDEX} "
                "ON products (tenant_key, slug) WHERE deleted_at IS NULL AND slug IS NOT NULL"
            )
        print(f"ce_0092: backfilled {backfilled} product slug(s)")  # noqa: T201

    if _ASSIGNMENTS in tables:
        if "export_alias" not in _columns(inspector, _ASSIGNMENTS):
            op.execute(f"ALTER TABLE {_ASSIGNMENTS} ADD COLUMN export_alias VARCHAR(128)")
        op.execute(f"COMMENT ON COLUMN {_ASSIGNMENTS}.export_alias IS '{_ALIAS_COMMENT}'")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if _ASSIGNMENTS in tables and "export_alias" in _columns(inspector, _ASSIGNMENTS):
        op.execute(f"ALTER TABLE {_ASSIGNMENTS} DROP COLUMN export_alias")

    if _PRODUCTS in tables:
        if _SLUG_INDEX in _indexes(inspector, _PRODUCTS):
            op.execute(f"DROP INDEX {_SLUG_INDEX}")
        if "slug" in _columns(inspector, _PRODUCTS):
            op.execute("ALTER TABLE products DROP COLUMN slug")
