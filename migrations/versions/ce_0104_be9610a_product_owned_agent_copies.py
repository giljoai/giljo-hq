# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import uuid

from alembic import op
from sqlalchemy import inspect, text


revision = "ce_0104_be9610a_product_owned_agent_copies"
down_revision = "ce_0103_be9605b_template_model_effort"
branch_labels = None
depends_on = None


_COPIED_COLUMNS = (
    "category",
    "role",
    "system_instructions",
    "user_instructions",
    "variables",
    "behavioral_rules",
    "success_criteria",
    "tool",
    "cli_tool",
    "background_color",
    "model",
    "effort",
    "tools",
    "description",
    "version",
    "is_active",
    "tags",
    "meta_data",
    "created_by",
    "org_id",
)

_MAX_NUMERIC_SUFFIX = 20


def _crew_names(base_names, taken_names):
    try:
        from giljo_mcp.template_validation import crew_suffixed_names
    except Exception:  # noqa: BLE001 -- never fail an upgrade on an import
        return None

    result = crew_suffixed_names(list(base_names), set(taken_names))
    return None if result is None else result[0]


def _slug_names(base_names, slug, taken_names):
    suffix = slug or "product"
    names = []
    for base in base_names:
        candidate = f"{base}-{suffix}"
        n = 2
        while candidate in taken_names:
            candidate = f"{base}-{suffix}-{n}"
            n += 1
        names.append(candidate)
        taken_names.add(candidate)
    return names


def _materialise_tolerance(bind, tenant_key):
    return (
        bind.execute(
            text(
                """
                INSERT INTO product_agent_assignments (id, product_id, template_id, tenant_key, is_active)
                SELECT gen_random_uuid()::text, p.id, t.id, p.tenant_key, TRUE
                FROM products p
                JOIN agent_templates t
                  ON t.tenant_key = p.tenant_key
                 AND t.deleted_at IS NULL
                 AND t.is_active IS TRUE
                WHERE p.tenant_key = :tk
                  AND p.deleted_at IS NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM product_agent_assignments a
                      JOIN agent_templates lt ON lt.id = a.template_id
                      WHERE a.product_id = p.id
                        AND lt.deleted_at IS NULL
                        AND lt.is_active IS TRUE
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM product_agent_assignments a2
                      WHERE a2.product_id = p.id AND a2.template_id = t.id
                  )
                """
            ),
            {"tk": tenant_key},
        ).rowcount
        or 0
    )


def _load_tenant(bind, tenant_key):
    products = bind.execute(
        text("SELECT id, slug, is_default FROM products WHERE tenant_key = :tk AND deleted_at IS NULL ORDER BY id ASC"),
        {"tk": tenant_key},
    ).fetchall()
    templates = bind.execute(
        text(
            "SELECT id, name, product_id FROM agent_templates "
            "WHERE tenant_key = :tk AND deleted_at IS NULL ORDER BY id ASC"
        ),
        {"tk": tenant_key},
    ).fetchall()
    assignments = bind.execute(
        text(
            "SELECT a.id, a.product_id, a.template_id, a.is_active "
            "FROM product_agent_assignments a "
            "JOIN agent_templates t ON t.id = a.template_id "
            "WHERE a.tenant_key = :tk AND t.deleted_at IS NULL"
        ),
        {"tk": tenant_key},
    ).fetchall()
    return products, templates, assignments


def _copy_template(bind, source_id, new_id, product_id, new_name):
    columns = ", ".join(_COPIED_COLUMNS)
    bind.execute(
        text(
            f"INSERT INTO agent_templates "  # noqa: S608 -- column list is a module constant
            f"(id, tenant_key, product_id, name, is_default, created_at, {columns}) "
            f"SELECT :new_id, tenant_key, :pid, :name, FALSE, NOW(), {columns} "
            f"FROM agent_templates WHERE id = :src"
        ),
        {"new_id": new_id, "pid": product_id, "name": new_name, "src": source_id},
    )


