# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Enforce NOT NULL on projects.product_id, healing orphans instead of deleting them.

Revision ID: ce_0004_projects_product_id_not_null
Revises: ce_0003_widen_alembic_version
Create Date: 2026-04-27

Projects must always belong to a product. Historical NULL rows leaked into
every product's project list via an OR-NULL fallback in the repository filter,
so the column is set NOT NULL here and the issue cannot recur at the data layer.

REWRITTEN 2026-08-15 (BE-9437), under an explicit ruling. As shipped, this
migration's upgrade() opened with::

    DELETE FROM projects WHERE product_id IS NULL

with the comment "none expected in a healthy install". That is a silent,
unrecoverable data loss on any install where the assumption was wrong, and the
CE installer reruns ``alembic upgrade`` on every boot with no operator present
to notice. CLAUDE.md's data-facing DoD is explicit that a convention change must
either tolerate the old shape or rewrite it with an idempotent migration, and
that "fix prod manually" is banned; deleting the rows is neither. The operator
ruled on 2026-08-15 that a project MUST belong to a product -- which settles
WHERE the rows go, not whether they survive. They survive.

WHY THE FIX LIVES HERE, in a shipped revision, rather than in a new one. A new
head revision runs AFTER this one, so by the time it executed the rows would
already be gone. This is the only point in the chain where the orphans still
exist. The change is heal-only -- the enforcement, the revision id and the final
schema are identical -- so it makes an existing invariant reachable without
losing data rather than altering what this migration means. Any database that
has already run this revision never runs it again, so the affected population is
pre-ce_0004 installs only, and for them the outcome changes from "lose your
product-less projects" to "keep them, filed under a product".

BACKFILL POLICY: BIND, never delete.
* Target product = the tenant's oldest live product (its only one, where it has
  exactly one). Soft-deleted products are not candidates -- filing a live
  project into a trashed product hides it just as effectively as deleting it.
* A tenant with orphans but NO live product gets one created for it, named so
  the user can find what happened. The alternative is refusing to boot over
  data the user cannot be asked about. That INSERT has a collision of its own:
  ``idx_product_single_active_per_tenant`` is UNIQUE(tenant_key) WHERE
  is_active=true and does NOT exclude soft-deleted rows, so a tenant whose only
  product is trashed-but-active still holds the slot. The placeholder's
  ``is_active`` is therefore derived rather than hardcoded.

BINDING IS NOT FREE: it moves rows into buckets that already have occupants, and
two partial unique indexes on this table constrain those buckets. Both are
healed, because either one would otherwise abort the migration -- turning a
boot-time upgrade into a boot failure, which is the exact outcome this file now
exists to prevent:
* ``idx_project_single_active_per_product`` -- UNIQUE(product_id) WHERE
  status='active'. NULL product_ids escape it under Postgres' default NULLS
  DISTINCT, so a tenant may legitimately hold several ACTIVE orphans today.
  The incumbent active project keeps its status; later arrivals are demoted to
  inactive. Status is recoverable in one click; a failed boot is not.
* ``uq_project_taxonomy_active`` -- UNIQUE(tenant_key, product_id,
  project_type_id, series_number, subseries) NULLS NOT DISTINCT WHERE
  deleted_at IS NULL. An orphan entering a product's bucket can collide with a
  row already there. The arriving row is renumbered above the bucket's
  watermark, the same reassign-above-the-high-water-mark rule ce_0067 and
  ce_0095 use. Note the watermark is computed over ``projects`` ALONE: at this
  revision ``tasks`` has no ``series_number`` column at all (the shared
  tasks+projects serial line arrives much later, with BE-6049b), so the shared
  watermark those revisions use does not yet exist and must not be assumed here.

IDEMPOTENT. The guard is the column's own ``is_nullable``: once NOT NULL, every
rerun returns immediately. A fresh install reaches this revision with no orphan
rows and a baseline that already declares the column NOT NULL, so it is a pure
no-op there too.

Edition Scope: Both (``projects`` is a CE core table; SaaS runs the CE chain,
and migrations/saas_versions/ does not reference this table).
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text


revision = "ce_0004_projects_product_id_not_null"
down_revision = "ce_0003_widen_alembic_version"
branch_labels = None
depends_on = None


_PLACEHOLDER_NAME = "Recovered Projects"


