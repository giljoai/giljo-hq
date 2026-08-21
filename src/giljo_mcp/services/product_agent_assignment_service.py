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

                # BE-9385a (load-bearing -- do not "simplify" this away).
                # Selection tolerance keys on ROW EXISTENCE: a product with no
                # junction rows falls back to the tenant-active set. So the first
                # toggle on such a product must not leave it holding exactly one
                # row -- that would switch tolerance off and collapse its active
                # set to a single agent (or to none, if the toggle was an OFF).
                # Materialising the currently-active set first makes the implicit
                # "all of them" explicit, so flipping one row changes exactly one
                # agent. Skip-existing, so an already-curated product is untouched
                # and a deliberate is_active=False row is never resurrected.
                await self._repo.bulk_assign_all_templates(session, product_id, self._tenant_key)

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

    async def include_in_active_product(self, session: AsyncSession, template_name: str) -> None:
        """Place a newly-usable agent in the tenant's ACTIVE product (BE-9391).

        BE-9385a made this junction authoritative for spawn, roster and export, and
        ``ce_0091`` backfilled a row for every (product, active template) pair -- so
        every pre-existing product is now "curated", and anything without a row is
        excluded from all three. Neither creating an agent nor switching it on
        tenant-wide was a junction writer, so an agent the user had just made was
        silently unspawnable, missing from the orchestrator's roster and never
        exported. This is the missing writer, and it lives here because this service
        owns the junction.

        MATERIALISE-then-include, NOT a single-row insert. Selection tolerance keys
        on row EXISTENCE (see ``product_agent_selection``): writing one row into a
        product that has none would flip tolerance OFF and collapse that product's
        active set to this one agent, removing every other agent from all three
        surfaces. :meth:`assign_all_templates` is skip-existing, so it makes the
        implicit "all of them" explicit and picks this agent up in the same pass,
        while never resurrecting a deliberate ``is_active=False`` row -- the same
        materialisation :meth:`toggle_assignment` performs, for the same reason.

        NO ACTIVE PRODUCT: deliberately does nothing (EM ruling, BE-9391). Both
        selection helpers return ``None`` when no product is active, so tolerance
        engages and the tenant-active set -- this agent included -- passes through
        every site unchanged. Writing rows for the tenant's INACTIVE products
        instead would curate products the user never touched, which is the "product
        goes dark" failure this feature exists to avoid. The gap self-heals:
        activation runs this same skip-existing pass.

        Call this ONLY for a user-initiated tenant-wide ACTIVATE. BE-9400 took the
        create path off this method -- creation now calls
        :meth:`place_in_active_product_switched_off` instead, because activation is
        an explicit user act and never a side effect of creating an agent.

        It must NOT be wired into ``TemplateService.add_and_commit_template`` to
        "cover more paths": ``template_import`` seeds through there, and ruling R2
        requires that a CE boot re-seed never auto-activate a seeded agent in an
        existing product.

        Best-effort by design, mirroring activation-time assignment
        (``product_lifecycle_service.py:202-207``): the caller has already committed
        the template, so raising here would fail the request for an agent that
        exists. A failure is logged at WARNING and healed by the next activation.

        Args:
            session: Caller-owned session, used only to read the active product.
            template_name: Name of the agent, for the warning log.
        """
        from giljo_mcp.repositories.product_repository import ProductRepository

        try:
            # eager_load=False: only the id is read, never the detail relations.
            product = await ProductRepository().get_active_product(session, self._tenant_key, eager_load=False)
            if product is None:
                return
            await self.assign_all_templates(product.id)
        except (BaseGiljoError, OSError, RuntimeError, ValueError, TypeError, AttributeError) as exc:
            self._logger.warning(
                "Could not assign agent '%s' to the active product (tenant=%s): %s. "
                "The agent exists; the next product activation picks it up.",
                sanitize(template_name),
                sanitize(self._tenant_key),
                exc,
            )

    async def place_in_active_product_switched_off(
        self, session: AsyncSession, template_id: str, template_name: str
    ) -> None:
        """Place a newly CREATED agent in the active product, switched OFF (BE-9400).

        The operator's ruling: activation is always an explicit user act, never a
        side effect of creation. A new agent is raw material to configure, so it
        arrives **available** (tenant ``is_active`` ON -- visible, editable) but
        **not live** in the product the user is working in.

        This replaces :meth:`include_in_active_product` on the CREATE path only.
        The tenant-wide switch-ON path still calls that one: flipping "Available in
        all products" back on is itself an explicit act, and BE-9391's
        create-then-activate guarantee rests on it.

        WHY THIS WRITES A ROW instead of simply not writing one. Selection
        tolerates a product with NO junction rows by falling back to the
        tenant-active set -- so on such a product, writing nothing would leave the
        new agent live anyway, through tolerance, and the ruling would hold only on
        already-curated products. Delegating to :meth:`toggle_assignment` gets the
        materialise-then-flip pass that makes "off" true in BOTH cases, and it is
        the same pass, with the same skip-existing guarantee, that the user's own
        toggle performs.

        It ACTIVATES NOTHING. The rows materialisation adds are ``is_active=True``
        for agents that were already live via tolerance -- the implicit set made
        explicit, no agent changing observable state -- and skip-existing means a
        deliberate ``is_active=False`` row is never resurrected (R2).

        NO ACTIVE PRODUCT: deliberately does nothing, exactly as
        :meth:`include_in_active_product` does. Writing rows for the tenant's
        INACTIVE products would curate products the user never touched, which is
        the "product goes dark" failure this feature exists to avoid.

        Best-effort by design, mirroring the include path: the caller has already
        committed the template, so raising here would fail the request for an agent
        that exists.

        Args:
            session: Caller-owned session, used only to read the active product.
            template_id: The newly created template's id.
            template_name: Name of the agent, for the warning log.
        """
        from giljo_mcp.repositories.product_repository import ProductRepository

        try:
            # eager_load=False: only the id is read, never the detail relations.
            product = await ProductRepository().get_active_product(session, self._tenant_key, eager_load=False)
            if product is None:
                return
            await self.toggle_assignment(product.id, template_id, is_active=False)
        except (BaseGiljoError, OSError, RuntimeError, ValueError, TypeError, AttributeError) as exc:
            self._logger.warning(
                "Could not place agent '%s' in the active product switched off (tenant=%s): %s. "
                "The agent exists; the user can switch it on for this product.",
                sanitize(template_name),
                sanitize(self._tenant_key),
                exc,
            )

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
