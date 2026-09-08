# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
TaskService MCP-adapter mixin -- the agent-facing (@mcp.tool) task surface.

BE-9060 (item 3): the ~470-line MCP facade was mechanically split out of the
1552-line ``TaskService`` god-class into this mixin, mirroring the exact in-repo
precedent of the ``project_service`` package (``McpAdapterMixin``). The composed
``TaskService`` in the package ``__init__`` inherits from this mixin, so the public
import ``from giljo_mcp.services.task_service import TaskService`` and every
``task_service.create_task_for_mcp`` / ``update_task_for_mcp`` / ``list_tasks_for_mcp``
call site keep working unchanged. Behavior is unchanged -- these methods were
extracted verbatim.

Concerns owned here:
- ``create_task_for_mcp`` / ``update_task_for_mcp`` / ``list_tasks_for_mcp`` --
  the three agent-facing tool entry points (active-product resolution, TSK-tag
  forcing, summary/full projection modes).
- ``_list_tasks_for_mcp_impl`` + the ``_task_type_block`` / ``_task_to_summary_row``
  / ``_task_to_full_row`` projection helpers.

These methods reference base-class attributes/methods (``self.db_manager``,
``self.tenant_manager``, ``self._session``, ``self._logger``, ``self.log_task``,
``self.update_task``, ``self._get_session``, ``self._append_completion_notes``)
through ``self`` -- resolved across the MRO of the composed ``TaskService``.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from giljo_mcp.domain.task_status import VALID_TASK_STATUSES
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models import Task
from giljo_mcp.services._mcp_wire_bounds import worst_case_cursor_charge
from giljo_mcp.services.task_service._mcp_filter_validators import (
    resolve_active_product_for_list_tasks,
    resolve_list_mode,
    resolve_list_tasks_filters_and_cursor,
    resolve_task_type_id,
)
from giljo_mcp.services.task_service._mcp_read_layer import (
    TASK_CURSOR_AXIS,
    apply_bounds,
    apply_task_filters,
    mint_task_next_cursor,
    task_counts,
    task_keyset_after,
    task_to_index_row,
)
from giljo_mcp.tenant import current_tenant
from giljo_mcp.utils.taxonomy_alias import format_taxonomy_alias


_VALID_LIST_MODES = ("index", "summary", "full")


def _parse_due_date(value: Any, *, operation: str, field: str = "due_date", task_id: str = "") -> datetime:
    """TSK-9163/TSK-9177: the @mcp.tool wrappers deliver due_date (update_task)
    and due_before (list_tasks) as ISO 8601 STRINGS; unparsed they reach the
    DateTime(timezone=True) column as a str and asyncpg rejects the
    str-vs-timestamptz write/comparison as a generic internal error. Parse here —
    mirroring the REST path, where Pydantic's ``TaskUpdate.due_date: datetime``
    does the same conversion — and reject garbage as agent-actionable
    ValidationError, not a 500.
    """
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    context: dict[str, Any] = {"operation": operation}
    if task_id:
        context["task_id"] = task_id
    raise ValidationError(
        message=(
            f"Invalid {field} {value!r}. Pass an ISO 8601 date or datetime, "
            "e.g. '2026-07-15' or '2026-07-15T09:00:00+00:00'."
        ),
        context=context,
    )


