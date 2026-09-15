# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager, tenant_session_context
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.repositories.taxonomy_repository import TaxonomyRepository
from giljo_mcp.services import taxonomy_ops


logger = logging.getLogger(__name__)


class TaxonomyService:

    def __init__(
        self,
        db_manager: DatabaseManager,
        session: AsyncSession | None = None,
    ) -> None:
        self._db_manager = db_manager
        self._session = session
        self._repo = TaxonomyRepository()
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    async def list_types(self, tenant_key: str) -> list[TaxonomyType]:
        if not tenant_key:
            raise ValidationError(
                "tenant_key is required",
                context={"operation": "taxonomy.list_types"},
            )
        if self._session is not None:
            with tenant_session_context(self._session, tenant_key):
                return await taxonomy_ops.list_taxonomy_types(self._session, tenant_key)
        async with self._db_manager.get_session_async() as session:
            with tenant_session_context(session, tenant_key):
                return await taxonomy_ops.list_taxonomy_types(session, tenant_key)

    async def validate(self, abbreviation: str, tenant_key: str, *, allow_reserved: bool = False) -> TaxonomyType:
        if not abbreviation or not abbreviation.strip():
            raise ValidationError(
                "abbreviation is required",
                context={"operation": "taxonomy.validate"},
            )
        if not tenant_key:
            raise ValidationError(
                "tenant_key is required",
                context={"operation": "taxonomy.validate"},
            )
        normalized = abbreviation.strip()
        if normalized in taxonomy_ops.RESERVED_TYPE_ABBRS and not allow_reserved:
            valid_types = await self._valid_types_payload(tenant_key)
            valid_abbrevs = sorted(t["abbreviation"] for t in valid_types)
            raise ValidationError(
                f"'{normalized}' is a reserved tag and cannot be selected. Valid types: {', '.join(valid_abbrevs)}.",
                context={
                    "operation": "taxonomy.validate",
                    "abbreviation": normalized,
                    "reserved": True,
                    "valid_types": valid_types,
                },
            )
        if self._session is not None:
            with tenant_session_context(self._session, tenant_key):
                row = await self._repo.get_by_abbreviation(self._session, tenant_key, normalized)
        else:
            async with self._db_manager.get_session_async(tenant_key=tenant_key) as session:
                with tenant_session_context(session, tenant_key):
                    row = await self._repo.get_by_abbreviation(session, tenant_key, normalized)

        if row is None:
            valid_types = await self._valid_types_payload(tenant_key)
            valid_abbrevs = sorted(t["abbreviation"] for t in valid_types)
            raise ValidationError(
                f"Unknown taxonomy type '{normalized}'. Valid types: {', '.join(valid_abbrevs)}.",
                context={
                    "operation": "taxonomy.validate",
                    "abbreviation": normalized,
                    "valid_types": valid_types,
                },
            )
        return row

    async def create_type(
        self,
        tenant_key: str,
        *,
        abbreviation: str,
        label: str,
        color: str = "#607D8B",
        sort_order: int = 0,
    ) -> TaxonomyType:
        if not tenant_key:
            raise ValidationError(
                "tenant_key is required",
                context={"operation": "taxonomy.create_type"},
            )
        normalized_abbr = (abbreviation or "").strip().upper()
        if normalized_abbr in taxonomy_ops.RESERVED_TYPE_ABBRS:
            raise ValidationError(
                f"'{normalized_abbr}' is a reserved tag and cannot be created as a custom type.",
                context={"operation": "taxonomy.create_type", "abbreviation": abbreviation, "reserved": True},
            )
        if self._session is not None:
            with tenant_session_context(self._session, tenant_key):
                return await taxonomy_ops.create_taxonomy_type(
                    self._session,
                    tenant_key,
                    abbreviation=abbreviation,
                    label=label,
                    color=color,
                    sort_order=sort_order,
                )
        async with self._db_manager.get_session_async(tenant_key=tenant_key) as session:
            with tenant_session_context(session, tenant_key):
                return await taxonomy_ops.create_taxonomy_type(
                    session,
                    tenant_key,
                    abbreviation=abbreviation,
                    label=label,
                    color=color,
                    sort_order=sort_order,
                )

    async def ensure_reserved_task_type(self, tenant_key: str) -> TaxonomyType:
        if not tenant_key:
            raise ValidationError(
                "tenant_key is required",
                context={"operation": "taxonomy.ensure_reserved_task_type"},
            )
        if self._session is not None:
            with tenant_session_context(self._session, tenant_key):
                return await taxonomy_ops.ensure_reserved_task_type(self._session, tenant_key)
        async with self._db_manager.get_session_async(tenant_key=tenant_key) as session:
            with tenant_session_context(session, tenant_key):
                return await taxonomy_ops.ensure_reserved_task_type(session, tenant_key)

    async def _valid_types_payload(self, tenant_key: str) -> list[dict[str, Any]]:
        rows = await self.list_types(tenant_key)
        return [
            {"abbreviation": t.abbreviation, "label": t.label, "color": t.color}
            for t in rows
            if t.abbreviation not in taxonomy_ops.RESERVED_TYPE_ABBRS
        ]