def _product_id_is_nullable(conn) -> bool | None:
    """``True``/``False`` for the live column, ``None`` when it does not exist."""
    value = conn.execute(
        text(
            """
            SELECT is_nullable FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'projects' AND column_name = 'product_id'
            """
        )
    ).scalar()
    return None if value is None else value == "YES"


def _target_product(conn, tenant_key: str) -> tuple[str, bool]:
    """The product this tenant's orphans bind to. Returns ``(id, was_created)``.

    ``created_at`` is nullable and Postgres sorts NULLs last on ASC, so a product
    with no timestamp is treated as the newest -- and the tie-break on id keeps
    the choice stable across reruns.
    """
    existing = conn.execute(
        text(
            """
            SELECT id FROM products
            WHERE tenant_key = :tk AND deleted_at IS NULL
            ORDER BY created_at, id
            LIMIT 1
            """
        ),
        {"tk": tenant_key},
    ).scalar()
    if existing is not None:
        return existing, False

    # ``is_active`` is DERIVED, not hardcoded true. ``products`` carries
    # ``idx_product_single_active_per_tenant`` -- UNIQUE(tenant_key) WHERE
    # is_active = true, with NO deleted_at clause, so even a SOFT-DELETED active
    # product still holds that slot. Inserting an unconditionally-active
    # placeholder for such a tenant raises a unique violation and aborts the
    # upgrade, which is the boot failure this rewrite exists to avoid. The
    # subquery makes the placeholder active only where the slot is genuinely
    # free, so the INSERT cannot collide.
    product_id = str(uuid.uuid4())
    conn.execute(
        text(
            """
            INSERT INTO products (id, tenant_key, name, description, is_active)
            VALUES (:id, :tk, :name, :description,
                    NOT EXISTS (SELECT 1 FROM products WHERE tenant_key = :tk AND is_active = true))
            """
        ),
        {
            "id": product_id,
            "tk": tenant_key,
            "name": _PLACEHOLDER_NAME,
            "description": (
                "Created automatically so projects that belonged to no product could be kept. "
                "Rename it, or move these projects to a product of your own."
            ),
        },
    )
    return product_id, True


def _watermark(conn, tenant_key: str, product_id: str) -> int:
    """Highest live serial in the ``(tenant_key, product_id)`` bucket (0 if none).

    Projects only. ``tasks`` carries no ``series_number`` at this revision.
    """
    return conn.execute(
        text(
            """
            SELECT COALESCE(MAX(series_number), 0) FROM projects
            WHERE tenant_key = :tk AND product_id = :pid AND deleted_at IS NULL
            """
        ),
        {"tk": tenant_key, "pid": product_id},
    ).scalar_one()


def _taxonomy_is_taken(conn, tenant_key, product_id, type_id, series, subseries, exclude_id) -> bool:
    """Would this row collide under ``uq_project_taxonomy_active``?

    ``IS NOT DISTINCT FROM`` on every nullable member, because that index is
    ``NULLS NOT DISTINCT`` -- so the detector and the index agree by
    construction rather than by a hand-written NULL dance.
    """
    return (
        conn.execute(
            text(
                """
                SELECT 1 FROM projects
                WHERE tenant_key = :tk
                  AND product_id = :pid
                  AND project_type_id IS NOT DISTINCT FROM :ptid
                  AND series_number IS NOT DISTINCT FROM :sn
                  AND subseries IS NOT DISTINCT FROM :sub
                  AND deleted_at IS NULL
                  AND id <> :exclude
                LIMIT 1
                """
            ),
            {
                "tk": tenant_key,
                "pid": product_id,
                "ptid": type_id,
                "sn": series,
                "sub": subseries,
                "exclude": exclude_id,
            },
        ).scalar()
        is not None
    )


def _active_is_taken(conn, product_id: str, exclude_id: str) -> bool:
    """Does this product already hold an ACTIVE project?

    ``status::text`` rather than a bare comparison: the column is VARCHAR at this
    revision and becomes the ``project_status`` ENUM at ce_0008, and the cast
    reads the same either way.
    """
    return (
        conn.execute(
            text(
                """
                SELECT 1 FROM projects
                WHERE product_id = :pid AND status::text = 'active' AND id <> :exclude
                LIMIT 1
                """
            ),
            {"pid": product_id, "exclude": exclude_id},
        ).scalar()
        is not None
    )


