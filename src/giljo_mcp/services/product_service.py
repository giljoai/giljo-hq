# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import (
    BaseGiljoError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models import Product
from giljo_mcp.models.products import VALID_TARGET_PLATFORMS
from giljo_mcp.product_slug import slugify_product_name
from giljo_mcp.repositories.product_repository import ProductRepository
from giljo_mcp.schemas.jsonb_validators import validate_product_memory
from giljo_mcp.services._session_helpers import tenant_context_session
from giljo_mcp.services.product_field_map import assemble_update_kwargs
from giljo_mcp.services.product_lifecycle_service import ProductLifecycleService
from giljo_mcp.services.product_memory_service import ProductMemoryService
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)


class ProductAmbiguousError(ValidationError):

    code = "PRODUCT_AMBIGUOUS"

    def __init__(self, *, products: list[dict[str, Any]], operation: str, tenant_key: str) -> None:
        lines = "\n".join(f"- {p['name']} (id={p['id']}, active={p['is_active']})" for p in products)
        message = (
            "Multiple products exist and none was specified. Your products:\n"
            f"{lines}\n"
            "Retry with product_id. In a local repo, persist the binding by calling "
            "giljo_setup with product_id -- it writes the binding into CLAUDE.md/AGENTS.md "
            "so this never asks again. In a web session, pass product_id per call."
        )
        super().__init__(message, context={"operation": operation, "tenant_key": tenant_key, "products": products})
        self.products = products


PROJECT_PATH_MAX_LENGTH = 500

_ALLOWED_PRODUCT_FIELDS = {
    "name",
    "description",
    "project_path",
    "core_features",
    "brand_guidelines",
    "extraction_custom_instructions",
    "target_platforms",
    "consolidated_vision_light",
    "consolidated_vision_light_tokens",
    "consolidated_vision_medium",
    "consolidated_vision_medium_tokens",
    "vision_analysis_complete",
}


