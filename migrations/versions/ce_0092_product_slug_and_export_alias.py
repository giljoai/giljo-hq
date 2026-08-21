# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Add products.slug and product_agent_assignments.export_alias.

Revision ID: ce_0092_product_slug_and_export_alias
Revises: ce_0091_backfill_product_agent_assignments
Create Date: 2026-08-09

BE-9385b -- exported agents become ``<agent-name>--<product-slug>.md`` so the same
agent shared by two products installs side by side instead of overwriting itself,
and a rename can never break spawning.

Two columns, two distinct jobs
------------------------------
``products.slug`` -- the stable, unique, URL-safe short name that qualifies an
exported filename. Persisted rather than derived at render time for two reasons
that a derived slug cannot provide: it is **immutable across a rename** (so files
already installed keep their names), and it is **unique by index** (so two
products whose names slugify identically -- "Acme Corp" and "Acme-Corp" -- cannot
produce the same filename).

``product_agent_assignments.export_alias`` -- the server-persisted rename applied
when an install hits a genuine conflict and the user chooses "keep both". It MUST
be server-side: spawn resolution is ``get_template_by_name(tenant, name,
product_id=...)`` and a Claude Code orchestrator spawns ``Task(subagent_type=X)``
against the file's frontmatter ``name``. A client-side rename the server never
learns about breaks spawning silently, which is the worst failure available here.
Per (product, template) is the right grain: an alias is a fact about this agent
*in this product*, not about the tenant-wide template row.

Chain routing
-------------
``products`` and ``product_agent_assignments`` are both CE tables, so this belongs
in ``migrations/versions/``, never ``saas_versions/``.

Baseline parity (INF-5060)
--------------------------
Unlike the data-only ce_0091, this migration CHANGES SCHEMA, so it is paired with
a matching ``baseline_v38_unified.py`` edit -- the ce_0081/ce_0043 precedent. A
fresh install gets the columns and the index from the baseline; an existing DB
gets them from here; both converge on an identical shape.

Idempotency
-----------
The CE installer reruns the whole chain on every boot, so every step is
existence-guarded: columns are added only when absent, the index only when
absent, and the backfill only touches rows whose slug ``IS NULL``. A second run
does nothing and prints 0.

Data-facing DoD
---------------
The slug backfill answers "what happens to rows already in the old shape?" for
every existing product. It is additive and one-way: a row that already has a slug
is never rewritten, so re-running this after a user has products cannot renumber
their exports. Rows are de-duplicated deterministically (oldest product keeps the
bare slug; later collisions get ``-2``, ``-3``, …) rather than by insertion luck,
so the same database always backfills to the same slugs.

Soft-deleted products are deliberately left ``NULL``: the unique index only
covers live rows, a deleted product exports nothing, and the render path tolerates
a NULL slug by deriving one from the name. That tolerance is the belt to this
migration's braces -- see ``src/giljo_mcp/product_slug.py``.
"""

from alembic import op
from sqlalchemy import inspect, text


revision = "ce_0092_product_slug_and_export_alias"
down_revision = "ce_0091_backfill_product_agent_assignments"
branch_labels = None
depends_on = None


_PRODUCTS = "products"
_ASSIGNMENTS = "product_agent_assignments"
_SLUG_INDEX = "idx_product_slug_unique_per_tenant"

# Must match the baseline's create_table comments byte-for-byte -- the INF-5060
# parity test compares column comments between the fast path and a chain replay.
_SLUG_COMMENT = "BE-9385b: stable URL-safe short name qualifying exported agent filenames"
_ALIAS_COMMENT = "BE-9385b: server-persisted export rename, so a renamed agent still spawns"

# Mirrors ``slugify_product_name`` in src/giljo_mcp/product_slug.py: lowercase,
# every run of non-alphanumerics collapsed to a single hyphen, trimmed, capped at
# 48 chars and re-trimmed (a cut can leave a trailing hyphen), empty -> 'product'.
# Kept as SQL rather than importing the app helper because a migration must run
# against a schema whose application code may be a different version.
# Oldest product keeps the bare slug; later collisions within the same tenant get
# a numeric suffix. Ordering by (created_at, id) makes the assignment
# deterministic rather than dependent on physical row order.
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

    # Belt-and-braces for a DB stamped mid-chain where a table does not exist yet.
    if _PRODUCTS in tables:
        if "slug" not in _columns(inspector, _PRODUCTS):
            op.execute("ALTER TABLE products ADD COLUMN slug VARCHAR(64)")
        # The comment is part of the schema the INF-5060 parity test compares
        # (fast-path baseline vs full chain replay), so it is NOT decoration: the
        # baseline's create_table declares it, and ALTER TABLE ADD COLUMN does not
        # carry one, so it has to be set here or the two paths diverge. COMMENT ON
        # is naturally idempotent.
        op.execute(f"COMMENT ON COLUMN products.slug IS '{_SLUG_COMMENT}'")

        backfilled = bind.execute(_BACKFILL_SLUGS_SQL).rowcount

        # Created AFTER the backfill: building it first would reject the very
        # duplicates the backfill exists to disambiguate.
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
