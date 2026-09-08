# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Operator edits of a thread — rename, status, product + project tags (BE-9289b, FE-9530).

Four capabilities the operator did not have. A thread could only be named at CREATE
time, which is the top complaint about the Hub; ``status`` was reachable only as a
side effect of an agent posting, which is why the operator's list is a wall of stale
"Open"; and — FE-9530 — a thread's ``product_id`` could only be set at create time,
which combined with "no migration" meant every thread that
predates mandatory product tagging would be untaggable FOREVER. This is that fix:
retagging happens here, on touch, rather than via a bulk migration nobody asked for.

Lives in its own module rather than on ``CommThreadService`` because that module is
pinned at its shrink-only size budget — the same reason ``comm_serializers`` and
``comm_author_identity`` were split out. Mixed into ``CommThreadService``, so it uses
that class's session/tenant plumbing (``_resolve_tenant``, ``_scoped_session``,
``_require_thread``) and the public API is unchanged.

Edition Scope: CE.
"""

from __future__ import annotations

from typing import Any

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.schemas.comm_serializers import thread_dict


# Mirrors the ``comm_threads.subject`` column width, enforced here at the owning
# service so the column never receives unbounded operator input.
_SUBJECT_MAX = 255


class CommThreadEditMixin:
    """Thread rename + operator-set status + product/project tags. Mixed into CommThreadService."""

    async def update_thread(
        self,
        *,
        thread_id: str,
        subject: str | None = None,
        status: str | None = None,
        product_id: str | None = None,
        clear_product: bool = False,
        project_ids: list[str] | None = None,
        settable_statuses: tuple[str, ...] = ("open", "active", "resolved", "closed"),
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
        """Rename a thread, set its status, and/or retag its product/projects.

        Returns the updated thread dict (``project_ids`` always freshly read, even
        when this call didn't touch tags, so the response is never stale).

        RENAME IS REFUSED ON A PROJECT-BOUND THREAD, deliberately and readably. Such a
        thread is named after its project and is kept with that project's 360 memory, so
        a divergent chat title would misrepresent the archive. The refusal is a clean
        validation error carrying the reason and the alternative — never a 500, and
        never a silent no-op that leaves the operator thinking the rename worked.

        This does NOT touch ``BOUND_THREAD_MARKER_SUBJECT`` semantics. That marker is
        load-bearing resolution machinery (``resolve_or_create_bound_thread`` orders on
        it and the ce_0072 fold replicates that precedence), and any thread carrying it
        is project-bound — so it is exactly the case this refuses. The stored subject is
        never rewritten by this method for a bound thread; only the API's *display*
        title is derived elsewhere.

        Status has no such restriction: resolving or closing a project thread is a
        normal operator action and says nothing about the project's identity.

        ``product_id`` (FE-9530): ``None`` (the default) leaves the thread's product
        untouched. Pass a UUID to set/change it (validated tenant-owned, mirroring
        ``create_thread``'s own guard — a supplied id is not a capability). Pass
        ``clear_product=True`` to explicitly null it back out to genuinely
        product-less; ``product_id`` and ``clear_product=True`` together are refused
        as contradictory rather than silently picking one.

        ``project_ids`` (FE-9530, ruling 3 — plural, optional): ``None`` leaves the
        thread's project TAGS untouched (the ``comm_thread_project_tags`` table, NOT
        the single lifecycle-bound ``project_id`` column, which this method never
        writes). An empty list ``[]`` clears every tag. A non-empty list FULL-REPLACES
        the tag set; each id is validated tenant-owned before anything is written.
        """
        tk = self._resolve_tenant(tenant_key)
        if subject is None and status is None and product_id is None and not clear_product and project_ids is None:
            raise ValidationError(
                "Nothing to update: pass a subject, status, product_id/clear_product, and/or project_ids.",
                context={"operation": "comm_thread.update", "thread_id": thread_id},
            )
        if status is not None and status not in settable_statuses:
            raise ValidationError(
                f"status must be one of {settable_statuses}, got '{status}'.",
                context={"operation": "comm_thread.update", "status": status},
            )
        if product_id and clear_product:
            raise ValidationError(
                "product_id and clear_product=True are contradictory — pass one or the other.",
                context={"operation": "comm_thread.update", "thread_id": thread_id},
            )

        cleaned_subject: str | None = None
        if subject is not None:
            cleaned_subject = subject.strip()
            if not cleaned_subject:
                raise ValidationError(
                    "subject cannot be blank — a nameless thread is what this feature exists to fix.",
                    context={"operation": "comm_thread.update", "thread_id": thread_id},
                )
            if len(cleaned_subject) > _SUBJECT_MAX:
                raise ValidationError(
                    f"subject must be {_SUBJECT_MAX} characters or fewer.",
                    context={"operation": "comm_thread.update", "subject_len": len(cleaned_subject)},
                )

        async with self._scoped_session(tk) as session:
            thread = await self._require_thread(session, tk, thread_id)
            if cleaned_subject is not None:
                if thread.project_id:
                    raise ValidationError(
                        "This thread belongs to a project, so it takes its name from that project "
                        "and is kept with the project's 360 memory — it cannot be renamed here. "
                        "Rename the project instead, or start a separate thread for this topic.",
                        context={
                            "operation": "comm_thread.update",
                            "thread_id": thread_id,
                            "project_id": thread.project_id,
                        },
                    )
                thread.subject = cleaned_subject
            if status is not None:
                thread.status = status
            if product_id:
                # BE-9420-style guard: a supplied id is not a capability. Reuses the
                # exact check create_thread applies to the same column, via the
                # repository it already lives on (CommThreadTenantRefsMixin).
                from giljo_mcp.models.products import Product

                await self._repo._require_owned_reference(
                    session, tk, model=Product, row_id=product_id, field="product_id"
                )
                thread.product_id = product_id
            elif clear_product:
                thread.product_id = None
            if project_ids is not None:
                await self._repo.set_project_tags(session, tk, thread_id, project_ids)
            await session.flush()
            tags = await self._repo.get_project_tags(session, tk, thread_id)
            return thread_dict(thread, extra_project_ids=tags)
