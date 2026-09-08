# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Memory + project closeout tools mixin for ToolAccessor (BE-6042a split)."""

from __future__ import annotations

from typing import Any


class MemoryToolsMixin:
    """Project closeout + 360 memory tool delegators. Composed into ToolAccessor."""

    async def write_project_closeout(
        self,
        project_id: str,
        summary: str,
        key_outcomes: list[str],
        decisions_made: list[str],
        tenant_key: str,
        force: bool = False,
        git_commits: list[dict[str, Any]] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Close project and update product memory with sequential history entries (Handover 0138+).

        This method wraps the project_closeout MCP tool for use via ToolAccessor.
        See project_closeout.py for implementation details.

        Args:
            project_id: UUID of the project being closed
            summary: User-provided summary of project work
            key_outcomes: List of key achievements/outcomes
            decisions_made: List of important decisions made
            tenant_key: Tenant isolation key
            force: If True, auto-decommission active agents and close anyway
            git_commits: Agent-supplied git commits (from local git log)
            tags: Orchestrator-supplied tags from the 16-entry controlled
                vocabulary (CONTROLLED_TAG_VOCABULARY in MemoryEntryWriteSchema).
                None or [] persists with empty tags; invalid tags are rejected
                with MemoryEntryWriteValidationError.

        Returns:
            Success/error response with learning_id and sequence number
        """
        from giljo_mcp.tools.project_closeout import close_project_and_update_memory as tool_func

        # Inject dependencies into the tool function call. BE-6198 live-update:
        # thread the accessor-held websocket_manager so the chain-drive writes inside
        # the closeout broadcast sequence:updated + project_update (the per-member
        # chain badge + "Project Completed and Closed" chip). The tool falls back to
        # the registered global when this is None, so CE/tests stay covered.
        return await tool_func(
            project_id=project_id,
            summary=summary,
            key_outcomes=key_outcomes,
            decisions_made=decisions_made,
            tenant_key=tenant_key,
            db_manager=self.db_manager,
            force=force,
            git_commits=git_commits,
            tags=tags,
            websocket_manager=self._websocket_manager,
        )

    async def search_memory(
        self,
        query: str,
        tenant_key: str,
        tag: str | None = None,
        limit: int = 10,
        product_id: str | None = None,
    ) -> dict[str, Any]:
        """BE-6225b: keyword (+ optional tag) search over 360 memory headlines.

        The missing 360-memory JTBD: lets an agent ask "have we solved X before?"
        against accumulated project history. Resolves the product server-side
        (the agent never passes tenant_key), then delegates to the reused
        ProductMemoryService search read path (BE-6082 FTS + ILIKE fallback).

        BE-9499a: ``product_id`` is optional. Omitted, this resolves the ACTIVE
        product exactly as before (same contract as list_projects). Supplied,
        it is validated as belonging to this tenant via
        ``ProductService.resolve_binding_product`` and searched regardless of
        which product is active -- never a silent fallback.

        Args:
            query: Case-insensitive keyword/substring search term.
            tenant_key: Tenant isolation key (injected by the dispatch layer).
            tag: Optional exact-tag filter (controlled vocabulary).
            limit: Max headlines to return (server-clamped).
            product_id: Optional explicit product UUID. Omit for the active product.

        Returns:
            ``{"results": [...headlines...], "count": int, "product_id": str,
            "query": str, "tag": str | None}``.

        Raises:
            ValidationError: No active product set for the tenant, or a
                supplied product_id does not belong to this tenant.
        """
        from giljo_mcp.services.product_memory_service import ProductMemoryService
        from giljo_mcp.services.product_service import ProductService

        product_service = ProductService(
            db_manager=self.db_manager,
            tenant_key=tenant_key,
            websocket_manager=self._websocket_manager,
            test_session=self._test_session,
        )
        bound_product = await product_service.resolve_binding_product(
            product_id, operation="search_memory", action="searched", write=False
        )

        memory_service = ProductMemoryService(
            db_manager=self.db_manager,
            tenant_key=tenant_key,
            test_session=self._test_session,
        )
        result = await memory_service.search_memory(
            product_id=bound_product.id,
            query=query,
            tag=tag,
            limit=limit,
        )
        result["product_id"] = bound_product.id
        return result

    async def write_memory_entry(
        self,
        project_id: str,
        tenant_key: str,
        summary: str,
        key_outcomes: list[str],
        decisions_made: list[str],
        entry_type: str = "project_completion",
        author_job_id: str | None = None,
        git_commits: list[dict[str, Any]] | None = None,
        tags: list[str] | None = None,
        user_id: str | None = None,
        acknowledge_closeout_todo: bool = False,
    ) -> dict[str, Any]:
        """
        Write a 360 memory entry for project completion or handover (Handover 0412).

        This method allows agents to create entries in the product_memory_entries table
        during handovers or at project completion.

        Args:
            project_id: UUID of the project
            tenant_key: Tenant isolation key
            summary: 2-3 paragraph summary of work accomplished
            key_outcomes: 3-5 specific achievements
            decisions_made: 3-5 architectural/design decisions
            entry_type: Type of entry. Workers: baseline, decision, architecture, discovery.
                Orchestrator-only: project_completion, session_handover.
                Legacy: handover_closeout (preserved for back-compat).
            author_job_id: Job ID of agent writing entry (optional)
            git_commits: Agent-supplied git commits (from local git log)
            tags: Tags for categorization (controlled vocabulary; see write_360_memory)

        Returns:
            Success/error response with sequence number
        """
        from giljo_mcp.tools.write_memory_entry import write_360_memory as tool_func

        # Inject dependencies into the tool function call
        return await tool_func(
            project_id=project_id,
            tenant_key=tenant_key,
            summary=summary,
            key_outcomes=key_outcomes,
            decisions_made=decisions_made,
            entry_type=entry_type,
            author_job_id=author_job_id,
            git_commits=git_commits,
            tags=tags,
            user_id=user_id,
            acknowledge_closeout_todo=acknowledge_closeout_todo,
            db_manager=self.db_manager,
        )
