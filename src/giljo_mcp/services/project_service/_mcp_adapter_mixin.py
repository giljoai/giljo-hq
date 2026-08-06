# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""MCP-tool adapter mixin for ProjectService (BE-6042c split; BE-6005 list path carved out).

Holds the agent-facing MCP WRITE entry points (create / update-metadata) plus the
CTX bootstrap render helper. The agent-facing READ path (``list_projects_for_mcp``
and its projection helpers) lives in the sibling ``McpAdapterQueryMixin``
(``_mcp_adapter_query_mixin.py``); ``ProjectService`` composes both. References
``self.*`` / ``self._*`` only. The ``_VALID_*`` / ``_MODE_TO_PROJECTION`` /
``_MEMORY_LIMIT_CAP`` class attributes and the ``_get_valid_project_types`` /
``_extract_git_commits`` helpers it calls live on the base class and resolve via
the MRO. Behavior is byte-identical to the pre-split single-file class.
"""

import logging
from typing import Any

from giljo_mcp.ctx_bootstrap_template import render_ctx_bootstrap
from giljo_mcp.exceptions import (
    AlreadyExistsError,
    ValidationError,
)
from giljo_mcp.repositories.product_repository import ProductRepository
from giljo_mcp.services.vision_hash import compute_vision_inputs_hash


logger = logging.getLogger(__name__)


class McpAdapterMixin:
    """Agent-facing MCP tool entry points + projection helpers. Composed into ProjectService."""

    async def create_project_for_mcp(
        self,
        name: str,
        mission: str = "",
        description: str = "",
        product_id: str | None = None,
        tenant_key: str | None = None,
        project_type: str | None = None,
        series_number: int | None = None,
        subseries: str | None = None,
        bootstrap_template_vars: dict[str, Any] | None = None,
        websocket_manager: Any | None = None,
    ) -> dict[str, Any]:
        """Create a project via MCP tool (validation + active product resolution).

        Pushed down from ToolAccessor.create_project (sprint 002f).
        """
        if not name or not name.strip():
            raise ValidationError(
                "Project name is required and cannot be empty.",
                context={"operation": "create_project"},
            )
        name = name.strip()
        description = description.strip() if description else ""

        effective_tenant_key = tenant_key or self.tenant_manager.get_current_tenant()
        ws = websocket_manager or self._websocket_manager

        project_type_id = None
        resolved_type_label = ""
        if project_type:
            resolved_type = await self.get_project_type_by_label(project_type, effective_tenant_key)
            if resolved_type:
                project_type_id = resolved_type.id
                resolved_type_label = resolved_type.abbreviation or project_type
            else:
                valid_types = await self._get_valid_project_types(effective_tenant_key)
                valid_labels = [t["abbreviation"] for t in valid_types]
                raise ValidationError(
                    f"Unknown project type '{project_type}'. "
                    f"Valid types: {', '.join(valid_labels)}. "
                    "Set project_type to one of these abbreviations or omit it.",
                    context={"operation": "create_project", "valid_types": valid_types},
                )

        if not product_id:
            from giljo_mcp.services.product_service import ProductService

            product_service = ProductService(
                db_manager=self.db_manager,
                tenant_key=effective_tenant_key,
                websocket_manager=ws,
                test_session=self._test_session,
            )
            active_product = await product_service.get_active_product()
            if not active_product:
                raise ValidationError(
                    "No active product set. Please activate a product first.",
                    context={"tenant_key": effective_tenant_key, "operation": "create_project"},
                )
            product_id = active_product.id

        # BE-5122: CTX project_type renders its mission from the CTX bootstrap
        # template using product + vision-input state. The dict is mandatory
        # (even if empty) so callers signal intent explicitly; an absent dict
        # produces a clean 422, never a stale agent prompt.
        if resolved_type_label == "CTX":
            mission = await self.render_ctx_bootstrap_mission(
                product_id=product_id,
                tenant_key=effective_tenant_key,
                bootstrap_template_vars=bootstrap_template_vars,
            )

        project = await self.create_project(
            name=name,
            mission=mission,
            description=description,
            product_id=product_id,
            tenant_key=effective_tenant_key,
            status="inactive",
            project_type_id=project_type_id,
            series_number=series_number,
            subseries=subseries,
        )

        logger.info(
            "Created project %s (alias: %s) for tenant %s in product %s",
            project.id,
            project.alias,
            effective_tenant_key,
            product_id,
        )

        if ws:
            try:
                await ws.broadcast_to_tenant(
                    tenant_key=effective_tenant_key,
                    event_type="project:created",
                    data={"project_id": str(project.id), "name": project.name, "product_id": product_id},
                )
            except (RuntimeError, ValueError, OSError) as e:
                logger.warning(f"Failed to broadcast project:created event: {e}")

        response: dict[str, Any] = {
            "success": True,
            "project_id": project.id,
            "alias": project.alias,
            "name": project.name,
            "description": project.description,
            "mission": project.mission,
            "status": project.status,
            "product_id": project.product_id,
            "project_type": resolved_type_label,
            "series_number": project.series_number or 0,
            "taxonomy_alias": project.taxonomy_alias,
            # BE-9326: create_project now returns a ProjectDetail whose timestamps
            # are already ISO strings (the MCP wire format), not datetimes.
            "created_at": project.created_at,
            "message": f"Project '{project.name}' created successfully",
            # BE-6049d: advertise that numbering is automatic so agents stop
            # supplying series_number. The serial is minted continue-upward on a
            # single global (tenant, product) line shared with tasks.
            "numbering": (
                "auto-assigned (continue-upward, global across all types and tasks); you do not pick the series_number"
            ),
        }
        if not project_type:
            response["valid_types"] = await self._get_valid_project_types(effective_tenant_key)
        return response

    async def render_ctx_bootstrap_mission(
        self,
        *,
        product_id: str,
        tenant_key: str,
        bootstrap_template_vars: dict[str, Any] | None,
    ) -> str:
        """Render the CTX bootstrap template into a project mission (BE-5122).

        Validates ``bootstrap_template_vars`` shape (must be a dict; optional
        ``new_documents`` must be a list of dicts), loads the product with its
        vision documents, computes the derived ``vision_inputs_hash``, and
        returns the substituted prompt. Validation errors produce a clean
        ``ValidationError`` (mapped to HTTP 422) — never a 500.
        """
        if bootstrap_template_vars is None:
            raise ValidationError(
                "CTX project_type requires bootstrap_template_vars (dict). "
                "Pass at least an empty dict to acknowledge intent.",
                context={"operation": "create_project", "project_type": "CTX"},
            )
        if not isinstance(bootstrap_template_vars, dict):
            raise ValidationError(
                "bootstrap_template_vars must be a dict.",
                context={"operation": "create_project", "project_type": "CTX"},
            )

        new_documents = bootstrap_template_vars.get("new_documents")
        if new_documents is not None:
            if not isinstance(new_documents, list):
                raise ValidationError(
                    "bootstrap_template_vars.new_documents must be a list.",
                    context={"operation": "create_project", "project_type": "CTX"},
                )
            if len(new_documents) > 50:
                raise ValidationError(
                    "bootstrap_template_vars.new_documents accepts at most 50 entries.",
                    context={"operation": "create_project", "project_type": "CTX"},
                )
            # BE-5122 review F7: per-field length caps. Agent input is untrusted;
            # a 100KB document_name would otherwise inflate the rendered mission.
            for entry in new_documents:
                if not isinstance(entry, dict):
                    raise ValidationError(
                        "Each new_documents entry must be a dict.",
                        context={"operation": "create_project", "project_type": "CTX"},
                    )
                for capped_field in ("document_name", "document_type", "id", "name", "type"):
                    value = entry.get(capped_field)
                    if value is None:
                        continue
                    if not isinstance(value, str):
                        raise ValidationError(
                            f"bootstrap_template_vars.new_documents[].{capped_field} must be a string.",
                            context={"operation": "create_project", "project_type": "CTX"},
                        )
                    if len(value) > 200:
                        raise ValidationError(
                            f"bootstrap_template_vars.new_documents[].{capped_field} exceeds 200 chars.",
                            context={"operation": "create_project", "project_type": "CTX"},
                        )

        product_repo = ProductRepository()
        # BE-5122 review F6: this opens a read-only session BEFORE the write
        # transaction in create_project. Intentional — we pre-validate that the
        # product exists and render the template against committed state. Do NOT
        # collapse into a single transaction without re-checking the create flow.
        async with self._get_session(tenant_key) as session:
            product = await product_repo.get_by_id(session, tenant_key, product_id, eager_load=True)
            if product is None:
                raise ValidationError(
                    "Product not found for CTX bootstrap render.",
                    context={"product_id": product_id, "tenant_key": tenant_key},
                )
            vision_inputs_hash = compute_vision_inputs_hash(product.vision_documents)
            return render_ctx_bootstrap(
                product_id=str(product.id),
                product_name=product.name,
                consolidated_vision_hash=product.consolidated_vision_hash,
                vision_inputs_hash=vision_inputs_hash,
                new_documents=new_documents,
            )

    async def update_project_metadata_for_mcp(
        self,
        project_id: str,
        name: str | None = None,
        description: str | None = None,
        status: str | None = None,
        tenant_key: str | None = None,
        project_type: str | None = None,
        series_number: int | None = None,
        subseries: str | None = None,
        websocket_manager: Any | None = None,
    ) -> dict[str, Any]:
        """Update project metadata via MCP tool (validation + active product enforcement).

        Pushed down from ToolAccessor.update_project_metadata (sprint 002f).
        """
        if not project_id or not project_id.strip():
            raise ValidationError(
                "Project ID is required and cannot be empty.",
                context={"operation": "update_project_metadata"},
            )
        project_id = project_id.strip()

        if all(v is None for v in (name, description, status, project_type, series_number, subseries)):
            raise ValidationError(
                "At least one field must be provided.",
                context={"operation": "update_project_metadata"},
            )

        if name is not None:
            name = name.strip()
            if len(name) > 200:
                raise ValidationError(
                    f"Name exceeds 200 character limit (got {len(name)}).",
                    context={"operation": "update_project_metadata"},
                )
            if not name:
                raise ValidationError(
                    "Name cannot be empty.",
                    context={"operation": "update_project_metadata"},
                )

        if description is not None and len(description) > 20000:
            raise ValidationError(
                f"Description exceeds 20000 character limit (got {len(description)}).",
                context={"operation": "update_project_metadata"},
            )

        if status is not None and status not in self._VALID_UPDATE_STATUSES:
            raise ValidationError(
                f"Invalid status '{status}'. Must be one of: {', '.join(sorted(self._VALID_UPDATE_STATUSES))}",
                context={"operation": "update_project_metadata"},
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
                context={"tenant_key": effective_tenant_key, "operation": "update_project_metadata"},
            )

        project = await self.get_project(project_id=project_id, tenant_key=effective_tenant_key)
        if project.product_id != active_product.id:
            raise ValidationError(
                "Project does not belong to the active product.",
                context={
                    "project_id": project_id,
                    "project_product_id": project.product_id,
                    "active_product_id": active_product.id,
                },
            )

        if project_type is not None:
            resolved_type = await self.get_project_type_by_label(project_type, effective_tenant_key)
            if resolved_type:
                project_type = resolved_type.id
            else:
                valid_types = await self._get_valid_project_types(effective_tenant_key)
                valid_labels = [t["abbreviation"] for t in valid_types]
                raise ValidationError(
                    f"Unknown project type '{project_type}'. "
                    f"Valid types: {', '.join(valid_labels)}. "
                    "Set project_type to one of these abbreviations or omit it.",
                    context={"operation": "update_project_metadata", "valid_types": valid_types},
                )

        if series_number is not None and (series_number < 1 or series_number > 9999):
            raise ValidationError(
                f"series_number must be 1-9999, got {series_number}.",
                context={"operation": "update_project_metadata"},
            )
        if subseries is not None and (len(subseries) != 1 or not subseries.isalpha() or not subseries.islower()):
            raise ValidationError(
                f"subseries must be a single lowercase letter (a-z), got '{subseries}'.",
                context={"operation": "update_project_metadata"},
            )

        # Duplicate taxonomy check when any taxonomy field changes
        if any(v is not None for v in (project_type, series_number, subseries)):
            check_type_id = project_type if project_type is not None else project.project_type_id
            check_series = series_number if series_number is not None else project.series_number
            check_subseries = subseries if subseries is not None else project.subseries
            async with self.db_manager.get_session_async() as session:
                is_dup = await self._repo.check_duplicate_taxonomy(
                    session,
                    effective_tenant_key,
                    project.product_id,
                    check_type_id,
                    check_series,
                    check_subseries,
                )
            if is_dup:
                raise AlreadyExistsError(
                    message="Taxonomy combination already in use. Please choose a different series number or suffix.",
                    context={"project_id": project_id},
                )

        updates: dict[str, Any] = {}
        if name is not None:
            updates["name"] = name
        if description is not None:
            updates["description"] = description
        if status is not None:
            updates["status"] = status
        if project_type is not None:
            updates["project_type_id"] = project_type
        if series_number is not None:
            updates["series_number"] = series_number
        if subseries is not None:
            updates["subseries"] = subseries

        try:
            updated = await self.update_project(project_id=project_id, updates=updates, websocket_manager=ws)
        except AlreadyExistsError as e:
            # BE-9016 (Sentry GILJOAI-BACKEND-A): the "single active project per
            # product" conflict is an EXPECTED, agent-actionable domain rejection
            # (BE-6081 Tier-2 carve-out) -- return it as structured content instead
            # of letting it raise to isError. The taxonomy-duplicate AlreadyExistsError
            # (a different, pre-existing rejection) is untouched by this branch and
            # keeps raising unchanged.
            if e.error_code == "ANOTHER_PROJECT_ACTIVE":
                return {
                    "success": False,
                    "error": "ANOTHER_PROJECT_ACTIVE",
                    "message": e.message,
                    "project_id": project_id,
                }
            raise

        return {
            "success": True,
            "project_id": updated.id,
            "name": updated.name,
            "description": updated.description,
            "status": updated.status,
            "updated_at": updated.updated_at,
            "message": f"Project '{updated.name}' updated successfully.",
        }