def _heal_orphans(conn) -> tuple[int, int, int, int]:
    """Bind every product-less project. Returns (bound, products_made, renumbered, demoted).

    Rows are handled oldest-first and each UPDATE lands before the next row is
    examined, so an orphan is checked against the effects of the ones already
    healed -- which is what makes orphan-versus-orphan collisions resolve without
    a second pass.
    """
    orphans = conn.execute(
        text(
            """
            SELECT id, tenant_key, status, project_type_id, series_number, subseries, deleted_at
            FROM projects
            WHERE product_id IS NULL
            ORDER BY created_at, id
            """
        )
    ).fetchall()

    targets: dict[str, str] = {}
    bound = products_made = renumbered = demoted = 0

    for orphan in orphans:
        product_id = targets.get(orphan.tenant_key)
        if product_id is None:
            product_id, was_created = _target_product(conn, orphan.tenant_key)
            targets[orphan.tenant_key] = product_id
            products_made += int(was_created)

        series, subseries = orphan.series_number, orphan.subseries
        # The taxonomy index is partial on ``deleted_at IS NULL``, so a
        # soft-deleted orphan is out of its scope and must not be renumbered.
        if orphan.deleted_at is None and _taxonomy_is_taken(
            conn, orphan.tenant_key, product_id, orphan.project_type_id, series, subseries, orphan.id
        ):
            series = _watermark(conn, orphan.tenant_key, product_id) + 1
            subseries = None
            renumbered += 1

        # Decided BEFORE the bind and applied IN it. Binding first and demoting
        # after cannot work: the UPDATE that sets product_id is itself the
        # statement that violates idx_project_single_active_per_product, so the
        # migration aborts before the demotion it was relying on ever runs. The
        # single-active index has no deleted_at clause, so this applies to
        # soft-deleted rows too.
        demote = orphan.status == "active" and _active_is_taken(conn, product_id, orphan.id)

        # 'inactive' is a LITERAL, not a bind parameter: Postgres coerces a
        # literal to the project_status ENUM this column becomes at ce_0008,
        # which a bound string would not be.
        status_clause = ", status = 'inactive'" if demote else ""
        conn.execute(
            text(
                f"""
                UPDATE projects
                SET product_id = :pid, series_number = :sn, subseries = :sub{status_clause}
                WHERE id = :id
                """
            ),
            {"pid": product_id, "sn": series, "sub": subseries, "id": orphan.id},
        )
        bound += 1
        demoted += int(demote)

    return bound, products_made, renumbered, demoted


def upgrade() -> None:
    conn = op.get_bind()

    if _product_id_is_nullable(conn) is not True:
        return  # already enforced -- CE reruns this on every boot

    # Hold the lock the ALTER will take anyway, but take it BEFORE healing.
    # Without it there is a window between the last UPDATE and the ALTER in which
    # a still-running old process could insert a fresh NULL row, and the ALTER
    # would then fail -- turning a healing migration back into the boot breaker
    # it exists to prevent. Same reasoning as ce_0095's lock-before-heal.
    op.execute("LOCK TABLE projects IN ACCESS EXCLUSIVE MODE")

    bound, products_made, renumbered, demoted = _heal_orphans(conn)

    # Say it out loud when it happens. This files a user's projects somewhere
    # they did not put them, and possibly renumbers or deactivates them -- none
    # of which an operator should have to discover from the UI. Quiet on the
    # overwhelmingly common zero case.
    if bound:
        notice = f"ce_0004: bound {bound} product-less project(s) to a product"
        if products_made:
            notice += f"; created {products_made} '{_PLACEHOLDER_NAME}' product(s) for tenants that had none"
        if renumbered:
            notice += f"; renumbered {renumbered} to avoid a taxonomy collision"
        if demoted:
            notice += f"; deactivated {demoted} (a product holds one active project)"
        print(notice)  # noqa: T201

    op.alter_column("projects", "product_id", existing_type=sa.String(length=36), nullable=False)


def downgrade() -> None:
    # Schema only. The bound rows are valid data and the products they were
    # filed under may since have been used, so the backfill is not reverted --
    # the same one-way stance ce_0067 and ce_0095 take on their healing.
    op.alter_column("projects", "product_id", existing_type=sa.String(length=36), nullable=True)
