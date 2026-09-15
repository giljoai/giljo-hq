# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from datetime import datetime
from typing import Any

from giljo_mcp.domain.project_status import (
    LIFECYCLE_FINISHED_STATUSES,
    ProjectStatus,
)
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.repositories.project_repository import ProjectRepository
from giljo_mcp.services._mcp_wire_bounds import worst_case_cursor_charge
from giljo_mcp.services.project_service._mcp_lifecycle_advice import (
    attach_lifecycle_hidden_advice,
    has_narrowing_filter,
)
from giljo_mcp.services.project_service._mcp_list_bounds import (
    apply_row_limit,
    build_counts_block,
    build_list_response,
    mint_next_cursor,
    open_cursor_walk,
)
from giljo_mcp.services.project_service._mcp_list_diagnostics import log_payload_size_breakdown
from giljo_mcp.services.project_service._mcp_list_filters import (
    _apply_post_fetch_filters,
    resolve_list_projects_query_filters,
)


logger = logging.getLogger(__name__)

_MCP_LIST_PROJECT_CEILING = 2500

_FORENSIC_MESSAGE_CAP = 200


def _resolve_inner_status(
    status_list: list[str] | None,
    include_completed: bool,
    has_completion_filter: bool = False,
) -> str | list[str] | None:
    if status_list is not None:
        return status_list[0] if len(status_list) == 1 else status_list
    if include_completed or has_completion_filter:
        return None
    return sorted({s.value for s in ProjectStatus} - {s.value for s in LIFECYCLE_FINISHED_STATUSES})


def _is_completion_oriented(
    status_list: list[str] | None,
    include_completed: bool,
    has_completion_filter: bool,
) -> bool:
    if status_list is not None:
        return ProjectStatus.COMPLETED.value in status_list
    return include_completed or has_completion_filter


