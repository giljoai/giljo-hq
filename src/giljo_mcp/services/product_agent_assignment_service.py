# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
ProductAgentAssignmentService - Per-product agent template toggle.

Manages the junction between products and tenant-wide agent templates.
Templates belong to the tenant; products reference which ones are active.
Think Spotify: songs exist once, playlists point to them.

Write discipline: All writes go through this service. No direct ORM writes
from endpoints or tools.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import (
    BaseGiljoError,
    ResourceNotFoundError,
    ValidationError,
)
from giljo_mcp.models.products import Product
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.repositories.product_agent_assignment_repository import (
    ProductAgentAssignmentRepository,
)
from giljo_mcp.services._session_helpers import tenant_scoped_session
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)

# Maximum length for UUID string parameters
_MAX_UUID_LENGTH = 36


class ProductAgentAssignmentService:
    """
    Service for managing product-agent template assignments.

    Enforces:
    - Tenant isolation on every operation
    - Input validation before DB writes
    - Write discipline (single write path)

    Thread Safety: Each instance is session-scoped. Do not share across requests.
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        tenant_key: str,
        test_session: AsyncSession | None = None,
    ):
        """
        Initialize ProductAgentAssignmentService.

        Args:
            db_manager: Database manager for async database operations
            tenant_key: Tenant key for multi-tenant isolation
            test_session: Optional AsyncSession for test transaction isolation
        """
        self._db_manager = db_manager
        self._tenant_key = tenant_key
        self._test_session = test_session
        self._repo = ProductAgentAssignmentRepository()
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def _get_session(self):
        """Yield a tenant-scoped DB session, honoring an injected test session (shared helper, BE-8000d)."""
        return tenant_scoped_session(self._db_manager, self._tenant_key, self._test_session)

    @staticmethod
    def _validate_uuid(value: str, field_name: str) -> None:
        """Validate a UUID string parameter.

        Args:
            value: String to validate
            field_name: Field name for error messages

        Raises:
            ValidationError: If validation fails
        """
        if not value or not isinstance(value, str):
            raise ValidationError(
                message=f"{field_name} is required and must be a string",
                context={"field": field_name},
            )
        if len(value) > _MAX_UUID_LENGTH:
            raise ValidationError(
                message=f"{field_name} exceeds maximum length ({_MAX_UUID_LENGTH})",
                context={"field": field_name, "length": len(value)},
            )

    # ========================================================================
    # Read operations
    # ========================================================================

    async def list_assignments(
        self,
        product_id: str,
        *,
        active_only: bool = False,
    ) -> list[dict[str, Any]]:
        """
        List all agent assignments for a product.

        Args:
            product_id: Product UUID
            active_only: If True, only return active assignments

        Returns:
            List of assignment dicts with template info

        Raises:
            ValidationError: If input validation fails
            BaseGiljoError: If operation fails
        """
        self._validate_uuid(product_id, "product_id")

        try:
            async with self._get_session() as session:
                assignments = await self._repo.get_assignments_for_product(
                    session, product_id, self._tenant_key, active_only=active_only
                )

                return [
                    {
                        "id": a.id,
                        "product_id": a.product_id,
                        "template_id": a.template_id,
                        "is_active": a.is_active,
                        "template_name": a.template.name if a.template else None,
                        "template_role": a.template.role if a.template else None,
                        "template_is_active": a.template.is_active if a.template else None,
                        "created_at": a.created_at.isoformat() if a.created_at else None,
                        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
                    }
                    for a in assignments
                ]
        except ValidationError:
            raise
        except Exception as e:
            self._logger.exception("Failed to list assignments for product %s", sanitize(product_id))
            raise BaseGiljoError(
                message=f"Failed to list assignments: {e!s}",
                context={"product_id": product_id, "tenant_key": self._tenant_key},
            ) from e

    async def get_active_template_ids(self, product_id: str) -> set[str]:
        """
        Get the set of active template IDs for a product.

        Useful for filtering template lists when product context is available.

        Args:
            product_id: Product UUID

        Returns:
            Set of active template IDs
        """
        self._validate_uuid(product_id, "product_id")

        async with self._get_session() as session:
            return await self._repo.get_active_template_ids_for_product(session, product_id, self._tenant_key)

    # ========================================================================
    # Write operations
    # ========================================================================

    async def toggle_assignment(
        self,
        product_id: str,
        template_id: str,
        is_active: bool,
    ) -> dict[str, Any]:
        """
        Toggle a template assignment for a product (create or update).

        Args:
            product_id: Product UUID
            template_id: Template UUID
            is_active: Whether the template should be active for this product

        Returns:
            Assignment dict with updated state

        Raises:
            ValidationError: If input validation fails
            ResourceNotFoundError: If template doesn't exist for tenant
            BaseGiljoError: If operation fails
        """
        self._validate_uuid(product_id, "product_id")
        self._validate_uuid(template_id, "template_id")

        if not isinstance(is_active, bool):
            raise ValidationError(
                message="is_active must be a boolean",
                context={"field": "is_active", "value": str(is_active)},
            )

        try:
            async with self._get_session() as session:
                # Verify the template belongs to this tenant and is not trashed.
                # BE-9334: ``deleted_at IS NULL`` is load-bearing. Soft-delete stamps
                # ``deleted_at`` and deliberately leaves ``is_active`` alone
                # (``template_service.py:720``), so an id-plus-tenant check matched
                # trashed rows and this endpoint created a junction row pointing at a
                # deleted agent instead of 404-ing. Same omission, same one-line
                # remedy, as the six sites BE-9325 fixed.
                template_check = await session.execute(
                    select(AgentTemplate.id).where(
                        and_(
                            AgentTemplate.id == template_id,
                            AgentTemplate.tenant_key == self._tenant_key,
                            AgentTemplate.deleted_at.is_(None),
                        )
                    )
                )
                if not template_check.scalar_one_or_none():
                    raise ResourceNotFoundError(
                        message=f"Template '{template_id}' not found for tenant",
                        context={"template_id": template_id, "tenant_key": self._tenant_key},
                    )

                # Verify the product belongs to this tenant
                product_check = await session.execute(
                    select(Product.id).where(
                        and_(
                            Product.id == product_id,
                            Product.tenant_key == self._tenant_key,
                        )
                    )
                )
                if not product_check.scalar_one_or_none():
                    raise ResourceNotFoundError(
                        message=f"Product '{product_id}' not found for tenant",
                        context={"product_id": product_id, "tenant_key": self._tenant_key},
                    )

                assignment = await self._repo.upsert_assignment(
                    session, product_id, template_id, self._tenant_key, is_active
                )
                await session.commit()

                self._logger.info(
                    "Toggled assignment: product=%s template=%s is_active=%s",
                    sanitize(product_id),
                    sanitize(template_id),
                    sanitize(is_active),
                )

                return {
                    "id": assignment.id,
                    "product_id": assignment.product_id,
                    "template_id": assignment.template_id,
                    "is_active": assignment.is_active,
                }

        except (ValidationError, ResourceNotFoundError):
            raise
        except Exception as e:
            self._logger.exception("Failed to toggle assignment")
            raise BaseGiljoError(
                message=f"Failed to toggle assignment: {e!s}",
                context={
                    "product_id": product_id,
                    "template_id": template_id,
                    "tenant_key": self._tenant_key,
                },
            ) from e

    async def assign_all_templates(self, product_id: str) -> int:
        """
        Assign all active tenant templates to a product.

        Called during product activation to default all agents as active.
        Skips templates that already have an assignment.

        Args:
            product_id: Product UUID

        Returns:
            Number of new assignments created

        Raises:
            ValidationError: If input validation fails
            BaseGiljoError: If operation fails
        """
        self._validate_uuid(product_id, "product_id")

        try:
            async with self._get_session() as session:
                new_assignments = await self._repo.bulk_assign_all_templates(session, product_id, self._tenant_key)
                await session.commit()

                count = len(new_assignments)
                self._logger.info(
                    "Assigned %d templates to product %s",
                    count,
                    product_id,
                )
                return count

        except ValidationError:
            raise
        except Exception as e:
            self._logger.exception("Failed to assign all templates to product %s", product_id)
            raise BaseGiljoError(
                message=f"Failed to assign all templates: {e!s}",
                context={"product_id": product_id, "tenant_key": self._tenant_key},
            ) from e

    async def remove_assignments(self, product_id: str) -> int:
        """
        Remove all assignments for a product.

        Args:
            product_id: Product UUID

        Returns:
            Number of assignments removed
        """
        self._validate_uuid(product_id, "product_id")

        try:
            async with self._get_session() as session:
                count = await self._repo.remove_assignments_for_product(session, product_id, self._tenant_key)
                await session.commit()
                return count

        except ValidationError:
            raise
        except Exception as e:
            self._logger.exception("Failed to remove assignments for product %s", product_id)
            raise BaseGiljoError(
                message=f"Failed to remove assignments: {e!s}",
                context={"product_id": product_id, "tenant_key": self._tenant_key},
            ) from e
