# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from typing import Any

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.http.url_resolver import get_public_url
from giljo_mcp.schemas.service_responses import build_next_action
from giljo_mcp.tools.setup_instructions import build_setup_instructions


logger = logging.getLogger(__name__)


class SetupMiscMixin:



    async def _resolve_product_binding(self, tenant_key: str, product_id: str | None):
        from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
        from giljo_mcp.services.product_service import ProductService
        from giljo_mcp.tools.setup_instructions import ProductBindingContext

        service = ProductService(db_manager=self.db_manager, tenant_key=tenant_key)

        if product_id and product_id.strip():
            try:
                product = await service.get_product(product_id.strip())
            except ResourceNotFoundError as exc:
                raise ValidationError(
                    f"product_id '{product_id}' was not found for this tenant. Pass the product_id "
                    "of one of your own products (see get_context(categories=['products'])), or omit "
                    "product_id.",
                    context={"product_id": product_id, "tenant_key": tenant_key},
                ) from exc
            return ProductBindingContext(phase="bound", product_id=str(product.id), product_name=product.name)

        products = await service.list_products(include_inactive=True, lean=True)
        if not products:
            return ProductBindingContext(phase="zero")
        if len(products) == 1:
            p = products[0]
            return ProductBindingContext(phase="bound", product_id=str(p.id), product_name=p.name)
        return ProductBindingContext(
            phase="ambiguous",
            products=tuple({"id": str(p.id), "name": p.name, "is_active": bool(p.is_active)} for p in products),
        )

    async def bootstrap_setup(
        self,
        tenant_key: str,
        platform: str = "claude_code",
        user_id: str | None = None,
        harness: str | None = None,
        product_id: str | None = None,
    ) -> dict[str, Any]:
        from giljo_mcp.downloads.token_manager import TokenManager
        from giljo_mcp.file_staging import FileStaging
        from giljo_mcp.services.product_service import ProductAmbiguousError

        try:
            product_binding = await self._resolve_product_binding(tenant_key, product_id)

            if product_binding.phase == "ambiguous":
                raise ProductAmbiguousError(
                    products=[dict(p) for p in product_binding.products],
                    operation="giljo_setup",
                    tenant_key=tenant_key,
                )

            async with self.get_session_async() as session:
                token_manager = TokenManager(db_session=session)
                staging = FileStaging(db_session=session)

                filename = "giljo_setup.zip"
                token = await token_manager.generate_token(
                    tenant_key=tenant_key,
                    download_type="slash_commands",
                    filename=filename,
                )

                staging_path = await staging.create_staging_directory(tenant_key, token)
                zip_path, message = await staging.stage_setup_bundle(staging_path, platform=platform)

                if not zip_path:
                    await token_manager.mark_failed(token, message)
                    raise ValidationError(message)

                await token_manager.mark_ready(token)


                server_url = get_public_url()
                download_url = f"{server_url}/api/download/temp/{token}/{filename}"

                instructions = build_setup_instructions(
                    platform, download_url, harness, product_binding=product_binding
                )

                return {
                    "status": "ready",
                    "platform": platform,
                    "expires_in_minutes": 15,
                    "next_action": build_next_action(why=instructions),
                }
        except (ValidationError, ValueError):
            raise
        except Exception as _exc:
            logger.exception("Failed to stage bootstrap setup")
            raise


    async def apply_context_tuning(
        self,
        product_id: str,
        tenant_key: str,
        proposals: list[dict[str, Any]],
        overall_summary: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        from giljo_mcp.tools.submit_tuning_review import submit_tuning_review as tool_func

        return await tool_func(
            product_id=product_id,
            tenant_key=tenant_key,
            proposals=proposals,
            overall_summary=overall_summary,
            force=force,
            db_manager=self.db_manager,
            websocket_manager=self._websocket_manager,
        )