def _migrate_tenant(bind, tenant_key):
    materialised = _materialise_tolerance(bind, tenant_key)
    products, templates, assignments = _load_tenant(bind, tenant_key)
    if not templates:
        return 0, 0, 0, materialised

    product_ids = [row[0] for row in products]
    slug_by_product = {row[0]: row[1] for row in products}
    live_products = set(product_ids)
    if not live_products:
        return 0, 0, 0, materialised

    fallback_owner = next((row[0] for row in products if row[2]), product_ids[0])

    owners_by_template = {}
    for _aid, product_id, template_id, is_active in assignments:
        if is_active and product_id in live_products:
            owners_by_template.setdefault(template_id, []).append(product_id)

    taken_names = {row[1] for row in templates}
    copies_by_product = {}
    stamped = 0

    for template_id, name, existing_product_id in templates:
        owners = sorted(owners_by_template.get(template_id, []))

        if not owners:
            owner = existing_product_id if existing_product_id in live_products else fallback_owner
            bind.execute(
                text("UPDATE agent_templates SET product_id = :pid WHERE id = :tid"),
                {"pid": owner, "tid": template_id},
            )
            stamped += 1
            continue

        keeper = owners[0]
        bind.execute(
            text("UPDATE agent_templates SET product_id = :pid WHERE id = :tid"),
            {"pid": keeper, "tid": template_id},
        )
        stamped += 1

        for extra_owner in owners[1:]:
            copies_by_product.setdefault(extra_owner, []).append((template_id, name))

    copied = 0
    for product_id, batch in copies_by_product.items():
        base_names = [name for _tid, name in batch]
        names = _crew_names(base_names, taken_names)
        if names is None:
            names = _slug_names(base_names, slug_by_product.get(product_id), taken_names)
            print(  # noqa: T201
                f"ce_0104: no free numeric crew suffix for product {product_id}; "
                f"named {len(names)} copy(ies) with the product slug instead"
            )
        for (source_id, _name), new_name in zip(batch, names, strict=True):
            new_id = str(uuid.uuid4())
            _copy_template(bind, source_id, new_id, product_id, new_name)
            bind.execute(
                text(
                    "UPDATE product_agent_assignments SET template_id = :new_tid "
                    "WHERE tenant_key = :tk AND product_id = :pid AND template_id = :old_tid"
                ),
                {"new_tid": new_id, "tk": tenant_key, "pid": product_id, "old_tid": source_id},
            )
            taken_names.add(new_name)
            copied += 1

    dropped = bind.execute(
        text(
            "DELETE FROM product_agent_assignments a "
            "USING agent_templates t "
            "WHERE a.tenant_key = :tk AND a.template_id = t.id "
            "AND a.is_active IS FALSE "
            "AND t.product_id IS NOT NULL AND t.product_id <> a.product_id"
        ),
        {"tk": tenant_key},
    ).rowcount

    return stamped, copied, dropped or 0, materialised


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if not {"product_agent_assignments", "products", "agent_templates"} <= tables:
        return

    tenant_keys = [
        row[0]
        for row in bind.execute(
            text("SELECT DISTINCT tenant_key FROM agent_templates WHERE deleted_at IS NULL ORDER BY tenant_key")
        ).fetchall()
    ]

    total_stamped = total_copied = total_dropped = total_materialised = 0
    for tenant_key in tenant_keys:
        stamped, copied, dropped, materialised = _migrate_tenant(bind, tenant_key)
        total_stamped += stamped
        total_copied += copied
        total_dropped += dropped
        total_materialised += materialised
        if copied or dropped or materialised:
            print(  # noqa: T201
                f"ce_0104: tenant {tenant_key[:12]}... stamped {stamped}, copied {copied}, "
                f"materialised {materialised} implicit row(s), dropped {dropped} stale switched-off row(s)"
            )

    healed = bind.execute(
        text("UPDATE agent_templates SET is_active = TRUE WHERE deleted_at IS NULL AND is_active IS NOT TRUE")
    ).rowcount

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_template_tenant_product "
        "ON public.agent_templates USING btree (tenant_key, product_id)"
    )

    print(  # noqa: T201
        f"ce_0104: {len(tenant_keys)} tenant(s); stamped {total_stamped} agent(s), "
        f"made {total_copied} copy(ies), wrote out {total_materialised} implicit row(s), "
        f"dropped {total_dropped} stale row(s), cleared {healed or 0} stale retire flag(s)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_template_tenant_product")
