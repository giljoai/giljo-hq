# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager, tenant_session_context
from giljo_mcp.exceptions import (
    BaseGiljoError,
    DatabaseError,
    ResourceNotFoundError,
)
from giljo_mcp.models import Product
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.repositories.product_repository import ProductRepository
from giljo_mcp.schemas.service_responses import DeleteResult, PurgeResult
from giljo_mcp.services._session_helpers import tenant_scoped_session
from giljo_mcp.template_validation import crew_suffixed_names
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)


class ProductLifecycleService:

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

    def _get_session(self):
        return tenant_scoped_session(self.db_manager, self.tenant_key, self._test_session)

    async def activate_product(self, product_id: str) -> Product:
        try:
            async with self._get_session() as session:
                product = await self._repo.get_by_id(session, self.tenant_key, product_id)

                if not product:
                    raise ResourceNotFoundError(
                        message="Product not found", context={"product_id": product_id, "tenant_key": self.tenant_key}
                    )

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

                self._logger.info(f"Showed product {sanitize(product_id)}")


                return product

        except ResourceNotFoundError:
            raise
        except Exception as e:
            self._logger.exception("Failed to activate product")
            raise BaseGiljoError(
                message=f"Failed to activate product: {e!s}",
                context={"product_id": product_id, "tenant_key": self.tenant_key},
            ) from e

    async def deactivate_product(self, product_id: str) -> Product:
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
        except Exception as e:
            self._logger.exception("Failed to deactivate product")
            raise BaseGiljoError(
                message=f"Failed to deactivate product: {e!s}",
                context={"product_id": product_id, "tenant_key": self.tenant_key},
            ) from e

    async def get_default_product(self, *, eager_load: bool = True) -> Product | None:
        try:
            async with self._get_session() as session:
                return await self._repo.get_default_product(session, self.tenant_key, eager_load=eager_load)

        except Exception as e:
            self._logger.exception("Failed to get default product")
            raise BaseGiljoError(
                message=f"Failed to get default product: {e!s}", context={"tenant_key": self.tenant_key}
            ) from e

    async def set_default_product(self, product_id: str) -> Product:
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
        except Exception as e:
            self._logger.exception("Failed to set default product")
            raise BaseGiljoError(
                message=f"Failed to set default product: {e!s}",
                context={"product_id": product_id, "tenant_key": self.tenant_key},
            ) from e

    async def delete_product(self, product_id: str) -> DeleteResult:
        try:
            async with self._get_session() as session:
                product = await self._repo.get_by_id(session, self.tenant_key, product_id)

                if not product:
                    raise ResourceNotFoundError(
                        message="Product not found", context={"product_id": product_id, "tenant_key": self.tenant_key}
                    )

                deleted_at = datetime.now(UTC)
                trashed = await self._trash_owned_templates(session, product_id, deleted_at)

                product.deleted_at = deleted_at
                product.is_active = False
                product.is_default = False
                product.updated_at = deleted_at

                await session.commit()

                self._logger.info("Soft deleted product %s with %d owned agent(s)", sanitize(product_id), trashed)

                return DeleteResult(deleted=True, deleted_at=product.deleted_at)

        except ResourceNotFoundError:
            raise
        except Exception as e:
            self._logger.exception("Failed to delete product")
            raise BaseGiljoError(
                message=f"Failed to delete product: {e!s}",
                context={"product_id": product_id, "tenant_key": self.tenant_key},
            ) from e

    async def restore_product(self, product_id: str) -> Product:
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

                restored = await self._restore_owned_templates(session, product_id)

                await session.commit()
                await self._repo.refresh(session, product)

                self._logger.info("Restored product %s with %d owned agent(s)", sanitize(product_id), restored)

                return product

        except ResourceNotFoundError:
            raise
        except Exception as e:
            self._logger.exception("Failed to restore product")
            raise BaseGiljoError(
                message=f"Failed to restore product: {e!s}",
                context={"product_id": product_id, "tenant_key": self.tenant_key},
            ) from e

    async def _trash_owned_templates(self, session: AsyncSession, product_id: str, deleted_at: datetime) -> int:
        stmt = (
            sql_update(AgentTemplate.__table__)
            .where(
                AgentTemplate.__table__.c.product_id == product_id,
                AgentTemplate.__table__.c.tenant_key == self.tenant_key,
                AgentTemplate.__table__.c.deleted_at.is_(None),
            )
            .values(deleted_at=deleted_at)
        )
        with tenant_session_context(session, self.tenant_key):
            result = await session.execute(stmt)
        return result.rowcount or 0

    async def _restore_owned_templates(self, session: AsyncSession, product_id: str) -> int:
        stmt = select(AgentTemplate).where(
            AgentTemplate.product_id == product_id,
            AgentTemplate.tenant_key == self.tenant_key,
            AgentTemplate.deleted_at.isnot(None),
        )
        with tenant_session_context(session, self.tenant_key):
            crew = list((await session.execute(stmt)).scalars().all())
        if not crew:
            return 0

        taken_stmt = select(AgentTemplate.name).where(
            AgentTemplate.tenant_key == self.tenant_key,
            AgentTemplate.deleted_at.is_(None),
        )
        with tenant_session_context(session, self.tenant_key):
            taken = {row[0] for row in (await session.execute(taken_stmt)).all()}

        bases = [re.sub(r"-\d+$", "", t.name) for t in crew]
        resolved = crew_suffixed_names(bases, taken)
        if resolved is None:
            product = await self._repo.get_by_id(session, self.tenant_key, product_id, include_deleted=True)
            slug = (getattr(product, "slug", None) or product_id)[:24]
            names = [f"{base}-{slug}" for base in bases]
            self._logger.warning(
                "Restored product %s could not reuse a numeric crew suffix; named its agents with the "
                "product slug instead",
                sanitize(product_id),
            )
        else:
            names = resolved[0]

        for template, name in zip(crew, names, strict=True):
            template.deleted_at = None
            template.name = name

        return len(crew)

    async def purge_product(self, product_id: str) -> dict:
        try:
            async with self._get_session() as session:
                product = await self._repo.get_by_id(session, self.tenant_key, product_id, include_deleted=True)

                if not product:
                    raise ResourceNotFoundError(
                        message="Product not found",
                        context={"product_id": product_id, "tenant_key": self.tenant_key},
                    )

                product_name = product.name

                await self._trash_owned_templates(session, product_id, datetime.now(UTC))

                await self._repo.delete_hard(session, product)
                await session.commit()

                self._logger.info(f"Permanently deleted product {product_id} ({product_name})")

                return {"product_name": product_name, "message": f"Product '{product_name}' permanently deleted"}

        except ResourceNotFoundError:
            raise
        except Exception as e:
            self._logger.exception("Failed to purge product")
            raise BaseGiljoError(
                message=f"Failed to permanently delete product: {e!s}",
                context={"product_id": product_id, "tenant_key": self.tenant_key},
            ) from e

    async def list_deleted_products(self) -> list[Product]:
        try:
            async with self._get_session() as session:
                return await self._repo.list_deleted(session, self.tenant_key)

        except Exception as e:
            self._logger.exception("Failed to list deleted products")
            raise BaseGiljoError(
                message=f"Failed to list deleted products: {e!s}", context={"tenant_key": self.tenant_key}
            ) from e

    async def purge_expired_deleted_products(self, days_before_purge: int = 10) -> PurgeResult:
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
        except Exception as e:
            self._logger.exception("[Product Purge] Failed to purge expired deleted products")
            raise BaseGiljoError(
                message=f"Failed to purge expired deleted products: {e!s}",
                context={
                    "operation": "purge_expired_deleted_products",
                    "tenant_key": self.tenant_key,
                    "days_before_purge": days_before_purge,
                },
            ) from e
