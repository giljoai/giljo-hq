# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any


class ContextToolsMixin:


    async def get_context(
        self,
        product_id: str,
        tenant_key: str,
        project_id: str | None = None,
        categories: list[str] | None = None,
        depth_config: dict[str, Any] | None = None,
        output_format: str = "structured",
        agent_name: str | None = None,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        from giljo_mcp.tools.context_tools.fetch_context import fetch_context

        return await fetch_context(
            product_id=product_id,
            tenant_key=tenant_key,
            project_id=project_id,
            categories=categories,
            depth_config=depth_config,
            output_format=output_format,
            agent_name=agent_name,
            job_id=job_id,
            db_manager=self.db_manager,
        )


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
        from giljo_mcp.tools.vision_analysis import create_vision_document as tool_func

        return await tool_func(
            product_id=product_id,
            tenant_key=tenant_key,
            content=content,
            document_name=document_name,
            db_manager=self.db_manager,
            _test_session=self._test_session,
        )


    async def get_vision_doc(
        self,
        product_id: str,
        tenant_key: str,
        chunk: int | None = None,
    ) -> dict[str, Any]:
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