class McpAdapterMixin:
    """MCP-tool task surface (create/update/list + row projections).

    Mixed into ``TaskService``; never instantiated on its own. All state comes
    from the composed base (see module docstring).
    """

    async def create_task_for_mcp(
        self,
        title: str,
        description: str,
        priority: str = "medium",
        task_type: str | None = None,
        assigned_to: str | None = None,
        product_id: str | None = None,
        tenant_key: str | None = None,
        db_manager: Any | None = None,
        websocket_manager: Any | None = None,
    ) -> dict[str, Any]:
        """Create a task via MCP tool (product binding + TSK tag).

        BE-6049c: tasks are now **TSK-only**. The ``task_type`` parameter is
        accepted for backward compatibility but **ignored** — every new task is
        force-assigned the reserved ``TSK`` tag (decoupled from the project
        taxonomy) and renders ``TSK-nnnn`` on the global serial line. The TSK
        row is ensured lazily + race-safe for the calling tenant.

        BE-9411: ``product_id`` is optional. Omitted, the task binds to the
        active product exactly as before. Supplied, it is validated as belonging
        to this tenant and the task binds there regardless of which product is
        active — so an active-product flip by another session or by the operator
        cannot steal the filing. See ``ProductService.resolve_binding_product``.
        """
        effective_tenant_key = tenant_key or self.tenant_manager.get_current_tenant()
        effective_db = db_manager or self.db_manager

        from giljo_mcp.services.product_service import ProductService
        from giljo_mcp.services.taxonomy_service import TaxonomyService

        product_service = ProductService(
            db_manager=effective_db,
            tenant_key=effective_tenant_key,
            websocket_manager=websocket_manager,
            test_session=self._session,
        )
        bound_product = await product_service.resolve_binding_product(product_id, operation="create_task", write=True)
        product_id = bound_product.id
        product_name = bound_product.name

        # BE-6049c: force the reserved TSK tag. ``ensure_reserved_task_type`` is
        # race-safe (INSERT ... ON CONFLICT DO NOTHING) so concurrent
        # first-task-creates for a tenant that predates TSK seeding cannot
        # collide. ``task_type`` is intentionally unused.
        taxonomy = TaxonomyService(db_manager=effective_db, session=self._session)
        reserved_type = await taxonomy.ensure_reserved_task_type(effective_tenant_key)
        task_type_id = reserved_type.id
        resolved_type_label = reserved_type.abbreviation

        # BE-5065/BE-6049b: shared global task+project series counter. Tasks are
        # always typed now (TSK), so every task draws a serial. ``log_task``
        # performs the lock + assign + insert inside one session so the FOR
        # UPDATE + advisory lock are held until the row is committed.
        assigned_series: list[int | None] = [None]
        task_id = await self.log_task(
            content=title,
            title=title,
            description=description,
            task_type_id=task_type_id,
            priority=priority,
            product_id=product_id,
            tenant_key=effective_tenant_key,
            assign_shared_series=True,
            _assigned_series_out=assigned_series,
        )

        self._logger.info(
            "Created task %s for tenant %s in product %s",
            task_id,
            effective_tenant_key,
            product_id,
        )

        if websocket_manager:
            try:
                await websocket_manager.broadcast_to_tenant(
                    tenant_key=effective_tenant_key,
                    event_type="task:created",
                    data={"task_id": task_id, "title": title, "product_id": product_id},
                )
            except (RuntimeError, ValueError, OSError) as e:
                self._logger.warning(f"Failed to broadcast task:created event: {e}")

        # BE-5065: surface taxonomy_alias (TSK-nnnn) to the MCP caller. Built
        # from the reserved abbreviation + the series_number assigned inside
        # log_task so we don't need a DB roundtrip (also keeps mock-friendly
        # tests happy when log_task is stubbed).
        taxonomy_alias = ""
        if assigned_series[0] is not None:
            taxonomy_alias = format_taxonomy_alias(resolved_type_label, assigned_series[0])

        return {
            "success": True,
            "task_id": task_id,
            "title": title,
            "priority": priority,
            "task_type": resolved_type_label,
            "taxonomy_alias": taxonomy_alias,
            "product_id": product_id,
            # BE-9411: name the landing, not just its id. An agent can then
            # self-check where a create actually went for one field read —
            # which is what the misfiling incident had no way to do.
            "product_name": product_name,
            "message": f"Task '{title}' created successfully",
        }

    async def update_task_for_mcp(
        self,
        task_id: str,
        tenant_key: str | None = None,
        title: str | None = None,
        description: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        task_type: str | None = None,
        due_date: Any = None,
        project_id: str | None = None,
        estimated_effort: float | None = None,
        actual_effort: float | None = None,
        hidden: bool | None = None,
        completion_notes: str | None = None,
        convert_to_project: bool = False,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Update a task via the MCP surface. Phase C; mirrors update_project.

        Only fields actually supplied (non-None) are written; the underlying
        ``update_task`` enforces the field allowlist (post-0962 write
        discipline). BE-6049c: tasks are TSK-only and the tag is IMMUTABLE —
        ``task_type`` is accepted for signature compatibility but ignored (it is
        not in the update allowlist), so passing it is a harmless no-op.

        BE-6225a: ``completion_notes`` folds in the retired ``complete_task``
        tool. When the task is being completed (``status == "completed"``) the
        note is appended to the description as a timestamped audit-trail entry
        (shared ``_append_completion_notes`` format, identical to the REST PATCH
        and the old complete_task path). A note without ``status="completed"``
        is a no-op — the audit entry only makes sense on completion.

        BE-9382: ``convert_to_project=True`` PROMOTES the task instead of editing
        it — the same atomic ``TaskConversionService.convert_to_project`` the
        dashboard's convert wizard drives through ``POST /tasks/{id}/convert``,
        with that endpoint's own request defaults (strategy="single",
        include_subtasks=True). The task row is hard-deleted by that flow, so the
        ONLY other field accepted alongside it is ``title``, which names the new
        project (the wizard's ``project_name`` field); any other supplied field
        would be written to a row that is about to disappear, so it is refused as
        a BE-6081 Tier-2 ``CONVERT_FIELD_CONFLICT`` before anything is written
        rather than silently discarded. ``task_type`` is exempt — it is
        accepted-but-ignored on every task tool by contract.
        """
        effective_tenant_key = tenant_key or self.tenant_manager.get_current_tenant()
        if not effective_tenant_key:
            raise ValidationError(
                message="tenant_key is required",
                context={"operation": "update_task_for_mcp", "task_id": task_id},
            )

        # BE-9382: promotion is a different operation, not an edit — it deletes the
        # row every other field would write to. Branch out BEFORE any of the update
        # path runs so a refused convert writes nothing at all.
        if convert_to_project:
            return await self._convert_task_for_mcp(
                task_id,
                effective_tenant_key,
                project_name=title,
                user_id=user_id,
                supplied={
                    "description": description,
                    "status": status,
                    "priority": priority,
                    "due_date": due_date,
                    "project_id": project_id,
                    "estimated_effort": estimated_effort,
                    "actual_effort": actual_effort,
                    "hidden": hidden,
                    "completion_notes": completion_notes,
                },
            )

        if status is not None and status not in VALID_TASK_STATUSES:
            valid_status_values = sorted(s.value for s in VALID_TASK_STATUSES)
            raise ValidationError(
                message=f"Unknown task status '{status}'. Valid statuses: {valid_status_values}",
                context={
                    "operation": "update_task_for_mcp",
                    "task_id": task_id,
                    "valid_statuses": valid_status_values,
                },
            )

        update_kwargs: dict[str, Any] = {}
        if title is not None:
            update_kwargs["title"] = title
        if description is not None:
            update_kwargs["description"] = description
        if status is not None:
            update_kwargs["status"] = status
        if priority is not None:
            update_kwargs["priority"] = priority
        if due_date is not None:
            update_kwargs["due_date"] = _parse_due_date(due_date, operation="update_task_for_mcp", task_id=task_id)
        if project_id is not None:
            update_kwargs["project_id"] = project_id
        if estimated_effort is not None:
            update_kwargs["estimated_effort"] = estimated_effort
        if actual_effort is not None:
            update_kwargs["actual_effort"] = actual_effort
        if hidden is not None:
            if not isinstance(hidden, bool):
                raise ValidationError(
                    message="hidden must be a boolean",
                    context={"operation": "update_task_for_mcp", "task_id": task_id},
                )
            update_kwargs["hidden"] = hidden

        # BE-6049c: task_type is intentionally NOT resolved/written — the TSK tag
        # is immutable (task_type_id is not in _ALLOWED_TASK_UPDATE_FIELDS), so a
        # supplied task_type is a no-op rather than a hard error.

        # BE-6225a: completion_notes only append on completion. A note alone (no
        # status="completed") is nothing to do, mirroring the no-fields case.
        will_append_notes = bool(completion_notes) and status == "completed"

        if not update_kwargs and not will_append_notes:
            return {
                "task_id": task_id,
                "updated_fields": [],
                "message": "No fields supplied; nothing to update.",
            }

        # Route through update_task; it owns the allowlist and timestamp logic.
        # update_task pulls tenant from tenant_manager — set it explicitly so
        # tenant_key parameter wins on the MCP-tool path.
        # Capture the token and reset() to the exact prior value (BE6004C-1):
        # the old set(previous) restore skipped restoring when previous was None,
        # leaving effective_tenant_key on the context — a cross-tenant leak.
        updated_fields: list[str] = []
        if update_kwargs:
            tenant_token = None
            if self.tenant_manager:
                tenant_token = self.tenant_manager.set_current_tenant(effective_tenant_key)
            try:
                result = await self.update_task(task_id, **update_kwargs)
            finally:
                if tenant_token is not None:
                    current_tenant.reset(tenant_token)
            updated_fields = list(result.updated_fields)

        # BE-6225a: append the audit-trail note AFTER the status write commits, so
        # the completed task carries the note exactly as the retired complete_task
        # tool did. Shares the single _append_completion_notes format with the
        # REST PATCH path (tenant-explicit; no new column).
        response: dict[str, Any] = {
            "task_id": task_id,
            "updated_fields": updated_fields,
            "message": f"Task {task_id} updated: {sorted(updated_fields)}",
        }
        if will_append_notes:
            await self._append_completion_notes(task_id, effective_tenant_key, completion_notes)
            response["completion_notes"] = completion_notes
        return response

    async def _convert_task_for_mcp(
        self,
        task_id: str,
        tenant_key: str,
        *,
        project_name: str | None,
        user_id: str | None,
        supplied: dict[str, Any],
    ) -> dict[str, Any]:
        """Promote a task to a project through the UI's own conversion path (BE-9382).

        ``supplied`` holds every OTHER task field the caller passed; a non-None
        value there is refused (see ``update_task_for_mcp``). Delegates to
        ``TaskConversionService.convert_to_project`` — one atomic scope that
        inserts the project, re-points subtasks and any roadmap card, and deletes
        the task — with the REST convert endpoint's request defaults, so the
        headless door and the dashboard door cannot drift apart.

        BE-9415: the new project binds to the TASK's product, never to whichever
        product is active, and the response echoes ``product_id``/``product_name``
        so a caller can see where the promotion landed (BE-9411's contract).
        """
        conflicting = sorted(name for name, value in supplied.items() if value is not None)
        if conflicting:
            return {
                "success": False,
                "error": "CONVERT_FIELD_CONFLICT",
                "task_id": task_id,
                "conflicting_fields": conflicting,
                "message": (
                    f"convert_to_project deletes the task row, so {conflicting} cannot be written in "
                    "the same call — they would be silently discarded. Nothing was changed. Either "
                    "convert on its own (pass only convert_to_project=true, plus title to name the "
                    "new project), or update those fields first and convert in a second call. To "
                    "record an outcome instead of promoting, drop convert_to_project and pass "
                    "status='completed'."
                ),
            }

        if not user_id:
            return {
                "success": False,
                "error": "USER_CONTEXT_REQUIRED",
                "task_id": task_id,
                "message": (
                    "Converting a task to a project runs as the authenticated user (only the task's "
                    "creator or an admin may convert), but this session's credential carries no user "
                    "identity. Nothing was changed. Re-connect with a current MCP key, or convert the "
                    "task from the dashboard."
                ),
            }

        # convert_to_project reads the tenant off the manager; set it explicitly so
        # the tenant_key argument wins on the MCP path, and reset() to the exact
        # prior value (BE6004C-1 — a plain set(previous) leaked when previous was None).
        tenant_token = None
        if self.tenant_manager:
            tenant_token = self.tenant_manager.set_current_tenant(tenant_key)
        try:
            result = await self.convert_to_project(
                task_id=task_id,
                # None keeps the task's own title, exactly like the wizard's empty
                # project_name field.
                project_name=project_name,
                # The REST endpoint's TaskConversionRequest defaults, verbatim: the
                # dashboard posts an empty body and gets these.
                strategy="single",
                include_subtasks=True,
                user_id=user_id,
            )
        finally:
            if tenant_token is not None:
                current_tenant.reset(tenant_token)

        alias = result.project_taxonomy_alias or ""
        self._logger.info(
            "Promoted task %s to project %s for tenant %s via MCP",
            task_id,
            result.project_id,
            tenant_key,
        )
        return {
            "success": True,
            "converted_to_project": True,
            "task_id": task_id,
            # Stated three ways on purpose: an agent that keeps using the task_id
            # after this call is the failure mode this response has to prevent.
            "task_deleted": True,
            "task_exists": False,
            "project_id": result.project_id,
            "project_name": result.project_name,
            "taxonomy_alias": alias,
            # BE-9415: the promotion binds to the TASK's product, not the ambient
            # active one. Naming the landing here is what lets an agent self-check
            # the filing -- the same echo BE-9411 added to the create responses.
            "product_id": result.product_id,
            "product_name": result.product_name,
            "project_status": "inactive",
            "project_type": None,
            "updated_fields": [],
            "message": (
                f"Task {task_id} was PROMOTED to project {result.project_id}"
                f"{f' ({alias})' if alias else ''} and the task row was DELETED — that task_id no "
                "longer resolves, and list_tasks will not return it. Subtasks and any roadmap card "
                "now point at the project (same roadmap position). The project is INACTIVE and "
                "UNTYPED: give it a taxonomy with update_project(project_id=..., "
                "project_type='BE'|'FE'|...), and the user activates or launches it from the "
                "dashboard."
            ),
        }

    async def list_tasks_for_mcp(
        self,
        tenant_key: str | None = None,
        mode: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        task_type: str | None = None,
        due_before: Any = None,
        summary_only: bool | None = None,
        memory_limit: int | None = None,
        hidden: bool | None = None,
        limit: int | None = None,
        query: str | None = None,
        # BE-9469: the opaque continuation token from a previous response's
        # truncation.next_cursor. Absent = start at the first page, byte-identical to
        # the shipped behaviour.
        cursor: str | None = None,
        # BE-9499a: explicit product to scope to, validated as tenant-owned. Omitted
        # -> the active product, byte-identical to pre-existing behaviour.
        product_id: str | None = None,
    ) -> dict[str, Any]:
        """List tasks for the active product, or an explicit product_id, bounded and honest about it.

        Phase D of agent-parity. Three projection modes:

        - ``index``: the lean list-and-sort row — task_id, taxonomy_alias, name,
          status, type, due_date, created_at. No description, no enrichment, and
          no embedded task_type block (see ``task_to_index_row``). Measured at
          37.7% fewer characters than ``summary`` on the same rows.
        - ``summary``: id, title, status, priority, task_type, due_date,
          created_at, taxonomy_alias, series_number, subseries, hidden,
          embedded task_type block.
        - ``full``: the full projection of Task columns (see
          ``_task_to_full_row``) plus an embedded task_type block.
          ``memory_limit`` truncates description if set.

        BE-9470: an explicit ``mode`` wins over the legacy ``summary_only`` flag
        (copied from ``list_projects``'s mode-vs-depth precedence). ``summary_only``
        still governs when ``mode`` is omitted entirely — it is the documented alias
        for callers who pass only it.

        Filters: status, priority, task_type, due_before, hidden, and ``query``
        (case-insensitive substring over title, description and taxonomy_alias —
        the cheapest path from "the OAuth one" to a single id). BE-9470: task_type
        accepts ONLY the reserved 'TSK' tag — every task carries it and no other
        type is ever assigned to a task (see ``validate_task_type_filter``) — so
        'TSK' is a harmless no-op filter and any other value is refused rather than
        silently matching nothing.

        BE-9468: the list is BOUNDED. Before this it had no bound of any kind —
        no row cap, no size cap, no truncation signal — so a call could return
        the whole corpus and the caller could not tell. Two bounds now apply and
        both announce themselves through the SHIPPED ``truncated`` /
        ``truncation`` vocabulary (BE-9455 Symptom A), never a second one:

        - ``limit`` (default ``LIST_TASKS_LIMIT_DEFAULT``, max
          ``LIST_TASKS_LIMIT_MAX``) — asking for everything stays possible, it
          just stops being the accidental default;
        - a response-size ceiling in characters, enforced by dropping whole
          ROWS. At ``mode='full'`` this is the only bound that means anything,
          because ``description`` is untruncated unless ``memory_limit`` is
          passed and one row is therefore arbitrarily large.

        Both bounds are backward compatible: every new parameter is optional,
        every new response key is additive, and a board under the default comes
        back exactly as it did before with ``truncated: False`` added.

        BE-6077: every query is scoped to BOTH tenant_key AND the active
        product (Task.product_id is NOT NULL), mirroring list_projects_for_mcp.
        Cross-tenant and cross-product tasks are never visible. Raises
        ValidationError when no active product is set.

        FE-5046: The 'hidden' field is per-row UI declutter and does NOT
        affect default visibility -- agents see hidden and non-hidden alike.
        Pass hidden=true|false to filter explicitly when needed (rare).
        """
        effective_tenant_key = tenant_key or self.tenant_manager.get_current_tenant()
        if not effective_tenant_key:
            raise ValidationError(
                message="tenant_key is required",
                context={"operation": "list_tasks_for_mcp"},
            )

        # BE-6077 / BE-9470: scope to the active product -- see
        # resolve_active_product_for_list_tasks for why and for the caller
        # that used to see the whole tenant's task corpus without this.
        active_product = await resolve_active_product_for_list_tasks(
            db_manager=self.db_manager,
            websocket_manager=self._websocket_manager,
            session=self._session,
            tenant_key=effective_tenant_key,
            product_id=product_id,
        )

        # Projection mode -- resolved here (not delegated) so this module keeps a
        # direct import of resolve_list_mode -- test_be9060_task_service_split pins
        # that. BE-9470: an explicit mode now WINS over summary_only (copied from
        # list_projects); summary_only still wins when mode is omitted, which is
        # what keeps every pre-mode caller byte-identical.
        mode = resolve_list_mode(mode, summary_only, _VALID_LIST_MODES)

        # TSK-9177: the @mcp.tool wrapper delivers due_before as an ISO string;
        # parse at the boundary (same class as TSK-9163) so the impl compares
        # datetime-vs-timestamptz instead of str-vs-timestamptz.
        if due_before is not None:
            due_before = _parse_due_date(due_before, operation="list_tasks_for_mcp", field="due_before")

        # BE-9470 (finding 5): task_type's only legal value is the reserved 'TSK'
        # tag -- see resolve_task_type_id / validate_task_type_filter for why. Also
        # resolved here directly -- test_be9060_task_service_split pins this import too.
        task_type_id = await resolve_task_type_id(
            task_type, db_manager=self.db_manager, session=self._session, tenant_key=effective_tenant_key
        )

        effective_limit, priority, cursor_fingerprint, after_key = resolve_list_tasks_filters_and_cursor(
            limit=limit,
            status=status,
            priority=priority,
            task_type_id=task_type_id,
            due_before=due_before,
            hidden=hidden,
            query=query,
            cursor=cursor,
            product_id=active_product.id,
        )

        async with self._get_session(effective_tenant_key) as session:
            tasks = await self._list_tasks_for_mcp_impl(
                session,
                effective_tenant_key,
                product_id=active_product.id,
                after_key=after_key,
                status=status,
                priority=priority,
                task_type_id=task_type_id,
                due_before=due_before,
                hidden=hidden,
                query=query,
                # Fetch ONE past the limit. That extra row is how we learn whether
                # anything was withheld without paying for a second COUNT query, and
                # it is discarded below -- the caller never sees it.
                limit=effective_limit + 1,
            )
            counts = await task_counts(
                session,
                effective_tenant_key,
                product_id=active_product.id,
                status=status,
                priority=priority,
                task_type_id=task_type_id,
                due_before=due_before,
                hidden=hidden,
                query=query,
                after_key=after_key,
            )

        limit_cut = len(tasks) > effective_limit
        tasks = tasks[:effective_limit]

        if mode == "index":
            rows = [task_to_index_row(t) for t in tasks]
        elif mode == "summary":
            rows = [self._task_to_summary_row(t) for t in tasks]
        else:
            rows = [self._task_to_full_row(t, memory_limit=memory_limit) for t in tasks]

        response: dict[str, Any] = {
            "tasks": rows,
            "count": len(rows),
            "mode": mode,
            "tenant_key": effective_tenant_key,
            "counts": counts,
            "product_id": active_product.id,
        }
        # The counts block is inside the response BEFORE the size budget is charged, so
        # it is paid for out of the ceiling rather than added on top of it.
        apply_bounds(
            response,
            rows,
            limit_cut=limit_cut,
            effective_limit=effective_limit,
            # Minted by apply_bounds AFTER its size cut, because the token must name the
            # last row actually delivered. The charge is an upper-bound placeholder so the
            # ceiling is charged for the token the response will carry.
            cursor_charge=worst_case_cursor_charge(TASK_CURSOR_AXIS, cursor_fingerprint),
            mint_cursor=lambda kept: mint_task_next_cursor(
                returned_rows=kept, fetched_rows=tasks, fingerprint=cursor_fingerprint
            ),
            mode=mode,
        )
        # ASSIGNED, never recomputed, and only after the size backstop has settled the
        # final row count. ``count`` is the shipped key and keeps its shipped meaning;
        # ``counts.returned`` mirrors it inside the block so all three numbers sit
        # together and none of them means something different depending on the call.
        counts["returned"] = response["count"]
        return response

    async def _list_tasks_for_mcp_impl(
        self,
        session: AsyncSession,
        tenant_key: str,
        *,
        product_id: str,
        status: str | None,
        priority: str | None,
        task_type_id: str | None,
        due_before: Any,
        hidden: bool | None = None,
        query: str | None = None,
        limit: int | None = None,
        after_key: tuple[Any, str] | None = None,
    ) -> list[Task]:
        stmt = (
            select(Task)
            .options(selectinload(Task.task_type))
            .where(Task.tenant_key == tenant_key)
            .where(Task.product_id == product_id)
            .where(Task.deleted_at.is_(None))  # BE-6130b: exclude trashed tasks
            # BE-9468: ``id`` is a unique TIEBREAK, not decoration. ``created_at``
            # defaults to ``func.now()``, and PostgreSQL's ``now()`` is
            # TRANSACTION-scoped, so every task created in one transaction carries a
            # byte-identical timestamp. Ordering by ``created_at`` alone leaves those
            # rows in an arbitrary order, which did not matter while this list was
            # unbounded and every row came back regardless. Adding ``limit`` is what
            # makes it matter: without the tiebreak, WHICH of the tied rows falls
            # outside the limit can differ between two identical calls, so a caller
            # paging or re-reading sees rows appear and vanish with nothing changed.
            #
            # ⚠ THIS ORDERING AND THE TRUNCATION MESSAGE MUST CHANGE TOGETHER.
            # Both bounds drop from the TAIL, and ``DROPPED_TASKS`` in ``_mcp_read_layer``
            # tells the caller that what it lost was "the OLDEST-CREATED tasks". That
            # sentence is true only because of the ``created_at DESC`` here. There is no
            # sort parameter on this tool today, so it holds -- but add one, or reverse
            # this, and the truncation block starts telling an agent something false
            # about which rows are missing, with every test still passing. A cut is a
            # claim about what was discarded; the claim lives here, not in the string.
            .order_by(Task.created_at.desc(), Task.id.asc())
        )
        stmt = apply_task_filters(
            stmt,
            status=status,
            priority=priority,
            task_type_id=task_type_id,
            due_before=due_before,
            hidden=hidden,
            query=query,
        )
        if after_key is not None:
            # BE-9469: the continuation position, applied in SQL BEFORE the limit so each
            # page fetches the next window FROM the cursor. See _mcp_read_layer for why
            # it is an explicit OR and not a row-value comparison.
            stmt = stmt.where(task_keyset_after(*after_key))
        if limit is not None:
            stmt = stmt.limit(limit)

        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    def _task_type_block(task: Task) -> dict[str, Any] | None:
        if not task.task_type:
            return None
        return {
            "id": task.task_type.id,
            "abbreviation": task.task_type.abbreviation,
            "label": task.task_type.label,
            "color": task.task_type.color,
        }

    @classmethod
    def _task_to_summary_row(cls, task: Task) -> dict[str, Any]:
        # FE-5046: summary now mirrors Project parity -- taxonomy_alias,
        # series_number, subseries, embedded task_type block, hidden.
        return {
            "task_id": str(task.id),
            "title": task.title,
            "status": task.status,
            "priority": task.priority,
            "task_type": cls._task_type_block(task),
            "taxonomy_alias": task.taxonomy_alias or "",
            "series_number": task.series_number,
            "subseries": task.subseries,
            "hidden": bool(task.hidden),
            "due_date": task.due_date.isoformat() if task.due_date else None,
            "created_at": task.created_at.isoformat() if task.created_at else None,
        }

    @classmethod
    def _task_to_full_row(cls, task: Task, *, memory_limit: int | None) -> dict[str, Any]:
        description = task.description or ""
        if memory_limit and len(description) > memory_limit:
            description = description[:memory_limit] + "..."
        return {
            "task_id": str(task.id),
            "title": task.title,
            "description": description,
            "status": task.status,
            "priority": task.priority,
            "task_type": cls._task_type_block(task),
            "taxonomy_alias": task.taxonomy_alias or "",
            "series_number": task.series_number,
            "subseries": task.subseries,
            "hidden": bool(task.hidden),
            "task_type_id": task.task_type_id,
            "product_id": task.product_id,
            "project_id": task.project_id,
            "parent_task_id": task.parent_task_id,
            "estimated_effort": task.estimated_effort,
            "actual_effort": task.actual_effort,
            "due_date": task.due_date.isoformat() if task.due_date else None,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "created_at": task.created_at.isoformat() if task.created_at else None,
        }
