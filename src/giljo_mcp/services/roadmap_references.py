# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""How a roadmap item's project/task reference is turned into a real row (BE-9474).

Two steps, in this order, both tenant-scoped and both refusing rather than
guessing:

1. **Resolve** — a reference that is not UUID-shaped is looked up as the row's
   ``taxonomy_alias`` (``BE-0001``, ``IMP-0086``, or a type-less project's
   6-character ``alias``). An agent already holds those; before this it had to
   spend a ``list_projects`` + ``list_tasks`` round trip translating them into
   UUIDs by hand for every row it wanted to rank.
2. **Assert** — every reference that survives resolution must name a row of the
   ACTIVE product, in this tenant. Unchanged from the behaviour this module was
   extracted from.

**A UUID-shaped reference is never looked up at all.** That is what makes the
change backward compatible structurally rather than by testing: a caller sending
raw UUIDs, as every caller does today, takes the identical code path it always
did and never touches a resolution query.

**No resolution oracle (the reason resolution refuses quietly).** An alias that
matches nothing, an alias belonging to a different product, and an alias
belonging to a different tenant all fall through unresolved into the same
"do not exist in this workspace" bucket ``format_missing_refusal`` already
words. A caller cannot tell the three apart, so the tool cannot be used to probe
for another tenant's rows. Do not add a "did you mean", a near-match, or a
distinct not-found code here; each of those turns this into the probe surface
BE-9469 refused ``before_id`` for.

**Ambiguity cannot happen, and is still refused.** ``uq_project_taxonomy_active``
/ ``uq_task_taxonomy_active`` are UNIQUE over
``(tenant_key, product_id, type_id, series_number, subseries)`` for non-deleted
rows — exactly the tuple an alias is built from — so within the scope resolved
here an alias names at most one row. The duplicate guard below is therefore
unreachable today; it exists so that relaxing that constraint fails loudly
instead of silently picking a row for the user.

**One asymmetry, documented rather than "fixed".** Resolution excludes
soft-deleted rows, because that is the scope the uniqueness proof above holds
in. A soft-deleted PROJECT is still roadmap-able by raw UUID (only the task
branch of the assert filters ``deleted_at``, per BE-6130b). That inconsistency
predates BE-9474 and the incident behind it was not reproduced here, so the
museum rule says pin and describe it, not change it.

Edition Scope: CE.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models import Product, Project, Task
from giljo_mcp.services.roadmap_validation import format_missing_refusal


# item_type -> (model, the normalized item key holding its reference)
_REF_KINDS: dict[str, tuple[Any, str]] = {
    "project": (Project, "project_id"),
    "task": (Task, "task_id"),
}


def _is_uuid_shaped(value: str) -> bool:
    """True when the reference is already a row id, so no lookup is needed."""
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
    """``{taxonomy_alias: id}`` for the active product's non-deleted rows.

    Exact match, never case-insensitive or fuzzy: an agent that asks for a row
    should get that row or nothing, and a looser match would weaken the
    uniqueness argument this module rests on.
    """
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
    """Rewrite alias references to row ids, in place, across every list given.

    Both the upsert ``items`` and the ``remove`` refs go through here so an
    agent may name a row the same way in either. A reference that resolves to
    nothing is left exactly as it arrived: the upsert path then refuses it
    through :func:`assert_items_in_product`, and the removal path treats it as
    the no-op an unknown ref has always been.
    """
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
    """Sort rejected ids into "in another product" vs "does not exist" (BE-9420).

    Both lookups stay inside the tenant: a foreign-tenant id lands in the
    nonexistent bucket deliberately. Wording lives in
    ``roadmap_validation.format_missing_refusal``, which explains why.
    """
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
    """Reject any item whose project/task is not in the active product + tenant.

    BE-9474: both halves are checked before raising. Previously a payload
    carrying an unknown project AND an unknown task reported the projects, and
    the agent learned about the tasks only on the resend.
    """
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
                Task.deleted_at.is_(None),  # BE-6130b: can't roadmap a trashed task
                Task.id.in_(task_ids),
            )
        )
        missing = task_ids - {r[0] for r in rows}
        if missing:
            messages.append(await _explain_missing(session, tenant_key, product_id, Task, missing, noun="task"))
            context["missing_task_ids"] = sorted(missing)

    if messages:
        raise ValidationError(message=" || ".join(messages), context=context)
