# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Setup / download / health / tuning tools mixin for ToolAccessor (BE-6042a split)."""

from __future__ import annotations

import logging
from typing import Any

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.http.url_resolver import get_public_url
from giljo_mcp.schemas.service_responses import build_next_action
from giljo_mcp.tools.setup_instructions import build_setup_instructions


logger = logging.getLogger(__name__)


class SetupMiscMixin:
    """Health/download/bootstrap/template-export/tuning tool delegators. Composed into ToolAccessor."""

    # Orchestration Tools

    # INF-6111b: generate_download_token accessor leg RETIRED with its @mcp.tool
    # wrapper (no live MCP callers). The REST POST /api/download/generate-token
    # route in api/endpoints/downloads.py is the remaining download-token path.

    async def _resolve_product_binding(self, tenant_key: str, product_id: str | None):
        """Resolve the phase-aware product-binding context for giljo_setup (BE-9523c).

        Three phases:
        - product_id supplied -> validate it belongs to this tenant, bind to it.
        - omitted, tenant owns exactly one product -> bind to it (unambiguous default).
        - omitted, tenant owns zero or 2+ products -> "zero" / "ambiguous" (never guess).

        Returns a ``ProductBindingContext`` for ``build_setup_instructions``.
        """
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
        """
        Stage combined slash commands + agent templates ZIP for first-time setup (Handover 0907).

        Returns a download URL for a ZIP containing everything the agent needs.
        Binary transfer — no template content passes through the LLM.

        BE-9523c: also resolves the phase-aware per-repo product binding (bound /
        zero products / ambiguous) and folds it into the returned instructions.
        """
        from giljo_mcp.downloads.token_manager import TokenManager
        from giljo_mcp.file_staging import FileStaging
        from giljo_mcp.services.product_service import ProductAmbiguousError

        try:
            product_binding = await self._resolve_product_binding(tenant_key, product_id)

            # BE-9589: REFUSE BEFORE PACKAGING. The ambiguous phase already existed
            # (BE-9523c) but only reached build_setup_instructions -- the prose -- while
            # bound_product_id fell to None and file_staging then exported the DEFAULT
            # product's junction. So a 2+-product tenant silently received some product's
            # agents and read about the ambiguity afterwards, if at all.
            #
            # Raised here, ahead of generate_token/stage_combined_setup, because the
            # side effect is the thing that matters: refusing later would still burn a
            # download token and write a staging directory for a package nobody asked
            # for. ProductAmbiguousError is the house shape -- the MCP dispatch
            # chokepoint (_base.py) converts it to the Tier-2 structured rejection
            # carrying the product list, so the agent gets a remedy on the normal tool
            # content path rather than an isError. Its message already names giljo_setup
            # with product_id as the way to persist the binding, which is exactly the
            # remedy for this caller.
            #
            # phase == "zero" deliberately still proceeds: a tenant with no products
            # gets the slash-commands-only ZIP exactly as it does today. There is no
            # question to ask, so there is nothing to refuse.
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

                # BE-9557: thread the resolved binding into template selection --
                # this used to be computed above and then discarded, so the
                # export followed an arbitrary shown product instead of the
                # one the caller (or the sole-product default) actually bound.
                bound_product_id = product_binding.product_id if product_binding.phase == "bound" else None

                staging_path = await staging.create_staging_directory(tenant_key, token)
                zip_path, message = await staging.stage_combined_setup(
                    staging_path,
                    tenant_key,
                    db_session=session,
                    platform=platform,
                    product_id=bound_product_id,
                )

                if not zip_path:
                    await token_manager.mark_failed(token, message)
                    raise ValidationError(message)

                await token_manager.mark_ready(token)

                # IMP-0023: per-user skills-version stamping removed.

                # MCP tool context has no FastAPI request, so we can't use
                # request.base_url here. Fall back to GILJO_PUBLIC_URL env var
                # (set in .env.demo / SaaS deploys). CE default covers localhost.
                # BE-9442: via the one accessor, which strips the trailing slash —
                # this value has a path appended to it on the next line.
                server_url = get_public_url()
                download_url = f"{server_url}/api/download/temp/{token}/{filename}"

                # Build natural-language install prompt the LLM will execute
                # BE-9385b: the harness decides repo-level vs user-level targeting.
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
        except Exception as _exc:  # Broad catch: tool boundary, logs and re-raises
            logger.exception("Failed to stage bootstrap setup")
            raise

    async def list_agent_templates(self, tenant_key: str, platform: str, product_id: str = "") -> dict[str, Any]:
        """
        Export agent templates formatted for the target CLI platform.

        Returns pre-assembled files (Claude Code, Gemini CLI) or structured
        data (Codex CLI) ready for the calling agent to install locally.

        Templates are tenant-scoped rows, but the exported SET follows a product
        (BE-9385a): the ``product_agent_assignments`` junction decides which of
        the tenant's active templates ship. A product with no junction rows falls
        back to the full tenant-active set.

        Handover 0836a: Multi-platform agent template export.

        Args:
            tenant_key: Tenant identifier for multi-tenant isolation.
            platform: Target platform -- 'claude_code', 'codex_cli', or 'gemini_cli'.
            product_id: Optional product UUID to scope the export to (BE-9557:
                giljo_setup's already-resolved product binding). Validated
                against this tenant via ``_resolve_product_binding`` -- a
                foreign or nonexistent id is rejected, not silently ignored.
                Falsy resolves the tenant's DEFAULT product instead (see
                ``product_agent_selection._resolve_default_product_id``).

        Returns:
            Dict with platform, agents list, install_paths, template_count, format_version.
        """
        from sqlalchemy import select

        from giljo_mcp.models import AgentTemplate
        from giljo_mcp.repositories.product_agent_selection import (
            active_product_template_ids,
            build_export_context,
            filter_templates_by_ids,
            template_ids_for_product,
        )
        from giljo_mcp.template_renderer import select_templates_for_packaging
        from giljo_mcp.tools.agent_template_assembler import AgentTemplateAssembler

        try:
            # BE-9557: validate an explicit product_id belongs to this tenant
            # BEFORE it reaches the selection query -- untrusted agent input,
            # membership checked at the boundary rather than silently no-op'd.
            resolved_product_id: str | None = None
            if product_id and product_id.strip():
                binding = await self._resolve_product_binding(tenant_key, product_id)
                resolved_product_id = binding.product_id

            async with self.get_session_async() as session:
                # Tenant-scoped query for live active templates (BE-6137: exclude soft-deleted)
                stmt = (
                    select(AgentTemplate)
                    .where(
                        AgentTemplate.tenant_key == tenant_key,
                        AgentTemplate.is_active,
                        AgentTemplate.deleted_at.is_(None),
                    )
                    .order_by(AgentTemplate.name)
                )

                result = await session.execute(stmt)
                all_active = list(result.scalars().all())

                if not all_active:
                    raise ValidationError("No active templates found for this tenant")

                # BE-9385a/BE-9557: narrow to the REQUESTED product's agents when
                # one was given, else the DEFAULT product's. None = the junction
                # has no opinion for this product, so the tenant-active set ships
                # unchanged (see product_agent_selection's TOLERANCE note).
                if resolved_product_id:
                    ids = await template_ids_for_product(session, resolved_product_id, tenant_key)
                else:
                    ids = await active_product_template_ids(session, tenant_key)
                all_active = filter_templates_by_ids(all_active, ids)

                if not all_active:
                    raise ValidationError(
                        "No agents are enabled for the requested product. Enable at least one "
                        "agent for this product, or switch to a product that has agents enabled."
                    )

                selected = select_templates_for_packaging(all_active)

                # BE-9385b: product-qualified names + ownership markers, so two
                # products' copies of one agent coexist on disk instead of racing.
                export_context = await build_export_context(session, tenant_key, product_id=resolved_product_id)
                assembler = AgentTemplateAssembler()
                response = assembler.assemble(selected, platform, export_context=export_context)

                # Update last_exported_at via TemplateService (write discipline)
                from giljo_mcp.services.template_service import TemplateService

                template_svc = TemplateService(
                    db_manager=self.db_manager,
                    tenant_manager=self.tenant_manager,
                )
                template_ids = [str(t.id) for t in selected]
                # BE-9385e: product_id records the export against the product that
                # performed it, alongside the tenant-wide stamp, in one transaction.
                await template_svc.mark_templates_exported(
                    template_ids,
                    tenant_key,
                    product_id=export_context.product_id if export_context else None,
                )

                return response
        except ValidationError:
            raise
        except Exception as _exc:  # Broad catch: tool boundary, logs and re-raises
            logger.exception("Failed to export agent templates")
            raise

    # Product Context Tuning (Handover 0831)

    async def apply_context_tuning(
        self,
        product_id: str,
        tenant_key: str,
        proposals: list[dict[str, Any]],
        overall_summary: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """
        Apply reviewed product context tuning directly to product fields, after
        comparing current product context against recent project history
        (Handover 0831; renamed from propose_product_context_update in BE-6225c).

        Args:
            product_id: Target product UUID
            tenant_key: Tenant isolation key
            proposals: Per-section proposals with drift_detected, evidence, proposed_value
            overall_summary: High-level drift assessment
            force: If True, allow overwriting populated JSONB fields

        Returns:
            Success response with review_id
        """
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
