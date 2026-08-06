# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
ProductService - Dedicated service for product domain logic

Handover 0127b: Extract product operations from direct database access
to follow established service layer pattern.

Responsibilities:
- CRUD operations for products
- Product lifecycle management (activate, deactivate, archive, restore)
- Product metrics and statistics
- Vision document management
- Cascade impact analysis

Design Principles:
- Single Responsibility: Only product domain logic
- Dependency Injection: Accepts DatabaseManager and tenant_key
- Async/Await: Full SQLAlchemy 2.0 async support
- Error Handling: Consistent exception handling and logging
- Testability: Can be unit tested independently
"""

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import (
    BaseGiljoError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models import Product
from giljo_mcp.models.products import VALID_TARGET_PLATFORMS
from giljo_mcp.repositories.product_repository import ProductRepository
from giljo_mcp.schemas.jsonb_validators import validate_product_memory
from giljo_mcp.services._session_helpers import tenant_context_session
from giljo_mcp.services.product_field_map import assemble_update_kwargs
from giljo_mcp.services.product_lifecycle_service import ProductLifecycleService
from giljo_mcp.services.product_memory_service import ProductMemoryService
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)


# FE-9320: matches the String(500) products.project_path column.
PROJECT_PATH_MAX_LENGTH = 500

_ALLOWED_PRODUCT_FIELDS = {
    "name",
    "description",
    "project_path",
    "core_features",
    "brand_guidelines",
    "extraction_custom_instructions",
    "target_platforms",
    # BE-5117: aggregate-vision summaries are written via update_product_context MCP tool.
    "consolidated_vision_light",
    "consolidated_vision_light_tokens",
    "consolidated_vision_medium",
    "consolidated_vision_medium_tokens",
    "vision_analysis_complete",
}


class ProductService:
    """
    Service for managing product lifecycle and operations.

    This service handles all product-related operations including:
    - Creating, reading, updating, deleting products
    - Product activation/deactivation (single active product per tenant)
    - Product metrics and statistics
    - Vision document management
    - Quality standards updates (Handover 0316)
    - Cascade impact analysis for deletions

    Lifecycle state changes are delegated to ProductLifecycleService.
    Statistics and memory helpers are delegated to ProductMemoryService.

    Thread Safety: Each instance is session-scoped. Do not share across requests.
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        tenant_key: str,
        websocket_manager=None,
        test_session: AsyncSession | None = None,
    ):
        """
        Initialize ProductService with database and tenant isolation.

        Args:
            db_manager: Database manager for async database operations
            tenant_key: Tenant key for multi-tenant isolation
            websocket_manager: Optional WebSocket manager for event emission (Handover 0139a)
            test_session: Optional AsyncSession for tests to share the same transaction
        """
        self.db_manager = db_manager
        self.tenant_key = tenant_key
        self._test_session = test_session
        self._websocket_manager = websocket_manager
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._repo = ProductRepository()

        # Sprint 002f: Public sub-services for direct caller access (collapsed pass-throughs)
        self.lifecycle = ProductLifecycleService(
            db_manager=db_manager,
            tenant_key=tenant_key,
            websocket_manager=websocket_manager,
            test_session=test_session,
        )
        self.memory = ProductMemoryService(
            db_manager=db_manager,
            tenant_key=tenant_key,
            test_session=test_session,
        )

    # Shared product-field translator (BE-6225d). The single place that groups a flat
    # {column: value} mapping into update_product() kwargs (direct columns + relation
    # blocks). Both the vision-extraction writer and the context-tuning writer route
    # through this, so there is no longer a parallel block-grouping mapper per caller.
    # Implementation lives in services/product_field_map.py.
    assemble_update_kwargs = staticmethod(assemble_update_kwargs)

    def _get_session(self):
        """Yield a tenant-scoped DB session, honoring an injected test session (shared helper, BE-8000d)."""
        return tenant_context_session(self.db_manager, self.tenant_key, self._test_session)

    def _validate_target_platforms(self, target_platforms: list[str]) -> tuple[bool, str | None]:
        """
        Validate target_platforms field (Handover 0425).

        Args:
            target_platforms: List of platform values

        Returns:
            Tuple of (is_valid, error_message)

        Validation Rules:
            - All values must be in VALID_TARGET_PLATFORMS
            - If 'all' is present, it must be the only value
        """
        if not target_platforms:
            return False, "target_platforms cannot be empty"

        invalid_platforms = set(target_platforms) - VALID_TARGET_PLATFORMS

        if invalid_platforms:
            valid_list = ", ".join(sorted(VALID_TARGET_PLATFORMS))
            return False, f"Invalid platform values: {', '.join(sorted(invalid_platforms))}. Valid values: {valid_list}"

        if "all" in target_platforms and len(target_platforms) > 1:
            return False, "'all' platform cannot be combined with specific platforms"

        return True, None

    @staticmethod
    def _column_holds_a_value(value: Any) -> bool:
        """True when a config column already carries content worth protecting.

        NULL and whitespace-only text are treated as empty — a column the user has
        never filled must never block a write (FE-9320).
        """
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        return True

    def _collides_per_column(self, product: Product, incoming_blocks: dict[str, Any]) -> dict[str, list[str]]:
        """Return {block: [columns]} for incoming columns that already hold a value.

        FE-9320: the overwrite guard's granularity. A block whose relation row does
        not exist yet cannot collide at all; a block whose row exists collides only
        on the specific columns that are already populated.
        """
        collisions: dict[str, list[str]] = {}
        for block_name, incoming in incoming_blocks.items():
            if not incoming or not isinstance(incoming, dict):
                continue
            row = getattr(product, block_name, None)
            if row is None:
                continue
            clashing = [column for column in incoming if self._column_holds_a_value(getattr(row, column, None))]
            if clashing:
                collisions[block_name] = clashing
        return collisions

    def _validate_project_path(self, project_path: Any, *, operation: str, product_id: str | None = None) -> None:
        """Reject an over-length project_path at the owning-service write boundary.

        FE-9320: ``products.project_path`` is String(500) at the DB but the MCP tool
        boundary caps it at 20000, and nothing in between checked — so an over-long
        path became an opaque sanitized 500 instead of an actionable rejection.
        Mirrors the BE-9215 name cap.
        """
        if project_path is None or len(project_path) <= PROJECT_PATH_MAX_LENGTH:
            return
        context: dict[str, Any] = {"operation": operation}
        if product_id is not None:
            context["product_id"] = product_id
        raise ValidationError(
            message=(
                f"project_path exceeds {PROJECT_PATH_MAX_LENGTH} character limit "
                f"(got {len(project_path)}). Pass the repository folder path, not its contents."
            ),
            context=context,
        )

    # ============================================================================
    # CRUD Operations
    # ============================================================================

    async def create_product(
        self,
        name: str,
        description: str | None = None,
        project_path: str | None = None,
        tech_stack: dict[str, Any] | None = None,
        architecture: dict[str, Any] | None = None,
        test_config: dict[str, Any] | None = None,
        core_features: str | None = None,
        brand_guidelines: str | None = None,
        product_memory: dict[str, Any] | None = None,
        target_platforms: list[str] | None = None,
    ) -> Product:
        """
        Create a new product.

        Handover 0840i: Accepts normalized config fields directly instead of config_data dict.

        Args:
            name: Product name (required)
            description: Product description
            project_path: File system path to product folder
            tech_stack: Tech stack configuration dict
            architecture: Architecture configuration dict
            test_config: Test configuration dict
            core_features: Core product features string
            product_memory: 360 Memory data (git integration, sequential_history, context) - Handover 0135
            target_platforms: Target platforms (windows, linux, macos, android, ios, web, or all) - Handover 0425

        Returns:
            Product ORM model after commit and refresh

        Raises:
            ValidationError: If target_platforms invalid or product name already exists
            BaseGiljoError: If database operation fails
        """
        try:
            # BE-9215: name column is String(255). Cap at the owning-service write
            # so every transport (REST, MCP create_product, vision extraction) gets
            # a clean 422 instead of a raw StringDataRightTruncation 500.
            if name is not None and len(name) > 255:
                raise ValidationError(
                    message=f"Product name exceeds 255 character limit (got {len(name)}).",
                    context={"operation": "create_product"},
                )
            self._validate_project_path(project_path, operation="create_product")
            if target_platforms is not None:
                is_valid, error_msg = self._validate_target_platforms(target_platforms)
                if not is_valid:
                    raise ValidationError(message=error_msg, context={"target_platforms": target_platforms})

            async with self._get_session() as session:
                existing = await self._repo.get_by_name(session, self.tenant_key, name)
                if existing:
                    raise ValidationError(
                        message=f"Product '{name}' already exists",
                        context={"product_name": name, "tenant_key": self.tenant_key},
                    )

                # Handover 0135 + 0700c: Initialize product_memory (history in table)
                # BE-9261: seed key renamed github -> git_integration (server_default
                # column left untouched; _ensure_product_memory_initialized backfills
                # existing rows, and the git_integration-preferred/github-legacy read
                # fallback in _build_product_memory_response covers pre-rename rows).
                default_memory = {
                    "git_integration": {},
                    "context": {},
                }

                product_id = str(uuid4())

                validated_memory = validate_product_memory(product_memory) or default_memory
                product = Product(
                    id=product_id,
                    tenant_key=self.tenant_key,
                    name=name,
                    description=description,
                    project_path=project_path,
                    core_features=core_features,
                    brand_guidelines=brand_guidelines,
                    product_memory=validated_memory,
                    target_platforms=target_platforms or ["all"],
                    is_active=False,
                    created_at=datetime.now(UTC),
                )

                await self._repo.add(session, product)

                # Handover 0840i: Create normalized config table rows from typed fields
                config_parts = {}
                if tech_stack:
                    config_parts["tech_stack"] = tech_stack
                if architecture:
                    config_parts["architecture"] = architecture
                if test_config:
                    config_parts["test_config"] = test_config
                if config_parts:
                    await self._repo.create_config_relations(session, product_id, self.tenant_key, config_parts)

                await session.commit()
                await self._repo.refresh(session, product)

                self._logger.info(f"Created product {product.id} for tenant {self.tenant_key}")

                return product

        except ValidationError:
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to create product")
            raise BaseGiljoError(
                message=f"Failed to create product: {e!s}",
                context={"product_name": name, "tenant_key": self.tenant_key},
            ) from e

    async def get_product(self, product_id: str) -> Product:
        """
        Get a specific product by ID.

        Args:
            product_id: Product UUID

        Returns:
            Product ORM model

        Raises:
            ResourceNotFoundError: If product not found
            BaseGiljoError: If database operation fails
        """
        try:
            async with self._get_session() as session:
                product = await self._repo.get_by_id(session, self.tenant_key, product_id, eager_load=True)

                if not product:
                    raise ResourceNotFoundError(
                        message="Product not found", context={"product_id": product_id, "tenant_key": self.tenant_key}
                    )

                # Handover 0136: Ensure product_memory is initialized (backward compatibility)
                await self.memory._ensure_product_memory_initialized(session, product)

                # Handover 0412: Force refresh to ensure we have latest DB data
                # Handover 0840h: Include relationships so refresh doesn't discard eager loads
                await self._repo.refresh(session, product)

                return product

        except ResourceNotFoundError:
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to get product")
            raise BaseGiljoError(
                message=f"Failed to get product: {e!s}",
                context={"product_id": product_id, "tenant_key": self.tenant_key},
            ) from e

    async def list_products(self, include_inactive: bool = False, lean: bool = False) -> list[Product]:
        """
        List all products for tenant with optional filtering.

        Args:
            include_inactive: Include inactive products (default: False)
            lean: BE-6066 P4 — when True, skip eager-loading the 4 detail relations
                (the lean products LIST serializes only columns + aggregates). The
                caller MUST NOT read tech_stack / architecture / test_config /
                vision_documents off the returned models in lean mode.

        Returns:
            List of Product ORM models

        Raises:
            BaseGiljoError: If database operation fails
        """
        try:
            async with self._get_session() as session:
                products = await self._repo.list_products(
                    session, self.tenant_key, include_inactive=include_inactive, lean=lean
                )

                for product in products:
                    # Handover 0136: Ensure product_memory is initialized (backward compatibility)
                    await self.memory._ensure_product_memory_initialized(session, product)

                self._logger.debug(f"Found {len(products)} products for tenant {self.tenant_key}")

                return products

        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to list products")
            raise BaseGiljoError(
                message=f"Failed to list products: {e!s}", context={"tenant_key": self.tenant_key}
            ) from e

    async def update_product(self, product_id: str, force: bool = False, **updates) -> Product:
        """
        Update a product.

        Args:
            product_id: Product UUID
            force: If True, allow overwriting populated JSONB fields (tech_stack, architecture, test_config)
            **updates: Fields to update (name, description, project_path, tech_stack, architecture,
                test_config, core_features, product_memory, target_platforms, etc.)

        Returns:
            Product ORM model after commit and refresh

        Raises:
            ResourceNotFoundError: If product not found
            ValidationError: If product is not active, target_platforms invalid, or JSONB fields
                already populated without force=True
            BaseGiljoError: If database operation fails
        """
        try:
            # BE-9215: name column is String(255). Reject an over-long rename with
            # a clean 422 at the write boundary rather than a DB truncation 500.
            if updates.get("name") is not None and len(updates["name"]) > 255:
                raise ValidationError(
                    message=f"Product name exceeds 255 character limit (got {len(updates['name'])}).",
                    context={"product_id": product_id},
                )
            self._validate_project_path(updates.get("project_path"), operation="update_product", product_id=product_id)
            if "target_platforms" in updates:
                is_valid, error_msg = self._validate_target_platforms(updates["target_platforms"])
                if not is_valid:
                    raise ValidationError(message=error_msg, context={"target_platforms": updates["target_platforms"]})

            async with self._get_session() as session:
                product = await self._repo.get_by_id(session, self.tenant_key, product_id, eager_load=True)

                if not product:
                    raise ResourceNotFoundError(
                        message="Product not found", context={"product_id": product_id, "tenant_key": self.tenant_key}
                    )

                # Note: Active product guard removed — blocking users from editing their own
                # products has no valid use case. Overwrite confirmation (WI-2) is sufficient
                # protection against agents accidentally clobbering populated fields.

                # Handover 0840i: Handle normalized config fields
                tech_stack = updates.pop("tech_stack", None)
                architecture_data = updates.pop("architecture", None)
                test_config = updates.pop("test_config", None)
                core_features = updates.pop("core_features", None)

                # WI-2: Overwrite Confirmation — prevent accidental overwrites of populated
                # config fields. FE-9320: the guard used to fire on the relation ROW existing
                # (``product.tech_stack is not None``), but that row is created by the FIRST
                # write, so every later repair call had its whole block rejected — discarding
                # columns that were still EMPTY. It now compares COLUMN by COLUMN: only the
                # columns that actually hold a value collide, and the rest of the block writes.
                if not force:
                    populated_columns = self._collides_per_column(
                        product,
                        {
                            "tech_stack": tech_stack,
                            "architecture": architecture_data,
                            "test_config": test_config,
                        },
                    )
                    if populated_columns:
                        detail = "; ".join(
                            f"{block}: {', '.join(columns)}" for block, columns in populated_columns.items()
                        )
                        raise ValidationError(
                            message=f"Fields already populated: {detail}. Pass force=True to overwrite.",
                            # populated_fields stays the block-name list every existing caller
                            # reads; populated_columns carries the per-column detail.
                            context={
                                "populated_fields": list(populated_columns),
                                "populated_columns": populated_columns,
                                "product_id": product_id,
                            },
                        )

                if core_features is not None:
                    product.core_features = core_features

                config_parts = {}
                if tech_stack and isinstance(tech_stack, dict):
                    config_parts["tech_stack"] = tech_stack
                if architecture_data and isinstance(architecture_data, dict):
                    config_parts["architecture"] = architecture_data
                if test_config and isinstance(test_config, dict):
                    config_parts["test_config"] = test_config
                if config_parts:
                    await self._repo.update_config_relations(session, product, self.tenant_key, config_parts)

                for field, value in updates.items():
                    if field in _ALLOWED_PRODUCT_FIELDS:
                        setattr(product, field, value)

                product.updated_at = datetime.now(UTC)

                await session.commit()
                await self._repo.refresh(session, product)

                self._logger.info(f"Updated product {sanitize(product_id)}")

                # TSK-9265: no product:memory:updated emit here. product_memory is
                # not in _ALLOWED_PRODUCT_FIELDS, so this method never applies it —
                # the removed emit keyed on the RAW input dict and broadcast stale
                # memory for a silently-dropped field. The owning write paths
                # (write_memory_entry / project closeout) emit their own event.

                return product

        except (ResourceNotFoundError, ValidationError):
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to update product")
            raise BaseGiljoError(
                message=f"Failed to update product: {e!s}",
                context={"product_id": product_id, "tenant_key": self.tenant_key},
            ) from e

    # ============================================================================
    # Lifecycle Management -- delegated to ProductLifecycleService
    # ============================================================================

    async def activate_product(self, product_id: str) -> Product:
        """Activate a product (deactivates other products for tenant). Delegated to ProductLifecycleService."""
        return await self.lifecycle.activate_product(product_id)

    async def deactivate_product(self, product_id: str) -> Product:
        """Deactivate a product. Delegated to ProductLifecycleService."""
        return await self.lifecycle.deactivate_product(product_id)

    # ============================================================================
    # Active Product Management
    # ============================================================================

    async def get_active_product(self, *, eager_load: bool = True) -> Product | None:
        """
        Get the currently active product for the tenant.

        Args:
            eager_load: BE-6066 P2 — when True (default), eager-load the 4 detail
                relations for response building. Pass False when only identity/
                columns are needed (e.g. reading the previously-active product's id
                during activate) to skip four wasted selectin loads; the caller must
                not then read those relations off the returned model.

        Returns:
            Product ORM model if active product exists, None otherwise

        Raises:
            BaseGiljoError: If database operation fails
        """
        try:
            async with self._get_session() as session:
                return await self._repo.get_active_product(session, self.tenant_key, eager_load=eager_load)

        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to get active product")
            raise BaseGiljoError(
                message=f"Failed to get active product: {e!s}", context={"tenant_key": self.tenant_key}
            ) from e
