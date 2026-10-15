# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.models import Configuration


DEFAULT_ORCHESTRATOR_CONFIG_KEY = "system.orchestrator_prompt"
MAX_PROMPT_BYTES = 150_000

SCOPE_PRODUCT = "product"
SCOPE_DEFAULT = "default"

MODE_ADDITIONS = "additions"
MODE_REPLACE = "replace"
ADDITIONS_HEADING = "## Additional Instructions For This Account"


def product_orchestrator_config_key(product_id: str) -> str:
    return f"{DEFAULT_ORCHESTRATOR_CONFIG_KEY}:{product_id}"


def _normalize_product_id(product_id: str | None) -> str | None:
    if product_id is None:
        return None
    candidate = str(product_id).strip()
    if not candidate:
        return None
    try:
        return str(uuid.UUID(candidate))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(f"product_id must be a UUID string (got {len(candidate)} characters)") from exc


def coerce_product_id(product_id: str | None) -> str | None:
    try:
        return _normalize_product_id(product_id)
    except ValueError:
        return None


class ProductRequiredError(ValueError):

    def __init__(self) -> None:
        super().__init__("product_id is required: the orchestrator prompt is set per product.")


def _require_product_id(normalized_product_id: str | None) -> str:
    if not normalized_product_id:
        raise ProductRequiredError
    return normalized_product_id


@dataclass(frozen=True)
class ResolvedOverride:

    content: str | None
    scope: str = SCOPE_DEFAULT
    updated_at: datetime | None = None
    product_id: str | None = None
    mode: str | None = None


@dataclass
class PromptRecord:

    content: str
    is_override: bool
    updated_at: datetime | None
    updated_by: str | None
    scope: str = SCOPE_DEFAULT
    mode: str | None = None
    additions: str | None = None


def compose_seed_with_additions(seed: str, additions: str) -> str:
    return f"{seed.strip()}\n\n{ADDITIONS_HEADING}\n\n{additions.strip()}"


