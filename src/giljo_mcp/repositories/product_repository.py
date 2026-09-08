# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
ProductRepository - Data access layer for Product CRUD and lifecycle operations.

BE-5022c: Extracted from ProductService and ProductLifecycleService to route all
database writes through the repository layer.

Responsibilities:
- Product CRUD (create, read, update, soft-delete, hard-delete)
- Product activation/deactivation with cascade logic
- Config relations management (tech_stack, architecture, test_config)
- Soft-delete restoration, expiry purge

Design Principles:
- Session-in pattern: all methods accept session as parameter
- tenant_key filtering on EVERY query — no exceptions
- No business logic — pure data access
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.models import Product
from giljo_mcp.models.products import (
    ProductArchitecture,
    ProductTechStack,
    ProductTestConfig,
)


logger = logging.getLogger(__name__)


class ProductRepository:
    """
    Repository for Product database operations.

    All methods enforce tenant_key isolation.
    Session is passed in by the caller (service layer).
    """

    def __init__(self) -> None:
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    # ============================================================================
    # Read Operations
    # ============================================================================

    async def get_by_id(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str,
        *,
        include_deleted: bool = False,
        eager_load: bool = False,
    ) -> Product | None:
        """
        Get a product by ID with tenant isolation.

        Args:
            session: Active database session
            tenant_key: Tenant key for isolation
            product_id: Product UUID
            include_deleted: Include soft-deleted products
            eager_load: Eager-load relationships (vision_documents, tech_stack, etc.)

        Returns:
            Product instance or None
        """
        conditions = [Product.id == product_id, Product.tenant_key == tenant_key]
        if not include_deleted:
            conditions.append(Product.deleted_at.is_(None))

        stmt = select(Product).where(and_(*conditions))

        if eager_load:
            stmt = stmt.options(
                selectinload(Product.vision_documents),
                selectinload(Product.tech_stack),
                selectinload(Product.architecture),
                selectinload(Product.test_config),
            )

        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_name(
        self,
        session: AsyncSession,
        tenant_key: str,
        name: str,
    ) -> Product | None:
        """
        Get a non-deleted product by name.

        Args:
            session: Active database session
            tenant_key: Tenant key for isolation
            name: Product name

        Returns:
            Product instance or None
        """
        stmt = select(Product).where(
            and_(
                Product.tenant_key == tenant_key,
                Product.name == name,
                Product.deleted_at.is_(None),
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_default_product(
        self,
        session: AsyncSession,
        tenant_key: str,
        *,
        eager_load: bool = True,
    ) -> Product | None:
        """
        Get the tenant's DEFAULT product -- where an unscoped read resolves.

        FE-9524: renamed from
        ``get_active_product``. "Shown" (``is_active``) and "default" are two
        different questions now that several products may be shown at once;
        this reads the NEW ``is_default`` column, not ``is_active``.
        ``idx_product_single_default_per_tenant`` (ce_0099) enforces exactly
        one per tenant, so ``scalar_one_or_none()`` stays honest -- this is
        the same single-row guarantee ``idx_product_single_active_per_tenant``
        used to give the old query, moved onto a column that is actually
        still single-valued. Do NOT replace this with ``LIMIT 1`` /
        ``ORDER BY`` "pick one" logic: an arbitrary-but-stable product
        returned with no uniqueness backing it is a wrong answer delivered
        confidently, which is exactly the failure class this rename fixes.

        Args:
            session: Active database session
            tenant_key: Tenant key for isolation
            eager_load: BE-6066 P2 — when True (default), eager-load the 4 detail
                relations (vision_documents / tech_stack / architecture /
                test_config) for response building. When False, SKIP them: callers
                that only need identity/columns (e.g. reading the previously-default
                product's id during set_default_product) to skip four wasted selectin
                loads. Such callers MUST NOT read those relations off the returned model.

        Returns:
            The default Product instance, or None if the tenant has none set
            (a legal, pre-existing state -- see the ce_0099 migration docstring).

        SOLE-SHOWN-PRODUCT FALLBACK. If no row has ``is_default`` set, and
        the tenant has EXACTLY ONE non-deleted product with ``is_active``
        (shown) true, that product is returned anyway. This is NOT the
        "arbitrary-but-stable pick" the docstring above forbids -- with only
        one shown candidate there is nothing to pick AMONG, so the answer is
        unambiguous by construction. Scoped to SHOWN (not "exactly one
        product total") so a tenant that deliberately has no default -- a
        single product that is hidden, or several products with none
        explicitly defaulted -- correctly still resolves to None rather than
        the fallback silently picking one; D2's "hidden is still reachable"
        governs lookup BY ID, not whether an unscoped read should treat a
        hidden product as an implicit default. This exists so a tenant whose
        sole shown product predates ``is_default`` (or was created without
        going through ``ProductService.create_product``, e.g. most of this
        codebase's test fixtures, which seed a ``Product`` ORM row directly)
        still resolves correctly -- "single-product users see no change"
        holds for reads, not just for shown/hidden.
        """

        def _apply_eager(stmt):
            if eager_load:
                return stmt.options(
                    selectinload(Product.vision_documents),
                    selectinload(Product.tech_stack),
                    selectinload(Product.architecture),
                    selectinload(Product.test_config),
                )
            return stmt

        stmt = _apply_eager(
            select(Product).where(
                and_(
                    Product.tenant_key == tenant_key,
                    Product.is_default,
                    Product.deleted_at.is_(None),
                )
            )
        )
        result = await session.execute(stmt)
        product = result.scalar_one_or_none()
        if product is not None:
            return product

        count_stmt = (
            select(func.count())
            .select_from(Product)
            .where(and_(Product.tenant_key == tenant_key, Product.is_active, Product.deleted_at.is_(None)))
        )
        count = (await session.execute(count_stmt)).scalar_one()
        if count != 1:
            return None

        sole_stmt = _apply_eager(
            select(Product).where(
                and_(Product.tenant_key == tenant_key, Product.is_active, Product.deleted_at.is_(None))
            )
        )
        result = await session.execute(sole_stmt)
        return result.scalar_one_or_none()

    async def count_active_products(self, session: AsyncSession, tenant_key: str) -> int:
        """
        Count the tenant's currently SHOWN (``is_active``) non-deleted products.

        FE-9529: `ProductLifecycleService.activate_product` needs to know,
        BEFORE flipping a product's `is_active`, whether it is about to take
        the tenant from one shown product to two -- the exact transition that
        erases `get_default_product`'s sole-shown-product fallback. Mirrors
        the inline count `get_default_product` already runs internally.
        """
        count_stmt = (
            select(func.count())
            .select_from(Product)
            .where(and_(Product.tenant_key == tenant_key, Product.is_active, Product.deleted_at.is_(None)))
        )
        return (await session.execute(count_stmt)).scalar_one()

    async def find_other_default_products(
        self,
        session: AsyncSession,
        tenant_key: str,
        exclude_product_id: str,
    ) -> list[Product]:
        """Other products currently holding the default flag for this tenant.

        Only ever 0 or 1 rows given ``idx_product_single_default_per_tenant``,
        but returned as a list (mirrors ``find_other_active_products``'
        pre-existing shape) so the caller's clear-then-set flow is a single
        code path regardless of count.
        """
        stmt = select(Product).where(
            and_(
                Product.tenant_key == tenant_key,
                Product.is_default,
                Product.id != exclude_product_id,
            )
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def list_products(
        self,
        session: AsyncSession,
        tenant_key: str,
        *,
        include_inactive: bool = False,
        lean: bool = False,
    ) -> list[Product]:
        """
        List products for a tenant.

        Args:
            session: Active database session
            tenant_key: Tenant key for isolation
            include_inactive: Include inactive products
            lean: BE-6066 P4 — when True, SKIP eager-loading the 4 detail relations
                (vision_documents / tech_stack / architecture / test_config). The
                lean products LIST serializes only columns + aggregates and must
                NOT touch those relations after the session closes; full detail
                loads on demand via ``get_by_id(eager_load=True)``.

        Returns:
            List of Product instances
        """
        conditions = [Product.tenant_key == tenant_key, Product.deleted_at.is_(None)]

        if not include_inactive:
            conditions.append(Product.is_active)

        stmt = select(Product).where(and_(*conditions))
        if not lean:
            stmt = stmt.options(
                selectinload(Product.vision_documents),
                selectinload(Product.tech_stack),
                selectinload(Product.architecture),
                selectinload(Product.test_config),
            )
        stmt = stmt.order_by(Product.is_active.desc(), Product.created_at.desc())
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def list_deleted(
        self,
        session: AsyncSession,
        tenant_key: str,
    ) -> list[Product]:
        """
        List soft-deleted products for a tenant.

        Args:
            session: Active database session
            tenant_key: Tenant key for isolation

        Returns:
            List of soft-deleted Product instances
        """
        stmt = (
            select(Product)
            .where(
                and_(
                    Product.tenant_key == tenant_key,
                    Product.deleted_at.isnot(None),
                )
            )
            .order_by(Product.deleted_at.desc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_deleted_by_id(
        self,
        session: AsyncSession,
        tenant_key: str,
        product_id: str,
    ) -> Product | None:
        """
        Get a soft-deleted product by ID.

        Args:
            session: Active database session
            tenant_key: Tenant key for isolation
            product_id: Product UUID

        Returns:
            Soft-deleted Product instance or None
        """
        stmt = select(Product).where(
            and_(
                Product.id == product_id,
                Product.tenant_key == tenant_key,
                Product.deleted_at.isnot(None),
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_expired_deleted(
        self,
        session: AsyncSession,
        days_before_purge: int = 10,
    ) -> list[Product]:
        """
        Find products soft-deleted more than N days ago.

        Note: This is a cross-tenant operation used by startup purge.

        CONTRACT: Returns CROSS-TENANT rows (the tenant_isolation_bypass below
        intentionally scans every tenant's soft-deleted products). The caller MUST
        re-scope per tenant before any delete: either delete the exact Product
        instances returned here by identity (``session.delete(obj)``), or, if
        issuing a bulk ``DELETE``/``UPDATE``, add an explicit ``tenant_key`` filter.
        NEVER feed these rows into an unscoped bulk statement — that would mutate
        rows outside the intended set.

        Args:
            session: Active database session
            days_before_purge: Days threshold

        Returns:
            List of expired Product instances (cross-tenant)
        """
        cutoff_date = datetime.now(UTC) - timedelta(days=days_before_purge)
        stmt = select(Product).where(
            Product.deleted_at.isnot(None),
            Product.deleted_at < cutoff_date,
        )
        with tenant_isolation_bypass(
            session,
            reason="startup purge scans soft-deleted products across tenants",
            models=(Product,),
        ):
            result = await session.execute(stmt)
        return list(result.scalars().all())

    # ============================================================================
    # Write Operations
    # ============================================================================

    async def add(self, session: AsyncSession, product: Product) -> None:
        """
        Add a product to the session.

        Args:
            session: Active database session
            product: Product instance to add
        """
        session.add(product)

    async def delete_hard(self, session: AsyncSession, product: Product) -> None:
        """
        Hard-delete a product (cascades via FK).

        Args:
            session: Active database session
            product: Product instance to delete
        """
        await session.delete(product)

    async def flush(self, session: AsyncSession) -> None:
        """
        Flush pending changes to the database.

        Args:
            session: Active database session
        """
        await session.flush()

    async def refresh(
        self,
        session: AsyncSession,
        product: Product,
        *,
        include_relations: bool = True,
    ) -> None:
        """
        Refresh a product from the database.

        Args:
            session: Active database session
            product: Product instance to refresh
            include_relations: Whether to refresh relationships
        """
        if include_relations:
            await session.refresh(
                product,
                attribute_names=["tech_stack", "architecture", "test_config", "vision_documents"],
            )
        else:
            await session.refresh(product)

    # ============================================================================
    # Config Relations
    # ============================================================================

    async def create_config_relations(
        self,
        session: AsyncSession,
        product_id: str,
        tenant_key: str,
        config_data: dict,
    ) -> None:
        """
        Create normalized config table rows from config data.

        Args:
            session: Active database session
            product_id: Product UUID
            tenant_key: Tenant key for isolation
            config_data: Dict with optional keys: tech_stack, architecture, test_config
        """
        tech_stack = config_data.get("tech_stack")
        if tech_stack and isinstance(tech_stack, dict):
            ts = ProductTechStack(
                product_id=product_id,
                tenant_key=tenant_key,
                programming_languages=tech_stack.get("programming_languages", ""),
                frontend_frameworks=tech_stack.get("frontend_frameworks", ""),
                backend_frameworks=tech_stack.get("backend_frameworks", ""),
                databases_storage=tech_stack.get("databases_storage", ""),
                infrastructure=tech_stack.get("infrastructure", ""),
                dev_tools=tech_stack.get("dev_tools", ""),
            )
            session.add(ts)

        architecture = config_data.get("architecture")
        if architecture and isinstance(architecture, dict):
            arch = ProductArchitecture(
                product_id=product_id,
                tenant_key=tenant_key,
                primary_pattern=architecture.get("primary_pattern", ""),
                design_patterns=architecture.get("design_patterns", ""),
                api_style=architecture.get("api_style", ""),
                architecture_notes=architecture.get("architecture_notes", ""),
                coding_conventions=architecture.get("coding_conventions", ""),
            )
            session.add(arch)

        test_config = config_data.get("test_config")
        if test_config and isinstance(test_config, dict):
            tc = ProductTestConfig(
                product_id=product_id,
                tenant_key=tenant_key,
                quality_standards=test_config.get("quality_standards", ""),
                test_strategy=test_config.get("test_strategy", ""),
                coverage_target=test_config.get("coverage_target", 80),
                testing_frameworks=test_config.get("testing_frameworks", ""),
            )
            session.add(tc)

    async def update_config_relations(
        self,
        session: AsyncSession,
        product: Product,
        tenant_key: str,
        config_data: dict,
    ) -> None:
        """
        Update normalized config table rows.

        Args:
            session: Active database session
            product: Product instance with loaded relationships
            tenant_key: Tenant key for isolation
            config_data: Dict with optional keys: tech_stack, architecture, test_config
        """
        tech_stack = config_data.get("tech_stack")
        if tech_stack and isinstance(tech_stack, dict):
            ts = product.tech_stack
            if ts is None:
                ts = ProductTechStack(product_id=product.id, tenant_key=tenant_key)
                session.add(ts)
                product.tech_stack = ts
            for field in (
                "programming_languages",
                "frontend_frameworks",
                "backend_frameworks",
                "databases_storage",
                "infrastructure",
                "dev_tools",
            ):
                if field in tech_stack:
                    setattr(ts, field, tech_stack[field])

        architecture = config_data.get("architecture")
        if architecture and isinstance(architecture, dict):
            arch = product.architecture
            if arch is None:
                arch = ProductArchitecture(product_id=product.id, tenant_key=tenant_key)
                session.add(arch)
                product.architecture = arch
            for field in (
                "primary_pattern",
                "design_patterns",
                "api_style",
                "architecture_notes",
                "coding_conventions",
            ):
                if field in architecture:
                    setattr(arch, field, architecture[field])

        test_config = config_data.get("test_config")
        if test_config and isinstance(test_config, dict):
            tc = product.test_config
            if tc is None:
                tc = ProductTestConfig(product_id=product.id, tenant_key=tenant_key)
                session.add(tc)
                product.test_config = tc
            for field in ("quality_standards", "test_strategy", "coverage_target", "testing_frameworks"):
                if field in test_config:
                    setattr(tc, field, test_config[field])

    # ============================================================================
    # Lifecycle Operations (ProductLifecycleService)
    # ============================================================================
