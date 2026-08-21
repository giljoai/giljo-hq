# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Tenant-ownership guard for the optional foreign keys on a thread (BE-9420).

Its own module for the same two reasons the chain-hub mixin has one.

The concern is distinct. ``CommThreadRepository`` is thread CRUD and the
baton/status queries the tool surface is built on. This is one ownership check
with a rule that needs more explanation than the query needs code.

And the size budget forced the seam, exactly as it did for BE-9291: the repository
sits under an 800-line cap with single-digit headroom, so a guard inlined there
would have pushed it over. Fighting for four lines is the signal that the shape is
wrong, not that the cap is.

Inherited by ``CommThreadRepository`` on the seam the chain-hub / directed-actions /
list-enrichment / participants mixins established, so the public repository API is
unchanged.

Tenant-scoped.
Edition Scope: CE.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import ValidationError


class CommThreadTenantRefsMixin:
    """Refuse a thread FK that names a row outside the tenant. Inherited by CommThreadRepository."""

    async def _require_owned_reference(
        self,
        session: AsyncSession,
        tenant_key: str,
        *,
        model: type,
        row_id: str,
        field: str,
    ) -> None:
        """Verify an optional FK names a row IN THIS TENANT before it is stored.

        ``product_id`` and ``project_id`` reach ``create_thread`` from an agent (the
        MCP tool) and from a browser (``POST /api/threads``), and both were written
        straight into the row. The FK constraint does not close that: ``products.id``
        and ``projects.id`` are globally unique rather than tenant-qualified, so
        ANOTHER tenant's real id satisfies the constraint and is stored silently as a
        cross-tenant reference. Measured before this guard existed, over the real MCP
        transport, on both columns.

        This is the same check ``_require_sequence_run`` already applies to the third
        FK on that constructor, for the reason its own docstring gives -- a supplied
        id is not a capability (ADR-009). Applying it to one of three foreign keys
        and not the other two was the gap; the guard is generic so the fourth cannot
        repeat it.

        Refuses rather than dropping the value to NULL. A silent fallback would
        report success while binding something the caller did not ask for, which is
        the failure mode BE-9411's resolver docstring calls out in as many words.

        The refusal deliberately does not distinguish "does not exist" from "belongs
        to someone else" -- telling an unauthorized caller which foreign ids are real
        would answer a question they are not entitled to ask.
        """
        owned = (
            await session.execute(select(model.id).where(model.tenant_key == tenant_key, model.id == row_id))
        ).scalar_one_or_none()
        if owned is None:
            raise ValidationError(
                f"{field} does not name a {model.__name__.lower()} in this workspace",
                context={"operation": "comm_thread.create", field: row_id},
            )