class McpAdapterQueryMixin:

    async def _fetch_under_ceiling(
        self,
        *,
        inner_status: str | list[str] | None,
        tenant_key: str,
        product_id: str,
        completion_oriented: bool,
        search: str | None = None,
        after_key: tuple[Any, str] | None = None,
    ) -> tuple[list, bool]:
        rows = await self.list_projects(
            status=inner_status,
            tenant_key=tenant_key,
            include_cancelled=True,
            product_id=product_id,
            search=search,
            sort_key=ProjectRepository.COMPLETION_RECENCY_SORT_KEY if completion_oriented else None,
            limit=_MCP_LIST_PROJECT_CEILING,
            after_key=after_key,
        )
        truncated = len(rows) >= _MCP_LIST_PROJECT_CEILING
        if truncated:
            logger.warning(
                "list_projects_for_mcp hit the %d-project defensive ceiling for tenant %s "
                "(product %s); the agent-facing list is truncated. The response carries "
                "truncated=true so the caller can see it too. This signals an unusually "
                "large project set worth retention review.",
                _MCP_LIST_PROJECT_CEILING,
                tenant_key,
                product_id,
            )
        return rows, truncated

    async def _matched_across_walk(
        self,
        *,
        after_key: tuple[Any, str] | None,
        cursor_scoped_remaining: int | None,
        fetch_kwargs: dict[str, Any],
        post_filter_kwargs: dict[str, Any],
    ) -> int | None:
        if after_key is None:
            return cursor_scoped_remaining
        whole_rows, whole_truncated = await self._fetch_under_ceiling(**fetch_kwargs)
        if whole_truncated:
            return None
        return len(_apply_post_fetch_filters(whole_rows, **post_filter_kwargs))

    async def _relaxed_lifecycle_count(
        self,
        fetch_kwargs: dict[str, Any],
        post_filter_kwargs: dict[str, Any],
    ) -> int | None:
        relaxed_rows, relaxed_truncated = await self._fetch_under_ceiling(**{**fetch_kwargs, "inner_status": None})
        if relaxed_truncated:
            return None
        return len(_apply_post_fetch_filters(relaxed_rows, **post_filter_kwargs))

    async def _board_counts(
        self,
        tenant_key: str,
        product_id: str,
        *,
        returned: int,
        matched: int | None,
        remaining: int | None = None,
    ) -> dict[str, Any]:
        grouped = await self.board_counts(tenant_key=tenant_key, product_id=product_id)
        return build_counts_block(grouped, returned=returned, matched=matched, remaining=remaining)

    def _resolve_legacy_status_filter(
        self, status: str | list[str] | None, status_filter: str | None, include_completed: bool
    ) -> tuple[str | list[str] | None, bool]:
        if status_filter is None:
            return status, include_completed
        if status_filter not in self._VALID_STATUS_FILTERS:
            raise ValidationError(
                f"Invalid status_filter '{status_filter}'. "
                f"Must be one of: {', '.join(sorted(self._VALID_STATUS_FILTERS))}",
                context={"operation": "list_projects"},
            )
        if status is None:
            if status_filter == "all":
                include_completed = True
            else:
                status = status_filter
            return status, include_completed

        status_values = {status} if isinstance(status, str) else set(status)
        if status_filter == "all" or status_values != {status_filter}:
            raise ValidationError(
                f"status={status!r} and status_filter={status_filter!r} disagree -- pass "
                "only one. status_filter is legacy; prefer status. Identical values on "
                "both are accepted without conflict.",
                context={"operation": "list_projects", "status": status, "status_filter": status_filter},
            )
        return status, include_completed

    def _resolve_projection_mode(
        self,
        mode: str | None,
        depth: int,
        summary_only: bool,
        memory_limit: int | None,
    ) -> tuple[int, bool, bool, int | None]:
        headlines = False
        resolved_memory_limit: int | None = None
        if mode is None:
            if depth:
                summary_only = False
            return depth, summary_only, headlines, resolved_memory_limit

        if mode not in self._MODE_TO_PROJECTION:
            raise ValidationError(
                f"Invalid mode '{mode}'. Must be one of: {', '.join(sorted(self._MODE_TO_PROJECTION))}.",
                context={"operation": "list_projects", "mode": mode},
            )
        depth, headlines, default_limit = self._MODE_TO_PROJECTION[mode]
        summary_only = False
        if mode == "audit":
            effective_limit = memory_limit if memory_limit is not None else default_limit
            resolved_memory_limit = min(effective_limit, self._MEMORY_LIMIT_CAP)
        elif mode == "forensic":
            resolved_memory_limit = min(memory_limit, self._MEMORY_LIMIT_CAP) if memory_limit is not None else None
        else:
            resolved_memory_limit = default_limit
        return depth, summary_only, headlines, resolved_memory_limit

    async def list_projects_for_mcp(
        self,
        status_filter: str | None = None,
        summary_only: bool = True,
        depth: int = 0,
        tenant_key: str | None = None,
        websocket_manager: Any | None = None,
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
        mode: str | None = None,
        memory_limit: int | None = None,
        query: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        product_id: str | None = None,
    ) -> dict[str, Any]:
        status, include_completed = self._resolve_legacy_status_filter(status, status_filter, include_completed)
        if not isinstance(depth, int) or depth not in self._VALID_DEPTH_LEVELS:
            raise ValidationError(
                f"Invalid depth '{depth}'. Must be an integer 0-3.",
                context={"operation": "list_projects"},
            )

        depth, summary_only, headlines, resolved_memory_limit = self._resolve_projection_mode(
            mode, depth, summary_only, memory_limit
        )

        effective_tenant_key = tenant_key or self.tenant_manager.get_current_tenant()
        ws = websocket_manager or self._websocket_manager

        status_list, project_type_list, query, effective_limit = await resolve_list_projects_query_filters(
            status,
            project_type,
            taxonomy_alias_prefix,
            query,
            limit,
            valid_filter_statuses=self._VALID_FILTER_STATUSES,
            tenant_key=effective_tenant_key,
            get_valid_project_types=self._get_valid_project_types,
        )

        from giljo_mcp.services.product_service import ProductService

        product_service = ProductService(
            db_manager=self.db_manager,
            tenant_key=effective_tenant_key,
            websocket_manager=ws,
        )
        active_product = await product_service.resolve_binding_product(
            product_id, operation="list_projects", action="listed", write=False
        )

        has_completion_filter = completed_after is not None or completed_before is not None
        inner_status = _resolve_inner_status(
            status_list,
            include_completed,
            has_completion_filter=has_completion_filter,
        )

        completion_oriented = _is_completion_oriented(status_list, include_completed, has_completion_filter)

        cursor_axis, cursor_fingerprint, after_key = open_cursor_walk(
            cursor,
            completion_oriented=completion_oriented,
            product_id=active_product.id,
            status_list=status_list,
            include_completed=include_completed,
            include_superseded=include_superseded,
            hidden=hidden,
            project_type_list=project_type_list,
            taxonomy_alias_prefix=taxonomy_alias_prefix,
            created_after=created_after,
            created_before=created_before,
            completed_after=completed_after,
            completed_before=completed_before,
            query=query,
        )

        fetch_kwargs = {
            "inner_status": inner_status,
            "tenant_key": effective_tenant_key,
            "product_id": active_product.id,
            "completion_oriented": completion_oriented,
            "search": query,
        }
        product_projects, truncated = await self._fetch_under_ceiling(**fetch_kwargs, after_key=after_key)

        superseded_explicitly_requested = status_list is not None and ProjectStatus.SUPERSEDED.value in status_list
        post_filter_kwargs = {
            "exclude_superseded": not include_superseded and not superseded_explicitly_requested,
            "hidden": hidden,
            "project_type_list": project_type_list,
            "taxonomy_alias_prefix": taxonomy_alias_prefix,
            "created_after": created_after,
            "created_before": created_before,
            "completed_after": completed_after,
            "completed_before": completed_before,
        }
        filtered = _apply_post_fetch_filters(product_projects, **post_filter_kwargs)

        filtered, remaining, limit_truncated = apply_row_limit(filtered, effective_limit)
        matched_total = await self._matched_across_walk(
            after_key=after_key,
            cursor_scoped_remaining=None if truncated else remaining,
            fetch_kwargs=fetch_kwargs,
            post_filter_kwargs=post_filter_kwargs,
        )

        effective_depth = 0 if summary_only else depth

        projects_out = await self._build_mcp_project_list(
            filtered,
            effective_depth,
            effective_tenant_key,
            headlines=headlines,
            memory_limit=resolved_memory_limit,
            index_row=mode == "triage",
        )

        counts = await self._board_counts(
            effective_tenant_key,
            active_product.id,
            returned=len(projects_out),
            matched=matched_total,
            remaining=None if truncated else remaining,
        )
        await attach_lifecycle_hidden_advice(
            counts,
            project_type_list=project_type_list,
            default_lifecycle_view=status_list is None and not include_completed and not has_completion_filter,
            matched=matched_total,
            any_filter_set=has_narrowing_filter(query, post_filter_kwargs),
            relaxed_count=lambda: self._relaxed_lifecycle_count(fetch_kwargs, post_filter_kwargs),
        )
        response = build_list_response(
            projects_out=projects_out,
            cursor_charge=worst_case_cursor_charge(cursor_axis, cursor_fingerprint),
            mint_cursor=lambda rows: mint_next_cursor(
                returned_rows=rows,
                fetched_rows=product_projects,
                matched=remaining,
                ceiling_truncated=truncated,
                axis=cursor_axis,
                fingerprint=cursor_fingerprint,
            ),
            counts=counts,
            ceiling=_MCP_LIST_PROJECT_CEILING,
            product_id=active_product.id,
            depth=effective_depth,
            mode=mode,
            ceiling_truncated=truncated,
            ceiling_rows_fetched=len(product_projects),
            limit_truncated=limit_truncated,
            effective_limit=effective_limit,
            completion_oriented=completion_oriented,
        )

        log_payload_size_breakdown(self._logger, projects_out, effective_depth, mode)

        return response

    async def _build_mcp_project_list(
        self,
        projects: list,
        depth: int,
        tenant_key: str,
        headlines: bool = False,
        memory_limit: int | None = None,
        index_row: bool = False,
    ) -> list[dict[str, Any]]:
        project_ids = [p.id for p in projects]

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
                "taxonomy_alias": p.taxonomy_alias,
                "created_at": p.created_at,
                "completed_at": p.completed_at,
            }
            if not index_row:
                item["series_number"] = p.series_number

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
                message_history = await self.query.get_project_messages(
                    project_id=p.id,
                    tenant_key=tenant_key,
                    limit=_FORENSIC_MESSAGE_CAP,
                )
                item["message_history"] = message_history

            results.append(item)
        return results