class SystemPromptService:

    def __init__(self, db_manager: DatabaseManager | None = None):
        self.db_manager = db_manager
        self._default_orchestrator_prompt: str | None = None

    async def get_orchestrator_prompt(
        self,
        *,
        tenant_key: str,
        product_id: str | None = None,
        session: AsyncSession | None = None,
    ) -> PromptRecord:
        self._require_tenant_key(tenant_key)
        normalized_product_id = _normalize_product_id(product_id)

        if session:
            override = await self._fetch_product_override(session, tenant_key, normalized_product_id)
        elif self.db_manager:
            async with self.db_manager.get_session_async() as db_session:
                override = await self._fetch_product_override(db_session, tenant_key, normalized_product_id)
        else:
            override = None

        if override:
            if override["mode"] == MODE_ADDITIONS:
                content = compose_seed_with_additions(self._build_default_orchestrator_prompt(), override["additions"])
            else:
                content = override["content"]
            return PromptRecord(
                content=content,
                is_override=True,
                updated_at=override.get("updated_at"),
                updated_by=override.get("updated_by"),
                scope=SCOPE_PRODUCT,
                mode=override["mode"],
                additions=override.get("additions"),
            )

        return PromptRecord(
            content=self._build_default_orchestrator_prompt(),
            is_override=False,
            updated_at=None,
            updated_by=None,
            scope=SCOPE_DEFAULT,
        )

    async def update_orchestrator_prompt(
        self,
        *,
        tenant_key: str,
        content: str,
        updated_by: str,
        product_id: str | None = None,
        session: AsyncSession | None = None,
    ) -> PromptRecord:
        self._require_tenant_key(tenant_key)
        self._ensure_db_manager()
        normalized_product_id = _require_product_id(_normalize_product_id(product_id))
        sanitized_content = content.strip()
        self._validate_content(sanitized_content)

        stored_value = {
            "content": sanitized_content,
            "updated_by": updated_by,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        return await self._save_rung(tenant_key, normalized_product_id, stored_value, session)

    async def update_orchestrator_additions(
        self,
        *,
        tenant_key: str,
        additions: str,
        updated_by: str,
        product_id: str | None = None,
        session: AsyncSession | None = None,
    ) -> PromptRecord:
        self._require_tenant_key(tenant_key)
        self._ensure_db_manager()
        normalized_product_id = _require_product_id(_normalize_product_id(product_id))
        sanitized = additions.strip()
        self._validate_content(sanitized)

        stored_value = {
            "mode": MODE_ADDITIONS,
            "additions": sanitized,
            "updated_by": updated_by,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        return await self._save_rung(tenant_key, normalized_product_id, stored_value, session)

    async def read_rung_additions(
        self,
        *,
        tenant_key: str,
        product_id: str | None = None,
        session: AsyncSession | None = None,
    ) -> str | None:
        self._require_tenant_key(tenant_key)
        normalized_product_id = _normalize_product_id(product_id)
        if normalized_product_id is None:
            return None
        config_key = product_orchestrator_config_key(normalized_product_id)
        if session:
            row = await self._fetch_override(session, tenant_key, config_key)
        elif self.db_manager:
            async with self.db_manager.get_session_async() as db_session:
                row = await self._fetch_override(db_session, tenant_key, config_key)
        else:
            row = None
        if row is None or row["mode"] != MODE_ADDITIONS:
            return None
        return row["additions"]

    async def _save_rung(
        self,
        tenant_key: str,
        normalized_product_id: str,
        stored_value: dict,
        session: AsyncSession | None,
    ) -> PromptRecord:
        config_key = product_orchestrator_config_key(normalized_product_id)
        if session:
            await self._upsert_override(session, tenant_key, config_key, stored_value)
            return await self.get_orchestrator_prompt(
                tenant_key=tenant_key, product_id=normalized_product_id, session=session
            )

        async with self.db_manager.get_session_async() as db_session:
            await self._upsert_override(db_session, tenant_key, config_key, stored_value)
            return await self.get_orchestrator_prompt(
                tenant_key=tenant_key, product_id=normalized_product_id, session=db_session
            )

    async def reset_orchestrator_prompt(
        self,
        *,
        tenant_key: str,
        product_id: str | None = None,
        session: AsyncSession | None = None,
    ) -> PromptRecord:
        self._require_tenant_key(tenant_key)
        self._ensure_db_manager()
        normalized_product_id = _require_product_id(_normalize_product_id(product_id))
        config_key = product_orchestrator_config_key(normalized_product_id)

        if session:
            await self._delete_override(session, tenant_key, config_key)
            return await self.get_orchestrator_prompt(
                tenant_key=tenant_key, product_id=normalized_product_id, session=session
            )

        async with self.db_manager.get_session_async() as db_session:
            await self._delete_override(db_session, tenant_key, config_key)
            return await self.get_orchestrator_prompt(
                tenant_key=tenant_key, product_id=normalized_product_id, session=db_session
            )

    async def _fetch_product_override(
        self,
        session: AsyncSession,
        tenant_key: str,
        normalized_product_id: str | None,
    ) -> dict | None:
        if not normalized_product_id:
            return None
        return await self._fetch_override(session, tenant_key, product_orchestrator_config_key(normalized_product_id))

    def default_orchestrator_content(self) -> str:
        return self._build_default_orchestrator_prompt()

    def _ensure_db_manager(self) -> None:
        if not self.db_manager:
            raise RuntimeError("Database manager is required for this operation")

    @staticmethod
    def _require_tenant_key(tenant_key: str) -> None:
        if not tenant_key or not tenant_key.strip():
            raise ValueError("tenant_key is required")

    @staticmethod
    def _validate_content(content: str) -> None:
        if not content or not content.strip():
            raise ValueError("Prompt content cannot be empty")
        if len(content.encode("utf-8")) > MAX_PROMPT_BYTES:
            raise ValueError(f"Prompt content exceeds {MAX_PROMPT_BYTES / 1024:.0f}KB limit")

    async def _fetch_override(self, session: AsyncSession, tenant_key: str, config_key: str) -> dict | None:
        stmt = select(Configuration).where(
            Configuration.tenant_key == tenant_key,
            Configuration.key == config_key,
        )
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()
        if not record:
            return None

        value = record.value or {}
        if value.get("mode") == MODE_ADDITIONS:
            mode, content, additions = MODE_ADDITIONS, None, value.get("additions")
            if not additions:
                return None
        else:
            mode, content, additions = MODE_REPLACE, value.get("content"), None
            if not content:
                return None

        updated_at = value.get("updated_at")
        if isinstance(updated_at, str):
            try:
                updated_at = datetime.fromisoformat(updated_at)
            except ValueError:
                updated_at = None

        return {
            "mode": mode,
            "content": content,
            "additions": additions,
            "updated_by": value.get("updated_by"),
            "updated_at": updated_at,
        }

    async def _upsert_override(
        self, session: AsyncSession, tenant_key: str, config_key: str, stored_value: dict
    ) -> None:
        now = datetime.now(UTC)

        stmt = pg_insert(Configuration).values(
            tenant_key=tenant_key,
            project_id=None,
            key=config_key,
            value=stored_value,
            category="system",
            description="Administrator override for orchestrator prompt (product-scoped)",
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_config_tenant_key",
            set_={
                "value": stmt.excluded.value,
                "updated_at": now,
            },
        )
        await session.execute(stmt)

    async def _delete_override(self, session: AsyncSession, tenant_key: str, config_key: str) -> None:
        stmt = delete(Configuration).where(
            Configuration.tenant_key == tenant_key,
            Configuration.key == config_key,
        )
        await session.execute(stmt)

    def _build_default_orchestrator_prompt(self) -> str:
        if self._default_orchestrator_prompt:
            return self._default_orchestrator_prompt

        from giljo_mcp.template_seeder import _get_user_facing_orchestrator_seed

        self._default_orchestrator_prompt = _get_user_facing_orchestrator_seed().strip()
        return self._default_orchestrator_prompt


async def read_orchestrator_override(
    *,
    db_manager: DatabaseManager | None,
    tenant_key: str,
    product_id: str | None,
    session: AsyncSession | None = None,
) -> ResolvedOverride:
    normalized_product_id = coerce_product_id(product_id)
    record = await SystemPromptService(db_manager=db_manager).get_orchestrator_prompt(
        tenant_key=tenant_key,
        product_id=normalized_product_id,
        session=session,
    )
    if not record.is_override:
        return ResolvedOverride(content=None, scope=SCOPE_DEFAULT)
    return ResolvedOverride(
        content=record.content,
        scope=record.scope,
        updated_at=record.updated_at,
        product_id=normalized_product_id if record.scope == SCOPE_PRODUCT else None,
        mode=record.mode,
    )
