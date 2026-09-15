# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models import Product, Project, Task
from giljo_mcp.services.roadmap_validation import format_missing_refusal


_REF_KINDS: dict[str, tuple[Any, str]] = {
    "project": (Project, "project_id"),
    "task": (Task, "task_id"),
}


def _is_uuid_shaped(value: str) -> bool:
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


async def _alias_to_id(
    session: AsyncSession,
    tenant_key: str,
    product_id: str,
    model: Any,
    aliases: set[str],
) -> dict[str, str]:
    rows = await session.execute(
        select(model.taxonomy_alias, model.id).where(
            model.tenant_key == tenant_key,
            model.product_id == product_id,
            model.deleted_at.is_(None),
            model.taxonomy_alias.in_(aliases),
        )
    )

    mapping: dict[str, str] = {}
    ambiguous: set[str] = set()
    for alias, row_id in rows:
        if alias in mapping:
            ambiguous.add(alias)
        mapping[alias] = row_id

    if ambiguous:
        raise ValidationError(
            message=(
                f"alias(es) {sorted(ambiguous)} match more than one row in the active product -- "
                f"refusing to guess which one you meant; use the id instead"
            ),
            context={"operation": "upsert_roadmap_items", "ambiguous_aliases": sorted(ambiguous)},
        )
    return mapping


async def resolve_refs(
    session: AsyncSession,
    tenant_key: str,
    product_id: str,
    *reference_lists: list[dict[str, Any]],
) -> None:
    pending: dict[str, set[str]] = {"project": set(), "task": set()}
    for refs in reference_lists:
        for row in refs:
            kind = row.get("item_type")
            if kind not in _REF_KINDS:
                continue
            value = row.get(_REF_KINDS[kind][1])
            if value and not _is_uuid_shaped(value):
                pending[kind].add(value)

    for kind, aliases in pending.items():
        if not aliases:
            continue
        model, key = _REF_KINDS[kind]
        mapping = await _alias_to_id(session, tenant_key, product_id, model, aliases)
        if not mapping:
            continue
        for refs in reference_lists:
            for row in refs:
                if row.get("item_type") == kind and row.get(key) in mapping:
                    row[key] = mapping[row[key]]


async def _explain_missing(
    session: AsyncSession,
    tenant_key: str,
    product_id: str,
    model: Any,
    missing: set[str],
    *,
    noun: str,
) -> str:
    elsewhere = {
        row[0]
        for row in await session.execute(select(model.id).where(model.tenant_key == tenant_key, model.id.in_(missing)))
    }
    active = (
        await session.execute(select(Product.name).where(Product.tenant_key == tenant_key, Product.id == product_id))
    ).scalar_one_or_none()
    return format_missing_refusal(
        noun=noun,
        elsewhere=sorted(elsewhere),
        unknown=sorted(missing - elsewhere),
        active_label=f"'{active}' ({product_id})" if active else product_id,
    )


async def assert_items_in_product(
    session: AsyncSession,
    tenant_key: str,
    product_id: str,
    validated: list[dict[str, Any]],
) -> None:
    project_ids = {v["project_id"] for v in validated if v["item_type"] == "project"}
    task_ids = {v["task_id"] for v in validated if v["item_type"] == "task"}

    messages: list[str] = []
    context: dict[str, Any] = {"operation": "upsert_roadmap_items"}

    if project_ids:
        rows = await session.execute(
            select(Project.id).where(
                Project.tenant_key == tenant_key,
                Project.product_id == product_id,
                Project.id.in_(project_ids),
            )
        )
        missing = project_ids - {r[0] for r in rows}
        if missing:
            messages.append(await _explain_missing(session, tenant_key, product_id, Project, missing, noun="project"))
            context["missing_project_ids"] = sorted(missing)

    if task_ids:
        rows = await session.execute(
            select(Task.id).where(
                Task.tenant_key == tenant_key,
                Task.product_id == product_id,
                Task.deleted_at.is_(None),
                Task.id.in_(task_ids),
            )
        )
        missing = task_ids - {r[0] for r in rows}
        if missing:
            messages.append(await _explain_missing(session, tenant_key, product_id, Task, missing, noun="task"))
            context["missing_task_ids"] = sorted(missing)

    if messages:
        raise ValidationError(message=" || ".join(messages), context=context)