class ProductService:

    def __init__(
        self,
        db_manager: DatabaseManager,
        tenant_key: str,
        websocket_manager=None,
        test_session: AsyncSession | None = None,
    ):
        self.db_manager = db_manager
        self.tenant_key = tenant_key
        self._test_session = test_session
        self._websocket_manager = websocket_manager
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._repo = ProductRepository()

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

    assemble_update_kwargs = staticmethod(assemble_update_kwargs)

    def _get_session(self):
        return tenant_context_session(self.db_manager, self.tenant_key, self._test_session)

    async def _emit_websocket_event(self, event_type: str, data: dict[str, Any]) -> None:
        if not self._websocket_manager:
            return
        try:
            await self._websocket_manager.broadcast_to_tenant(
                tenant_key=self.tenant_key,
                event_type=event_type,
                data={**data, "tenant_key": self.tenant_key},
            )
        except (RuntimeError, ValueError) as e:
            self._logger.warning(f"Failed to emit WebSocket event {event_type}: {e}", exc_info=True)

    def _validate_target_platforms(self, target_platforms: list[str]) -> tuple[bool, str | None]:
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
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        return True

    def _collides_per_column(self, product: Product, incoming_blocks: dict[str, Any]) -> dict[str, list[str]]:
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


    async def _allocate_product_slug(self, session, name: str) -> str:
        base = slugify_product_name(name)

        stmt = select(Product.slug).where(
            Product.tenant_key == self.tenant_key,
            Product.deleted_at.is_(None),
            Product.slug.is_not(None),
        )
        taken = set((await session.execute(stmt)).scalars().all())

        if base not in taken:
            return base
        for suffix in range(2, 1000):
            candidate = f"{base}-{suffix}"
            if candidate not in taken:
                return candidate
        return f"{base}-{uuid4().hex[:8]}"

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
        try:
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

                default_memory = {
                    "git_integration": {},
                    "context": {},
                }

                product_id = str(uuid4())

                slug = await self._allocate_product_slug(session, name)

                validated_memory = validate_product_memory(product_memory) or default_memory
                product = Product(
                    id=product_id,
                    tenant_key=self.tenant_key,
                    name=name,
                    slug=slug,
                    description=description,
                    project_path=project_path,
                    core_features=core_features,
                    brand_guidelines=brand_guidelines,
                    product_memory=validated_memory,
                    target_platforms=target_platforms or ["all"],
                    is_active=True,
                    created_at=datetime.now(UTC),
                )

                await self._repo.add(session, product)

                config_parts = {}
                if tech_stack:
                    config_parts["tech_stack"] = tech_stack
                if architecture:
                    config_parts["architecture"] = architecture
                if test_config:
                    config_parts["test_config"] = test_config
                if config_parts:
                    await self._repo.create_config_relations(session, product_id, self.tenant_key, config_parts)

                from giljo_mcp.product_crew import seed_product_crew

                crew = await seed_product_crew(session, self.tenant_key, product_id)
                await session.commit()
                await self._repo.refresh(session, product)

                self._logger.info(f"Created product {product.id} for tenant {self.tenant_key}, {len(crew)} agent(s)")

                await self._emit_websocket_event(
                    event_type="product:created",
                    data={"product_id": str(product.id), "name": product.name},
                )

                return product

        except ValidationError:
            raise
        except Exception as e:
            self._logger.exception("Failed to create product")
            raise BaseGiljoError(
                message=f"Failed to create product: {e!s}",
                context={"product_name": name, "tenant_key": self.tenant_key},
            ) from e

    async def get_product(self, product_id: str) -> Product:
        try:
            async with self._get_session() as session:
                product = await self._repo.get_by_id(session, self.tenant_key, product_id, eager_load=True)

                if not product:
                    raise ResourceNotFoundError(
                        message="Product not found", context={"product_id": product_id, "tenant_key": self.tenant_key}
                    )

                await self.memory._ensure_product_memory_initialized(session, product)

                await self._repo.refresh(session, product)

                return product

        except ResourceNotFoundError:
            raise
        except Exception as e:
            self._logger.exception("Failed to get product")
            raise BaseGiljoError(
                message=f"Failed to get product: {e!s}",
                context={"product_id": product_id, "tenant_key": self.tenant_key},
            ) from e

    async def list_products(self, include_inactive: bool = False, lean: bool = False) -> list[Product]:
        try:
            async with self._get_session() as session:
                products = await self._repo.list_products(
                    session, self.tenant_key, include_inactive=include_inactive, lean=lean
                )

                for product in products:
                    await self.memory._ensure_product_memory_initialized(session, product)

                self._logger.debug(f"Found {len(products)} products for tenant {self.tenant_key}")

                return products

        except Exception as e:
            self._logger.exception("Failed to list products")
            raise BaseGiljoError(
                message=f"Failed to list products: {e!s}", context={"tenant_key": self.tenant_key}
            ) from e

    async def update_product(self, product_id: str, force: bool = False, **updates) -> Product:
        try:
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


                tech_stack = updates.pop("tech_stack", None)
                architecture_data = updates.pop("architecture", None)
                test_config = updates.pop("test_config", None)
                core_features = updates.pop("core_features", None)

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


                await self._emit_websocket_event(
                    event_type="product:updated",
                    data={"product_id": str(product.id), "name": product.name},
                )

                return product

        except (ResourceNotFoundError, ValidationError):
            raise
        except Exception as e:
            self._logger.exception("Failed to update product")
            raise BaseGiljoError(
                message=f"Failed to update product: {e!s}",
                context={"product_id": product_id, "tenant_key": self.tenant_key},
            ) from e


    async def activate_product(self, product_id: str) -> Product:
        return await self.lifecycle.activate_product(product_id)

    async def deactivate_product(self, product_id: str) -> Product:
        return await self.lifecycle.deactivate_product(product_id)


    async def get_default_product(self, *, eager_load: bool = True) -> Product | None:
        return await self.lifecycle.get_default_product(eager_load=eager_load)

    async def set_default_product(self, product_id: str) -> Product:
        return await self.lifecycle.set_default_product(product_id)

    async def resolve_binding_product(
        self, product_id: str | None, *, operation: str, action: str = "created", write: bool
    ) -> Product:
        if not product_id or not str(product_id).strip():
            if write:
                products = await self.list_products(include_inactive=True, lean=True)
                if len(products) > 1:
                    raise ProductAmbiguousError(
                        products=[{"id": str(p.id), "name": p.name, "is_active": bool(p.is_active)} for p in products],
                        operation=operation,
                        tenant_key=self.tenant_key,
                    )
            default_product = await self.get_default_product(eager_load=False)
            if not default_product:
                raise ValidationError(
                    "No default product is set, so an unscoped read has nowhere to resolve to. "
                    "Pass product_id explicitly -- get_context(categories=['products']) lists your "
                    "products and their ids. Choosing which product is the default is a dashboard "
                    "action; there is no tool for it.",
                    context={"tenant_key": self.tenant_key, "operation": operation},
                )
            return default_product

        requested_id = str(product_id).strip()
        async with self._get_session() as session:
            product = await self._repo.get_by_id(session, self.tenant_key, requested_id, eager_load=False)

        if product is None:
            raise ValidationError(
                f"Product '{requested_id}' was not found for this account, so nothing was {action}. "
                "Pass the product_id of one of your own products -- get_context(categories=['products']) "
                "lists them with their ids.",
                context={"product_id": requested_id, "tenant_key": self.tenant_key, "operation": operation},
            )
        return product
