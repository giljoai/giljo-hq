# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
        if orphan.deleted_at is None and _taxonomy_is_taken(
            conn, orphan.tenant_key, product_id, orphan.project_type_id, series, subseries, orphan.id
        ):
            series = _watermark(conn, orphan.tenant_key, product_id) + 1
            subseries = None
            renumbered += 1

        demote = orphan.status == "active" and _active_is_taken(conn, product_id, orphan.id)

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
        return

    op.execute("LOCK TABLE projects IN ACCESS EXCLUSIVE MODE")

    bound, products_made, renumbered, demoted = _heal_orphans(conn)

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
    op.alter_column("projects", "product_id", existing_type=sa.String(length=36), nullable=True)
