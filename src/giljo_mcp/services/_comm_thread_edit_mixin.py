# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.schemas.comm_serializers import thread_dict


_SUBJECT_MAX = 255


class CommThreadEditMixin:

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
