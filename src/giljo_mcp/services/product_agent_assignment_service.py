# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import (
    BaseGiljoError,
    ProjectStateError,
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

_MAX_UUID_LENGTH = 36


class ProductAgentAssignmentService:

    def __init__(
        self,
        db_manager: DatabaseManager,
        tenant_key: str,
        test_session: AsyncSession | None = None,
    ):
        self._db_manager = db_manager
        self._tenant_key = tenant_key
        self._test_session = test_session
        self._repo = ProductAgentAssignmentRepository()
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def _get_session(self):
        return tenant_scoped_session(self._db_manager, self._tenant_key, self._test_session)

    @staticmethod
    def _validate_uuid(value: str, field_name: str) -> None:
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


    async def list_assignments(
        self,
        product_id: str,
        *,
        active_only: bool = False,
    ) -> list[dict[str, Any]]:
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


    async def toggle_assignment(
        self,
        product_id: str,
        template_id: str,
        is_active: bool,
    ) -> dict[str, Any]:
        self._validate_uuid(product_id, "product_id")
        self._validate_uuid(template_id, "template_id")

        if not isinstance(is_active, bool):
            raise ValidationError(
                message="is_active must be a boolean",
                context={"field": "is_active", "value": str(is_active)},
            )

        try:
            async with self._get_session() as session:
                template_check = await session.execute(
                    select(AgentTemplate.id, AgentTemplate.role, AgentTemplate.product_id).where(
                        and_(
                            AgentTemplate.id == template_id,
                            AgentTemplate.tenant_key == self._tenant_key,
                            AgentTemplate.deleted_at.is_(None),
                        )
                    )
                )
                template_row = template_check.first()
                if not template_row:
                    raise ResourceNotFoundError(
                        message=f"Template '{template_id}' not found for tenant",
                        context={"template_id": template_id, "tenant_key": self._tenant_key},
                    )

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

                owner_id = template_row[2]
                if owner_id and owner_id != product_id:
                    self._logger.info(
                        "Refused cross-product assignment: template=%s requested_product=%s owner_product=%s",
                        template_id,
                        product_id,
                        owner_id,
                    )
                    raise ValidationError(
                        message=(
                            "That agent belongs to a different product. Agents are not shared -- "
                            "create one in this product instead."
                        ),
                        context={"template_id": template_id, "product_id": product_id},
                    )

                if is_active:
                    await self._enforce_context_budget(session, product_id, template_id, template_row[1])

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

        except (ValidationError, ResourceNotFoundError, ProjectStateError):
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

    async def _enforce_context_budget(
        self,
        session: AsyncSession,
        product_id: str,
        template_id: str,
        role: str | None,
    ) -> None:
        from giljo_mcp.services.template_service import USER_MANAGED_AGENT_LIMIT
        from giljo_mcp.system_roles import SYSTEM_MANAGED_ROLES

        if not role or role in SYSTEM_MANAGED_ROLES:
            return

        enabled_roles = await self._repo.get_enabled_distinct_roles(
            session, product_id, self._tenant_key, exclude_template_id=template_id
        )
        if role in enabled_roles:
            return

        if len(enabled_roles) >= USER_MANAGED_AGENT_LIMIT:
            raise ProjectStateError(
                message=(
                    f"Maximum {USER_MANAGED_AGENT_LIMIT} active agent roles allowed for this product "
                    f"(currently {len(enabled_roles)}). Switch another role off first."
                ),
                context={"product_id": product_id, "role": role, "limit": USER_MANAGED_AGENT_LIMIT},
            )

    async def enable_for_product(
        self,
        session: AsyncSession,
        product_id: str,
        template_ids: list[str],
    ) -> int:
        self._validate_uuid(product_id, "product_id")
        created = await self._repo.enable_templates_for_product(
            session, product_id, self._tenant_key, list(template_ids)
        )
        return len(created)

    async def remove_assignments(self, product_id: str) -> int:
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
