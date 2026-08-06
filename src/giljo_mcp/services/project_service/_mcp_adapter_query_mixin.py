# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""MCP-tool list/projection adapter mixin for ProjectService (BE-6005 split).

Holds the agent-facing READ path extracted from ``McpAdapterMixin`` to keep that
module under the 800-line guardrail: ``list_projects_for_mcp`` (server-side
filtering + projection) and its projection helpers ``_build_mcp_project_list`` /
``_log_payload_size_breakdown``, plus the module-level helpers they exclusively
use (``_parse_iso_datetime`` and the ceiling / forensic-cap constants). Composed
into ``ProjectService`` alongside ``McpAdapterMixin``; references ``self.*`` only
and resolves shared class attributes (``_VALID_*`` / ``_MODE_TO_PROJECTION`` /
``_MEMORY_LIMIT_CAP``) and helpers (``_get_valid_project_types`` /
``_extract_git_commits`` / ``self.query`` / ``self.list_projects``) via the MRO.
Behavior is byte-identical to the pre-split single-file mixin.
"""

import logging
from datetime import datetime
from typing import Any

from giljo_mcp.domain.project_status import (
    LIFECYCLE_FINISHED_STATUSES,
    ProjectStatus,
)
from giljo_mcp.exceptions import ValidationError


logger = logging.getLogger(__name__)

# BE-6071 F6a: defensive ceiling on the agent-facing project list. This is a
# SAFETY CAP, not pagination — it bounds a pathological all-tenant fan-out
# without changing normal behavior (a tenant with <1000 active projects sees
# the identical list). Newest-first is applied by the repo's limit fallback
# order (created_at DESC). A warning is logged if the ceiling is ever hit so
# truncation is observable rather than silent.
_MCP_LIST_PROJECT_CEILING = 1000

# BE-6071 F6c: hard cap on the per-project message history serialized in the
# depth>=3 (forensic) projection. Forensic mode is an operator deep-dive; a
# most-recent window is acceptable and de-fangs the historic 63K-overflow.
_FORENSIC_MESSAGE_CAP = 200


def _parse_iso_datetime(value: Any) -> datetime | None:
    """Parse an ISO-8601 string into a tz-aware datetime; pass-through if already a datetime.

    Returns None for falsy/unparseable input. Naive datetimes are coerced to UTC
    so callers can compare against tz-aware boundary values without surprises.
    """
    from datetime import UTC

    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str):
        return None
    try:
        # datetime.fromisoformat handles "2026-01-01T00:00:00+00:00"; the trailing
        # "Z" form is normalized below. Be defensive in case older inputs slip through.
        normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
        dt = datetime.fromisoformat(normalized)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None


def _resolve_inner_status(
    status_list: list[str] | None,
    include_completed: bool,
    has_completion_filter: bool = False,
) -> str | list[str] | None:
    """SQL-side status filter for the agent list (Seq 161 / IMP-5036 pushdown).

    - explicit ``status`` -> pushed to the repo IN clause (single value or list);
    - ``include_completed`` -> ``None`` so the repo's bare-tenant path keeps the
      archived buckets (cancelled+completed) visible (include_cancelled=True);
    - default agent view -> the lifecycle-ACTIVE complement, excluding every
      lifecycle-finished state (completed/cancelled/terminated/deleted/superseded)
      at the SQL boundary instead of post-fetch.

    BE-9343 (audit F2) -- ``has_completion_filter`` (a ``completed_after`` /
    ``completed_before`` bound was supplied) implies ``include_completed``. A
    completion-date filter is an unambiguous request for FINISHED projects, but
    without this the default branch below excluded every completed project at the
    SQL boundary, so the query returned the projects NOT marked completed and
    dropped the ones that were. Before BE-9343 that returned nothing (every
    ``completed_at`` was NULL), which reads as "nothing found"; after the backfill
    it would have returned an INVERTED set, which reads as an answer -- the worse
    failure of the two, and the reason this is fixed at the mechanism rather than
    documented. An explicit ``status`` still wins, so
    ``list_projects(status="active", completed_after=X)`` keeps its narrow filter.

    Reachable by design: ``template_seeder.py`` seeds the orchestrator's
    duplicate/continuation check with ``completed_after`` and marks
    ``include_completed`` optional, so omitting it is documented-normal.
    """
    if status_list is not None:
        return status_list[0] if len(status_list) == 1 else status_list
    if include_completed or has_completion_filter:
        return None
    return sorted({s.value for s in ProjectStatus} - {s.value for s in LIFECYCLE_FINISHED_STATUSES})


class McpAdapterQueryMixin:
    """Agent-facing MCP list + projection path. Composed into ProjectService alongside McpAdapterMixin."""

    async def list_projects_for_mcp(
        self,
        status_filter: str | None = None,  # legacy param (kept for back-compat)
        summary_only: bool = True,
        depth: int = 0,
        tenant_key: str | None = None,
        websocket_manager: Any | None = None,
        # v1.2.1 server-side filtering surface
        status: str | list[str] | None = None,
        project_type: str | list[str] | None = None,
        taxonomy_alias_prefix: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        completed_after: datetime | None = None,
        completed_before: datetime | None = None,
        include_completed: bool = False,
        include_superseded: bool = False,
        hidden: bool | None = None,
        # BE-5042 agent-facing projection mode
        mode: str | None = None,
        memory_limit: int | None = None,
    ) -> dict[str, Any]:
        """List projects via MCP tool with server-side filtering (v1.2.1).

        Default returns only projects in active lifecycle (excludes completed,
        cancelled). The `hidden` field is a per-row UI declutter flag and does
        NOT affect default visibility -- agents see hidden and non-hidden alike.
        Pass include_completed=True to retrieve archived (completed/cancelled)
        projects. Pass hidden=True|False to filter by visibility explicitly.

        BE-9157: ``superseded`` projects (work replaced by a successor) are hidden
        by default -- even under include_completed=True. ``include_superseded=True``
        or an explicit ``status="superseded"`` surfaces them.

        Combination semantics: different fields AND together; multi-value
        within a field ORs together.

        BE-5042 — projection ``mode`` (agent-facing surface):
            ``triage`` (~depth 0), ``planning`` (~depth 1), ``audit``
            (~depth 2 with memory headlines + agent summaries, default last 5
            memory entries), ``forensic`` (~depth 3, full bodies, no cap).
            ``mode`` wins over numeric ``depth`` when both are passed; numeric
            ``depth`` stays as a back-compat path. ``memory_limit`` (default 5,
            cap 50) tunes audit; forensic ignores the cap unless overridden.

        Legacy ``status_filter`` kwarg (kept for back-compat with pre-v1.2.1
        callers) has narrower exclusion semantics than the new ``status``
        read-side kwarg. ``status_filter`` is validated against
        ``_VALID_STATUS_FILTERS``, which is derived from
        ``_DOMAIN_VALID_UPDATE_STATUSES`` plus the ``"all"`` sentinel — this
        deliberately **excludes ``terminated`` and ``deleted``** because those
        are lifecycle-only terminal states never set via update_project. A
        legacy caller passing ``status_filter="terminated"`` or
        ``status_filter="deleted"`` will hit ``ValidationError``. To query
        terminated/deleted projects, use the new ``status`` kwarg (validated
        against the broader ``_VALID_FILTER_STATUSES`` read-side set). The
        ``status_filter="all"`` sentinel sets ``include_completed=True`` to
        preserve pre-v1.2.1 archived-visible behavior; it does NOT include
        terminated/deleted. New code MUST use ``status`` directly.
        """
        # ----- Legacy status_filter back-compat -----
        # Existing callers pass status_filter ("all" | status). When the new
        # `status` kwarg is omitted, honor the legacy param. New callers
        # should use `status` directly.
        if status is None and status_filter is not None:
            if status_filter not in self._VALID_STATUS_FILTERS:
                raise ValidationError(
                    f"Invalid status_filter '{status_filter}'. "
                    f"Must be one of: {', '.join(sorted(self._VALID_STATUS_FILTERS))}",
                    context={"operation": "list_projects"},
                )
            if status_filter == "all":
                # Legacy "all" implies the user wants archived projects too --
                # preserve pre-v1.2.1 behavior for callers still using the old kwarg.
                include_completed = True
            else:
                status = status_filter
        if not isinstance(depth, int) or depth not in self._VALID_DEPTH_LEVELS:
            raise ValidationError(
                f"Invalid depth '{depth}'. Must be an integer 0-3.",
                context={"operation": "list_projects"},
            )

        # BE-5042: mode is the agent-facing surface; translate to internal
        # (depth, headlines, memory_limit). When both mode and numeric depth
        # are passed, mode wins.
        headlines = False
        resolved_memory_limit: int | None = None
        if mode is not None:
            if mode not in self._MODE_TO_PROJECTION:
                raise ValidationError(
                    f"Invalid mode '{mode}'. Must be one of: {', '.join(sorted(self._MODE_TO_PROJECTION))}.",
                    context={"operation": "list_projects", "mode": mode},
                )
            depth, headlines, default_limit = self._MODE_TO_PROJECTION[mode]
            # Mode implies a full projection pass; override summary_only=True default.
            summary_only = False
            if mode == "audit":
                effective_limit = memory_limit if memory_limit is not None else default_limit
                resolved_memory_limit = min(effective_limit, self._MEMORY_LIMIT_CAP)
            elif mode == "forensic":
                # Forensic has no default cap; honor an explicit caller override.
                resolved_memory_limit = min(memory_limit, self._MEMORY_LIMIT_CAP) if memory_limit is not None else None
            else:
                resolved_memory_limit = default_limit

        # ----- Normalize status to list[str] | None -----
        status_list: list[str] | None = None
        if status is not None:
            status_list = [status] if isinstance(status, str) else list(status)
            # Read-side validation: accept the full project-status enum
            # (including lifecycle-finished values terminated and deleted).
            # Update-side validation lives in update_project and remains
            # restricted to _VALID_UPDATE_STATUSES.
            valid_statuses = self._VALID_FILTER_STATUSES
            invalid = [s for s in status_list if s not in valid_statuses]
            if invalid:
                raise ValidationError(
                    f"Invalid status value(s) {invalid}. Must be one of: {', '.join(sorted(valid_statuses))}",
                    context={"operation": "list_projects", "invalid": invalid},
                )

        # ----- Normalize project_type and validate -----
        project_type_list: list[str] | None = None
        if project_type is not None:
            from giljo_mcp.services.taxonomy_ops import RESERVED_TASK_TYPE_ABBR

            project_type_list = [project_type] if isinstance(project_type, str) else list(project_type)
            effective_tk_for_types = tenant_key or self.tenant_manager.get_current_tenant()
            valid_types = await self._get_valid_project_types(effective_tk_for_types)
            # BE-6079 (L3) / IMP-6262: TSK is filtered OUT of _get_valid_project_types
            # because a project can never be CREATED as TSK. Converting a task now
            # STRIPS the type (the project is born untyped) and the ce_0067 backfill
            # un-typed any legacy converted projects, so no project is TSK-typed —
            # this filter value is a harmless no-op that now matches nothing, kept
            # for back-compat. Create/retag still reject TSK elsewhere.
            valid_abbrevs = {t["abbreviation"] for t in valid_types} | {RESERVED_TASK_TYPE_ABBR}
            invalid_types = [t for t in project_type_list if t not in valid_abbrevs]
            if invalid_types:
                raise ValidationError(
                    f"Invalid project_type value(s) {invalid_types}. Valid types: {', '.join(sorted(valid_abbrevs))}",
                    context={"operation": "list_projects", "invalid": invalid_types},
                )

        # ----- Validate taxonomy_alias_prefix (length cap, agent input) -----
        if taxonomy_alias_prefix is not None:
            if not isinstance(taxonomy_alias_prefix, str):
                raise ValidationError(
                    "taxonomy_alias_prefix must be a string.",
                    context={"operation": "list_projects"},
                )
            if len(taxonomy_alias_prefix) > 64:
                raise ValidationError(
                    "taxonomy_alias_prefix exceeds 64-character limit.",
                    context={"operation": "list_projects"},
                )

        effective_tenant_key = tenant_key or self.tenant_manager.get_current_tenant()
        ws = websocket_manager or self._websocket_manager

        from giljo_mcp.services.product_service import ProductService

        product_service = ProductService(
            db_manager=self.db_manager,
            tenant_key=effective_tenant_key,
            websocket_manager=ws,
        )
        active_product = await product_service.get_active_product()
        if not active_product:
            raise ValidationError(
                "No active product set. Please activate a product first.",
                context={"tenant_key": effective_tenant_key, "operation": "list_projects"},
            )

        # Seq 161 + IMP-5036: SQL pushdown for the status filter (see helper).
        # BE-9343 (audit F2): a completion-date bound implies include_completed --
        # rationale in _resolve_inner_status.
        inner_status = _resolve_inner_status(
            status_list,
            include_completed,
            has_completion_filter=completed_after is not None or completed_before is not None,
        )

        # BE-6071 F6a: pass a high defensive ceiling (newest-first via the repo's
        # limit-fallback order). This is a safety cap against a pathological
        # all-tenant fan-out, NOT pagination — a normal tenant (< ceiling active
        # projects) sees the identical list. Log a warning if the cap is hit so
        # truncation is observable.
        product_projects = await self.list_projects(
            status=inner_status,
            tenant_key=effective_tenant_key,
            include_cancelled=True,
            product_id=active_product.id,
            limit=_MCP_LIST_PROJECT_CEILING,
        )
        if len(product_projects) >= _MCP_LIST_PROJECT_CEILING:
            logger.warning(
                "list_projects_for_mcp hit the %d-project defensive ceiling for tenant %s "
                "(product %s); the agent-facing list is truncated to the newest %d. "
                "This signals an unusually large active-project set worth retention review.",
                _MCP_LIST_PROJECT_CEILING,
                effective_tenant_key,
                active_product.id,
                _MCP_LIST_PROJECT_CEILING,
            )

        # BE-9157: hide superseded by default even when include_completed=True
        # surfaced them (inner_status=None). An explicit status request wins.
        superseded_explicitly_requested = status_list is not None and ProjectStatus.SUPERSEDED.value in status_list
        exclude_superseded = not include_superseded and not superseded_explicitly_requested

        # Apply remaining filters in Python (post-fetch). Status and product
        # scoping are now SQL-side; only the v1.2.1 cross-cutting predicates
        # (hidden, project_type, taxonomy_alias_prefix, date ranges) remain
        # in-memory because they slice across enum-typed and computed columns
        # that don't all live in a single index.
        filtered: list = []
        for p in product_projects:
            # Superseded exclusion (BE-9157): audit-trail rows hidden by default.
            if exclude_superseded and p.status == ProjectStatus.SUPERSEDED.value:
                continue

            # Hidden filter (None = both)
            if hidden is not None and bool(p.hidden) != bool(hidden):
                continue

            # Project type filter
            if project_type_list is not None:
                pt_abbrev = p.project_type.abbreviation if p.project_type else None
                if pt_abbrev not in project_type_list:
                    continue

            # Taxonomy alias prefix filter (case-sensitive prefix match)
            if taxonomy_alias_prefix and not (p.taxonomy_alias or "").startswith(taxonomy_alias_prefix):
                continue

            # Date range filters (created_at and completed_at are ISO strings on ProjectListItem)
            if created_after is not None or created_before is not None:
                created_dt = _parse_iso_datetime(p.created_at)
                if created_after is not None and (created_dt is None or created_dt < created_after):
                    continue
                if created_before is not None and (created_dt is None or created_dt > created_before):
                    continue

            if completed_after is not None or completed_before is not None:
                completed_dt = _parse_iso_datetime(p.completed_at) if p.completed_at else None
                if completed_after is not None and (completed_dt is None or completed_dt < completed_after):
                    continue
                if completed_before is not None and (completed_dt is None or completed_dt > completed_before):
                    continue

            filtered.append(p)

        effective_depth = 0 if summary_only else depth

        projects_out = await self._build_mcp_project_list(
            filtered,
            effective_depth,
            effective_tenant_key,
            headlines=headlines,
            memory_limit=resolved_memory_limit,
        )

        response: dict[str, Any] = {
            "success": True,
            "product_id": active_product.id,
            "count": len(projects_out),
            "depth": effective_depth,
            "projects": projects_out,
        }
        if mode is not None:
            response["mode"] = mode

        # IMP-5036 task 696cf625: surface the post-strip payload-size signal
        # for the historical 63K-overflow culprit hunt. Per-row breakdown of
        # the largest contributing field (description/mission/memory_entries/etc.)
        # lands at DEBUG — the culprit hunt is done, so it stays out of the
        # operational INFO log; flip the logger to DEBUG to chart it again.
        self._log_payload_size_breakdown(projects_out, effective_depth, mode)

        return response

    def _log_payload_size_breakdown(
        self,
        projects_out: list[dict[str, Any]],
        depth: int,
        mode: str | None,
    ) -> None:
        """Log per-row JSON payload size and the field contributing the most.

        Emits a single DEBUG log per list_projects_for_mcp call with:
        - total payload size (bytes, JSON-encoded)
        - count of rows
        - top field per row by serialized byte count
        - the row's project_id and taxonomy_alias for triage

        Defensive try/except guards JSON serialization at the system boundary
        (log emission) so instrumentation never breaks the request.
        """
        import json

        try:
            total_bytes = len(json.dumps(projects_out, default=str))
            per_row: list[dict[str, Any]] = []
            for row in projects_out:
                field_sizes: dict[str, int] = {}
                for k, v in row.items():
                    field_sizes[k] = len(json.dumps(v, default=str))
                top_field = max(field_sizes, key=field_sizes.get) if field_sizes else None
                per_row.append(
                    {
                        "project_id": row.get("project_id"),
                        "taxonomy_alias": row.get("taxonomy_alias"),
                        "row_bytes": sum(field_sizes.values()),
                        "top_field": top_field,
                        "top_field_bytes": field_sizes.get(top_field, 0) if top_field else 0,
                    }
                )
            self._logger.debug(
                "list_projects payload size: total_bytes=%d rows=%d depth=%d mode=%s breakdown=%s",
                total_bytes,
                len(projects_out),
                depth,
                mode,
                per_row,
            )
        except (TypeError, ValueError) as exc:
            self._logger.warning("list_projects payload-size instrumentation failed: %s", exc)

    async def _build_mcp_project_list(
        self,
        projects: list,
        depth: int,
        tenant_key: str,
        headlines: bool = False,
        memory_limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Build project list dicts with graduated detail based on depth level.

        BE-5042: ``headlines`` and ``memory_limit`` propagate to the query
        service so audit mode can request a lean projection without forking
        the read path.

        BE-6071 F6b: the per-call (depth 1-2) enrichment facets are fetched in
        ONE grouped query each across ALL listed project_ids (BE-6066 grouped-IN
        pattern), then assembled per-project from the maps — instead of one query
        per project per facet (the N+1). The depth-3 forensic message history
        stays per-project on purpose (see below).
        """
        project_ids = [p.id for p in projects]

        # One grouped query per hot facet, up front — not N per facet.
        agent_summary_map: dict[str, dict] = {}
        agent_details_map: dict[str, list] = {}
        memory_entries_map: dict[str, list] = {}
        if project_ids:
            if depth >= 1:
                agent_summary_map = await self.query.get_project_agent_summaries(project_ids, tenant_key)
            if depth >= 2:
                agent_details_map = await self.query.get_project_agent_details_batch(
                    project_ids, tenant_key, headlines=headlines
                )
                memory_entries_map = await self.query.get_project_memory_entries_batch(
                    project_ids, tenant_key, headlines=headlines, limit=memory_limit
                )

        results = []
        for p in projects:
            item: dict[str, Any] = {
                "project_id": p.id,
                "name": p.name,
                "status": p.status,
                "project_type": getattr(p.project_type, "abbreviation", None) if p.project_type else None,
                "series_number": p.series_number,
                "taxonomy_alias": p.taxonomy_alias,
                "created_at": p.created_at,
                "completed_at": p.completed_at,
            }

            if depth >= 1:
                item["description"] = p.description or ""
                item["mission"] = getattr(p, "mission", None) or ""
                item["agent_summary"] = agent_summary_map.get(p.id, {"agent_count": 0, "job_types": []})

            memory_entries: list = []
            if depth >= 2:
                memory_entries = memory_entries_map.get(p.id, [])
                item["memory_entries"] = memory_entries
                item["agent_details"] = agent_details_map.get(p.id, [])

            if depth >= 3:
                item["git_commits"] = self._extract_git_commits(memory_entries)
                # BE-6071: depth-3 forensic message history stays PER-PROJECT (not
                # batched). It is already F6c-capped at _FORENSIC_MESSAGE_CAP/project
                # AND forensic is a rare operator deep-dive off the hot path, so the
                # bounded per-project query is acceptable — batching it would require
                # a per-project SQL LIMIT (window function) for the least benefit.
                message_history = await self.query.get_project_messages(
                    project_id=p.id,
                    tenant_key=tenant_key,
                    limit=_FORENSIC_MESSAGE_CAP,
                )
                item["message_history"] = message_history

            results.append(item)
        return results
