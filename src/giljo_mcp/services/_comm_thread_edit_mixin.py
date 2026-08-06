# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Operator edits of a thread — rename and status (BE-9289b).

Two capabilities the operator did not have. A thread could only be named at CREATE
time, which is the top complaint about the Hub; and ``status`` was reachable only as a
side effect of an agent posting, which is why the operator's list is a wall of stale
"Open".

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
    """Thread rename + operator-set status. Mixed into CommThreadService."""

    async def update_thread(
        self,
        *,
        thread_id: str,
        subject: str | None = None,
        status: str | None = None,
        settable_statuses: tuple[str, ...] = ("open", "active", "resolved", "closed"),
        tenant_key: str | None = None,
    ) -> dict[str, Any]:
        """Rename a thread and/or set its status. Returns the updated thread dict.

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
        """
        tk = self._resolve_tenant(tenant_key)
        if subject is None and status is None:
            raise ValidationError(
                "Nothing to update: pass a subject and/or a status.",
                context={"operation": "comm_thread.update", "thread_id": thread_id},
            )
        if status is not None and status not in settable_statuses:
            raise ValidationError(
                f"status must be one of {settable_statuses}, got '{status}'.",
                context={"operation": "comm_thread.update", "status": status},
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
            await session.flush()
            return thread_dict(thread)
