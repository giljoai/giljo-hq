# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Context fetch + vision-doc tools mixin for ToolAccessor (BE-6042a split)."""

from __future__ import annotations

from typing import Any


class ContextToolsMixin:
    """get_context + vision-doc tool delegators. Composed into ToolAccessor."""

    # Unified Context Tool (Handover 0350a)

    async def get_context(
        self,
        product_id: str,
        tenant_key: str,
        project_id: str | None = None,
        categories: list[str] | None = None,
        depth_config: dict[str, Any] | None = None,
        output_format: str = "structured",
        agent_name: str | None = None,  # Handover 0430: Required for self_identity category
        job_id: str | None = None,  # INF-5077: Required for 'todos' category
    ) -> dict[str, Any]:
        """
        Unified context fetcher - single entry point for all context.

        Handover 0350a: Replaces 9 individual tools with 1 unified tool.
        Saves ~720 tokens in MCP schema overhead.
        Handover 0430: Added agent_name parameter for self_identity category.
        INF-5077: Added job_id parameter and 'todos' category for force-recovery.

        Args:
            product_id: Product UUID
            tenant_key: Tenant isolation key
            project_id: Project UUID (required for 'project' category)
            categories: Exactly one category to fetch per call
            depth_config: Override depth settings per category
            format: "structured" (nested) or "flat" (merged)
            agent_name: Agent template name (required for 'self_identity' category)
            job_id: Agent job UUID (required for 'todos' category)

        Returns:
            Dict with context data organized by category
        """
        from giljo_mcp.tools.context_tools.fetch_context import fetch_context

        return await fetch_context(
            product_id=product_id,
            tenant_key=tenant_key,
            project_id=project_id,
            categories=categories,
            depth_config=depth_config,
            output_format=output_format,
            agent_name=agent_name,  # Handover 0430
            job_id=job_id,  # INF-5077
            db_manager=self.db_manager,
        )

    # Product bootstrap (BE-9201)

    async def create_product(
        self,
        name: str,
        tenant_key: str,
        description: str | None = None,
        project_path: str | None = None,
        core_features: str | None = None,
        brand_guidelines: str | None = None,
        target_platforms: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a product via MCP tool (BE-9201 agent-side bootstrap).

        Adapter: constructs the tenant-scoped ProductService (the owning
        service — the same path POST /api/products uses) and reshapes the ORM
        model into an agent-friendly dict. Establishes the row only; the agent
        populates tech/arch/testing via update_product_context afterwards.
        """
        from giljo_mcp.exceptions import ValidationError
        from giljo_mcp.services.product_service import ProductService

        if not name or not name.strip():
            raise ValidationError(
                "Product name is required and cannot be empty.",
                context={"operation": "create_product"},
            )

        service = ProductService(
            db_manager=self.db_manager,
            tenant_key=tenant_key,
            websocket_manager=self._websocket_manager,
            test_session=self._test_session,
        )
        product = await service.create_product(
            name=name.strip(),
            description=description,
            project_path=project_path,
            core_features=core_features,
            brand_guidelines=brand_guidelines,
            target_platforms=target_platforms,
        )
        return {
            "success": True,
            "product_id": str(product.id),
            "name": product.name,
            "description": product.description,
            "project_path": product.project_path,
            "target_platforms": product.target_platforms or ["all"],
            "is_active": product.is_active,
            "created_at": product.created_at.isoformat() if product.created_at else None,
            "next_step": (
                "Product created (inactive). Populate its card via update_product_context; "
                "write a vision document via create_vision_document. The user activates it "
                "from the dashboard review screen."
            ),
        }

    async def create_vision_document(
        self,
        product_id: str,
        content: str,
        tenant_key: str,
        document_name: str = "",
    ) -> dict[str, Any]:
        """Create an agent-authored vision document (BE-9201).

        Adapter: injects db_manager into the standalone tool-function (same
        shape as get_vision_doc / update_product_context below).
        """
        from giljo_mcp.tools.vision_analysis import create_vision_document as tool_func

        return await tool_func(
            product_id=product_id,
            tenant_key=tenant_key,
            content=content,
            document_name=document_name,
            db_manager=self.db_manager,
            _test_session=self._test_session,
        )

    # Vision Document Analysis (Handover 0842c)

    async def get_vision_doc(
        self,
        product_id: str,
        tenant_key: str,
        chunk: int | None = None,
    ) -> dict[str, Any]:
        """Retrieve vision document with extraction instructions (Handover 0842c)."""
        from giljo_mcp.tools.vision_analysis import get_vision_doc as tool_func

        return await tool_func(
            product_id=product_id,
            tenant_key=tenant_key,
            chunk=chunk,
            db_manager=self.db_manager,
            websocket_manager=self._websocket_manager,
        )

    async def update_product_context(
        self,
        product_id: str,
        tenant_key: str,
        force: bool = False,
        is_active: bool | None = None,
        **fields: Any,
    ) -> dict[str, Any]:
        """Write product fields from vision document analysis (Handover 0842c).

        is_active (BE-9502a): optional activate/deactivate/switch, routed through
        ProductService.activate_product/deactivate_product -- see
        update_product_fields for why this is not a generic field.
        """
        from giljo_mcp.tools.vision_analysis import update_product_fields as tool_func

        return await tool_func(
            product_id=product_id,
            tenant_key=tenant_key,
            db_manager=self.db_manager,
            websocket_manager=self._websocket_manager,
            force=force,
            is_active=is_active,
            **fields,
        )
