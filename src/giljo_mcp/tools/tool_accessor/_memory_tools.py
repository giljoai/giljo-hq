# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any


class MemoryToolsMixin:

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
        from giljo_mcp.tools.project_closeout import close_project_and_update_memory as tool_func

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
        from giljo_mcp.tools.write_memory_entry import write_360_memory as tool_func

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
