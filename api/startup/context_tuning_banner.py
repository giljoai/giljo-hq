# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Context-tuning-due system banner (FE-9202; cadence ratified BE-9218).

Extracted as a sibling of ``background_tasks.py`` (which sits at the 800-line CI
guardrail) — the same split precedent as ``oauth_code_reaper.py`` and
``template_refresh.py``. This banner reminds the user to review their active
product's context when it has gone stale.

It belongs to the CE system-banner family (``background_tasks.emit_system_banners``
upserts/resolves it per tenant), NOT the SaaS billing family. It emits in BOTH
editions because context tuning is a core concern. The banner is per-user
(``role_filter=None``) rather than admin-only, since any user benefits from a
context review.

Cadence (BE-9218, ratified 2026-07-17): the banner fires when the tenant's active
product is **stale by the user's ``tuning_reminder_threshold``** — i.e. at least
that many projects have completed since the last tune (or since product creation,
if never tuned). This is the same count-based staleness the closeout toast uses;
both now flow from the single ``tuning_reminder_threshold`` preference through the
owning ``ProductTuningService.check_tuning_staleness``. This replaces FE-9202's
fixed 14-day/336h time cadence (the F2 "design-stands" boundary):
the banner no longer keys off wall-clock at all.

Manual-refresh reset: a manual context tune resets the countdown for free —
``ProductTuningService.apply_tuning_updates`` stamps ``last_tuned_at_sequence`` to
the current project sequence on every tune, so ``projects_since_tune`` drops to 0
and the reminder is postponed until ``threshold`` more projects complete. No
separate anchor is written here; the banner just consumes that existing state.

Resurface: the ``system.context_tuning_due`` row carries no time-based resurface
window. A dismissed reminder stays dismissed until the user actually tunes (which
makes the product no longer stale and resolves the row); the next reminder is a
fresh row raised once ``threshold`` more projects have accumulated. Resurface
cadence is therefore governed by the same threshold count, not a fixed clock.

Legacy-anchor tolerance (data-facing DoD): a ``tuning_state`` written before
sequence tracking (``last_tuned_at`` present, ``last_tuned_at_sequence`` absent)
is read as sequence 0 by ``check_tuning_staleness`` — it counts from creation
rather than erroring. Old-shape anchors degrade gracefully, no migration.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from giljo_mcp.database import DatabaseManager, tenant_session_context
from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.models.auth import User
from giljo_mcp.services.notification_service import NotificationService


logger = logging.getLogger(__name__)

CONTEXT_TUNING_DUE_DEDUPE_KEY = "system.context_tuning_due"


async def _resolve_active_user_id(db_manager: DatabaseManager, tenant_key: str) -> str | None:
    """Resolve the tenant's active user id (per-user tenancy: one user per tenant).

    The read runs inside ``tenant_session_context`` so the fail-closed tenant
    guard sees provable tenant context — a raw predicate-only ``select(User)`` in a
    contextless session is what the guard rejects (BE-9212). The explicit
    ``tenant_key`` predicate is kept alongside the context so scoping is guaranteed
    for this column-only select regardless of the guard's loader-criteria path.
    """
    async with db_manager.get_session_async() as session:
        with tenant_session_context(session, tenant_key):
            user_id = (
                await session.execute(select(User.id).where(User.tenant_key == tenant_key, User.is_active).limit(1))
            ).scalar_one_or_none()
    return str(user_id) if user_id else None


async def compute_context_tuning_due(db_manager: DatabaseManager, tenant_key: str) -> dict | None:
    """Return banner info when the tenant's active product is due for a review, else None.

    Due iff the reminder preference is on AND the product is stale by the user's
    ``tuning_reminder_threshold`` (``projects_since_tune >= threshold``, computed by
    the owning tuning service). None means "no banner" — no active product, the
    preference is off, or fewer than ``threshold`` projects have completed since the
    last tune — and drives the resolve path in
    :func:`emit_context_tuning_due_banner`.
    """
    from giljo_mcp.services.product_service import ProductService
    from giljo_mcp.services.product_tuning_service import ProductTuningService

    product_service = ProductService(db_manager=db_manager, tenant_key=tenant_key)
    product = await product_service.get_active_product(eager_load=False)
    if product is None:
        return None

    # Resolve the tenant's user for the preference + threshold lookup.
    user_id = await _resolve_active_user_id(db_manager, tenant_key)
    if not user_id:
        return None

    # Staleness + preference gate through the owning tuning service. The threshold
    # (count-based) and the manual-refresh reset both live in check_tuning_staleness
    # / apply_tuning_updates — this emitter only consumes the verdict.
    # TOCTOU guard: the product/user were fetched in earlier awaits and are
    # re-looked-up inside check_tuning_staleness. If either was deleted or the
    # product deactivated in between, that raise means "no active product to
    # review" — treat it as no-banner rather than letting it propagate.
    tuning_service = ProductTuningService(db_manager=db_manager, tenant_key=tenant_key)
    try:
        staleness = await tuning_service.check_tuning_staleness(product_id=str(product.id), user_id=user_id)
    except ResourceNotFoundError:
        return None
    if not staleness.get("enabled"):
        return None  # user turned the reminder off
    if not staleness.get("is_stale"):
        return None  # fewer than tuning_reminder_threshold projects since the last tune

    return {
        "product_id": str(product.id),
        "product_name": product.name,
        "projects_since_tune": int(staleness.get("projects_since_tune", 0) or 0),
    }


async def emit_context_tuning_due_banner(
    service: NotificationService,
    tenant_key: str,
    due: dict | None,
    *,
    tools_route: str,
) -> None:
    """Upsert or resolve the context-tuning-due banner for one tenant."""
    if due is None:
        await service.resolve_by_dedupe_key(tenant_key, CONTEXT_TUNING_DUE_DEDUPE_KEY)
        return

    count = due["projects_since_tune"]
    await service.upsert_by_dedupe_key(
        tenant_key=tenant_key,
        user_id=None,
        notification_type="system.context_tuning_due",
        severity="info",
        title="Time for a context review",
        body=(
            f"{due['product_name']} has had {count} project{'s' if count != 1 else ''} "
            "complete since its last context review — tune it so your agents stay current."
        ),
        dedupe_key=CONTEXT_TUNING_DUE_DEDUPE_KEY,
        surface="banner",
        role_filter=None,
        cta_label="Review context",
        cta_route=tools_route,
        dismissible=True,
        # No time-based resurface: a dismissed reminder returns only after the user
        # tunes (resolving it) and accumulates `threshold` more projects (BE-9218).
        resurface_after_hours=None,
        payload={
            "product_id": due["product_id"],
            "product_name": due["product_name"],
            "projects_since_tune": count,
        },
    )
