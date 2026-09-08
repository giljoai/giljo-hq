# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
ProductLifecycleService - Product lifecycle state management

Handover 0950n: Extracted from ProductService to keep all files under 1000 lines.

Responsibilities:
- Activate / deactivate products (FE-9524/D1: show/hide a tab; several
  products may be shown at once, no single-active-per-tenant rule)
- Soft delete, restore, and hard-purge products
- Auto-purge expired soft-deleted products on startup
"""

import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import (
    BaseGiljoError,
    DatabaseError,
    ResourceNotFoundError,
)
from giljo_mcp.models import Product
from giljo_mcp.repositories.product_repository import ProductRepository
from giljo_mcp.schemas.service_responses import DeleteResult, PurgeResult
from giljo_mcp.services._session_helpers import tenant_scoped_session
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)


class ProductLifecycleService:
    """
    Service for product lifecycle state transitions.

    Handles show/hide (activate/deactivate), soft delete, restore, hard purge,
    and automatic expiry purge.

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
        Initialize ProductLifecycleService.

        Args:
            db_manager: Database manager for async database operations
            tenant_key: Tenant key for multi-tenant isolation
            websocket_manager: Unused by this service (FE-9524 dropped its only
                caller); kept as a constructor param so ProductService's DI
                wiring does not need to branch per-service.
            test_session: Optional AsyncSession for tests to share the same transaction
        """
        self.db_manager = db_manager
        self.tenant_key = tenant_key
        self._test_session = test_session
        self._websocket_manager = websocket_manager
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._repo = ProductRepository()

    def _get_session(self):
        """Yield a tenant-scoped DB session, honoring an injected test session (shared helper, BE-8000d)."""
        return tenant_scoped_session(self.db_manager, self.tenant_key, self._test_session)

    async def activate_product(self, product_id: str) -> Product:
        """
        Show a product as a tab (FE-9524/D1: ``activate`` == "show").

        Several products may be shown at once -- there is no more sibling
        deactivation, no more pausing the shown product's own projects/jobs.
        ``idx_product_single_active_per_tenant`` is dropped (ce_0099); nothing
        in this method enforces single-active-product any more.

        FE-9529: ``ProductRepository.get_default_product``'s sole-shown-product
        fallback resolves a default ONLY while exactly one shown product
        exists and nothing has ``is_default`` persisted. Showing a SECOND
        product silently erases that fallback -- a tenant who never
        explicitly set a default would lose a working one the instant they
        show a second product, with nothing telling them. This is the ONE
        owning writer for "a product becomes shown" (dual-door rule -- REST
        and any future MCP tool both land here), so the promotion belongs
        here, not in a UI-layer caller: a caller that goes straight to this
        endpoint must get the same guarantee the dashboard does.

        Args:
            product_id: Product UUID to show

        Returns:
            Product ORM model after being shown

        Raises:
            ResourceNotFoundError: If product not found
            BaseGiljoError: If database operation fails
        """
        try:
            async with self._get_session() as session:
                product = await self._repo.get_by_id(session, self.tenant_key, product_id)

                if not product:
                    raise ResourceNotFoundError(
                        message="Product not found", context={"product_id": product_id, "tenant_key": self.tenant_key}
                    )

                # FE-9529: only the 1-shown -> 2+-shown transition can erase the
                # fallback (0 -> 1 has nothing resolved yet to lose; already
                # 2+ has already resolved via a real default or already lost
                # the fallback, neither of which this call can retroactively
                # fix). Checked BEFORE flipping is_active, and the promotion
                # (if any) commits in the SAME transaction as the activation
                # below -- a promotion that committed separately could half-
                # apply if the activation then failed.
                if not product.is_active:
                    currently_shown = await self._repo.count_active_products(session, self.tenant_key)
                    if currently_shown == 1:
                        implicit_default = await self._repo.get_default_product(
                            session, self.tenant_key, eager_load=False
                        )
                        if implicit_default is not None and not implicit_default.is_default:
                            implicit_default.is_default = True
                            implicit_default.updated_at = datetime.now(UTC)

                product.is_active = True
                product.updated_at = datetime.now(UTC)

                await session.commit()

                # BE-6066 P2: no post-commit refresh. The only HTTP caller discards
                # this return and re-hydrates via get_product(); sessions use
                # expire_on_commit=False so the manually-set is_active/updated_at
                # columns stay readable on the detached product. Dropping the
                # refresh removes a redundant SELECT + 4 relation selectin loads.
                self._logger.info(f"Showed product {sanitize(product_id)}")

                # Auto-assign all active tenant templates to the newly activated product.
                # This ensures every product starts with the full agent roster.
                # Uses its own session via the assignment repository (not the lifecycle session).
                try:
                    from giljo_mcp.repositories.product_agent_assignment_repository import (
                        ProductAgentAssignmentRepository,
                    )

                    assignment_repo = ProductAgentAssignmentRepository()
                    new_assignments = await assignment_repo.bulk_assign_all_templates(
                        session, product_id, self.tenant_key
                    )
                    if new_assignments:
                        await session.commit()
                        self._logger.info(
                            "Auto-assigned %d templates to product %s on activation",
                            len(new_assignments),
                            sanitize(product_id),
                        )
                except (OSError, RuntimeError, ValueError, TypeError, AttributeError) as exc:
                    # Non-fatal: product activation succeeded, assignment is best-effort
                    self._logger.warning(
                        "Failed to auto-assign templates on product activation (product_id=%s): %s",
                        sanitize(product_id),
                        exc,
                    )

                return product

        except ResourceNotFoundError:
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to activate product")
            raise BaseGiljoError(
                message=f"Failed to activate product: {e!s}",
                context={"product_id": product_id, "tenant_key": self.tenant_key},
            ) from e

    async def deactivate_product(self, product_id: str) -> Product:
        """
        Hide a product's tab (FE-9524/D1: ``deactivate`` == "hide").

        Hidden never means inaccessible (D2) and never means paused: this no
        longer touches the product's projects or jobs. Hiding is purely a
        tab-strip visibility toggle -- background work continues, which is
        the whole point of several tabs being open at once.

        Args:
            product_id: Product UUID to hide

        Returns:
            Product ORM model after being hidden

        Raises:
            ResourceNotFoundError: If product not found
            BaseGiljoError: If database operation fails
        """
        try:
            async with self._get_session() as session:
                product = await self._repo.get_by_id(session, self.tenant_key, product_id)

                if not product:
                    raise ResourceNotFoundError(
                        message="Product not found", context={"product_id": product_id, "tenant_key": self.tenant_key}
                    )

                product.is_active = False
                product.updated_at = datetime.now(UTC)

                await session.commit()
                await self._repo.refresh(session, product)

                self._logger.info(f"Hid product {sanitize(product_id)} (projects and jobs untouched)")

                return product

        except ResourceNotFoundError:
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to deactivate product")
            raise BaseGiljoError(
                message=f"Failed to deactivate product: {e!s}",
                context={"product_id": product_id, "tenant_key": self.tenant_key},
            ) from e

    async def get_default_product(self, *, eager_load: bool = True) -> Product | None:
        """
        Get the tenant's DEFAULT product -- where an unscoped read resolves.

        Renamed from ``get_active_product``:
        "shown" and "default" are two different questions once several
        products may be shown at once. See
        ``ProductRepository.get_default_product`` for the full rationale.

        Args:
            eager_load: BE-6066 P2 — when True (default), eager-load the 4 detail
                relations for response building. Pass False when only identity/
                columns are needed (e.g. reading the previously-default product's id
                during set_default_product) to skip four wasted selectin loads; the
                caller must not then read those relations off the returned model.

        Returns:
            Product ORM model if a default is set, None otherwise (legal state)

        Raises:
            BaseGiljoError: If database operation fails
        """
        try:
            async with self._get_session() as session:
                return await self._repo.get_default_product(session, self.tenant_key, eager_load=eager_load)

        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to get default product")
            raise BaseGiljoError(
                message=f"Failed to get default product: {e!s}", context={"tenant_key": self.tenant_key}
            ) from e

    async def set_default_product(self, product_id: str) -> Product:
        """
        Set the tenant's DEFAULT product, clearing any previous one.

        Independent of shown/hidden (``is_active``) -- D2 means a hidden
        product is still a fully valid default, so this does not check or
        touch ``is_active``. Unlike ``activate_product``, this never
        cascades to projects or jobs; it only ever moves one boolean flag.

        Args:
            product_id: Product UUID to make the default

        Returns:
            Product ORM model after being set as default

        Raises:
            ResourceNotFoundError: If product not found
            BaseGiljoError: If database operation fails
        """
        try:
            async with self._get_session() as session:
                product = await self._repo.get_by_id(session, self.tenant_key, product_id)
                if not product:
                    raise ResourceNotFoundError(
                        message="Product not found", context={"product_id": product_id, "tenant_key": self.tenant_key}
                    )

                others = await self._repo.find_other_default_products(session, self.tenant_key, product_id)
                for other in others:
                    other.is_default = False
                    other.updated_at = datetime.now(UTC)
                if others:
                    await self._repo.flush(session)

                product.is_default = True
                product.updated_at = datetime.now(UTC)

                await session.commit()

                self._logger.info(f"Set default product {sanitize(product_id)}")
                return product

        except ResourceNotFoundError:
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to set default product")
            raise BaseGiljoError(
                message=f"Failed to set default product: {e!s}",
                context={"product_id": product_id, "tenant_key": self.tenant_key},
            ) from e

    async def delete_product(self, product_id: str) -> DeleteResult:
        """
        Soft delete a product.

        Args:
            product_id: Product UUID to delete

        Returns:
            DeleteResult Pydantic model with deleted flag and timestamp

        Raises:
            ResourceNotFoundError: If product not found
            BaseGiljoError: If database operation fails
        """
        try:
            async with self._get_session() as session:
                product = await self._repo.get_by_id(session, self.tenant_key, product_id)

                if not product:
                    raise ResourceNotFoundError(
                        message="Product not found", context={"product_id": product_id, "tenant_key": self.tenant_key}
                    )

                product.deleted_at = datetime.now(UTC)
                product.is_active = False
                # FE-9524: idx_product_single_default_per_tenant has no
                # deleted_at clause (a deleted row's default flag still
                # counts), so a deleted default must be cleared here -- else
                # it permanently blocks any other product from ever becoming
                # the tenant's default (unique-index violation on the next
                # set_default_product call, even though reads already
                # tolerate "no default" via the deleted_at IS NULL filter).
                product.is_default = False
                product.updated_at = datetime.now(UTC)

                await session.commit()

                self._logger.info(f"Soft deleted product {product_id}")

                return DeleteResult(deleted=True, deleted_at=product.deleted_at)

        except ResourceNotFoundError:
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to delete product")
            raise BaseGiljoError(
                message=f"Failed to delete product: {e!s}",
                context={"product_id": product_id, "tenant_key": self.tenant_key},
            ) from e

    async def restore_product(self, product_id: str) -> Product:
        """
        Restore a soft-deleted product.

        Args:
            product_id: Product UUID to restore

        Returns:
            Product ORM model after restoration

        Raises:
            ResourceNotFoundError: If deleted product not found
            BaseGiljoError: If database operation fails
        """
        try:
            async with self._get_session() as session:
                product = await self._repo.get_deleted_by_id(session, self.tenant_key, product_id)

                if not product:
                    raise ResourceNotFoundError(
                        message="Deleted product not found",
                        context={"product_id": product_id, "tenant_key": self.tenant_key},
                    )

                product.deleted_at = None
                product.updated_at = datetime.now(UTC)

                await session.commit()
                await self._repo.refresh(session, product)

                self._logger.info(f"Restored product {product_id}")

                return product

        except ResourceNotFoundError:
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to restore product")
            raise BaseGiljoError(
                message=f"Failed to restore product: {e!s}",
                context={"product_id": product_id, "tenant_key": self.tenant_key},
            ) from e

    async def purge_product(self, product_id: str) -> dict:
        """
        Permanently delete a product and ALL related data (hard delete).

        Cascades via FK ondelete=CASCADE to: projects, tasks, tech_stacks,
        architectures, test_configs, vision_documents, product_memory_entries,
        context chunks.

        Args:
            product_id: Product UUID to permanently delete

        Returns:
            dict with product_name and message

        Raises:
            ResourceNotFoundError: If product not found
            BaseGiljoError: If database operation fails
        """
        try:
            async with self._get_session() as session:
                product = await self._repo.get_by_id(session, self.tenant_key, product_id, include_deleted=True)

                if not product:
                    raise ResourceNotFoundError(
                        message="Product not found",
                        context={"product_id": product_id, "tenant_key": self.tenant_key},
                    )

                product_name = product.name
                await self._repo.delete_hard(session, product)
                await session.commit()

                self._logger.info(f"Permanently deleted product {product_id} ({product_name})")

                return {"product_name": product_name, "message": f"Product '{product_name}' permanently deleted"}

        except ResourceNotFoundError:
            raise
        except Exception as e:  # Broad catch: service boundary, wraps unexpected errors in BaseGiljoError
            self._logger.exception("Failed to purge product")
            raise BaseGiljoError(
                message=f"Failed to permanently delete product: {e!s}",
                context={"product_id": product_id, "tenant_key": self.tenant_key},
            ) from e

    async def list_deleted_products(self) -> list[Product]:
        """
        List soft-deleted products for the tenant.

        Returns:
            List of Product ORM models (soft-deleted), ordered by deleted_at desc

        Raises:
            BaseGiljoError: If database operation fails
        """
        try:
            async with self._get_session() as session:
                return await self._repo.list_deleted(session, self.tenant_key)

        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("Failed to list deleted products")
            raise BaseGiljoError(
                message=f"Failed to list deleted products: {e!s}", context={"tenant_key": self.tenant_key}
            ) from e

    async def purge_expired_deleted_products(self, days_before_purge: int = 10) -> PurgeResult:
        """
        Hard delete products that were soft-deleted more than the specified number of days ago.

        SQLAlchemy cascade="all, delete-orphan" handles child relationships:
        projects, tasks, vision documents, etc.

        Called from startup.py on server start for automatic cleanup.

        Args:
            days_before_purge: Number of days before permanent deletion (default: 10)

        Returns:
            PurgeResult Pydantic model with purged_count and purged_ids

        Raises:
            DatabaseError: If database not available
            BaseGiljoError: If purge operation fails
        """
        if not self.db_manager:
            self._logger.error("[Product Purge] Cannot purge - database manager not available")
            raise DatabaseError(
                message="Database not available",
                context={"operation": "purge_expired_deleted_products", "tenant_key": self.tenant_key},
            )

        try:
            async with self._get_session() as session:
                expired_products = await self._repo.find_expired_deleted(session, days_before_purge)

                if not expired_products:
                    self._logger.info(
                        f"[Product Purge] No expired deleted products to purge (cutoff: {days_before_purge} days)"
                    )
                    return PurgeResult(purged_count=0, purged_ids=[])

                purged_ids = []
                for product in expired_products:
                    days_ago = (datetime.now(UTC) - product.deleted_at).days
                    purged_ids.append(str(product.id))

                    await self._repo.delete_hard(session, product)

                    self._logger.info(
                        f"[Product Purge] Auto-purged expired product {product.id} (deleted {days_ago} days ago)"
                    )

                await session.commit()

                self._logger.info(f"[Product Purge] Successfully purged {len(purged_ids)} expired deleted products")

                return PurgeResult(purged_count=len(purged_ids), purged_ids=purged_ids)

        except DatabaseError:
            raise
        except Exception as e:  # Broad catch: service boundary, wraps in BaseGiljoError
            self._logger.exception("[Product Purge] Failed to purge expired deleted products")
            raise BaseGiljoError(
                message=f"Failed to purge expired deleted products: {e!s}",
                context={
                    "operation": "purge_expired_deleted_products",
                    "tenant_key": self.tenant_key,
                    "days_before_purge": days_before_purge,
                },
            ) from e
