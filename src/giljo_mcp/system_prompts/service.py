# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
System prompt service

Provides a canonical source for system-managed prompts (currently orchestrator),
with optional administrator overrides stored in the configurations table.

BE-9385d: overrides resolve on a ladder -- **product override -> tenant override ->
seeded default**. The per-product rung is additional rows in the SAME store under a
product-namespaced key (``system.orchestrator_prompt:{product_id}``); the existing
``uq_config_tenant_key`` unique constraint already accommodates it, so the ladder
needs no schema migration. A tenant that never sets a product override keeps getting
its tenant-wide content byte-identically -- the old shape is tolerated, not rewritten.
"""

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
MAX_PROMPT_BYTES = 150_000  # ~150 KB safety limit

# BE-9385d: which rung of the ladder produced a PromptRecord. Surfaced so the editor
# can tell "this product's own override" from "inherited from your tenant-wide one"
# instead of presenting inherited content as if the product owned it.
SCOPE_PRODUCT = "product"
SCOPE_TENANT = "tenant"
SCOPE_DEFAULT = "default"


def product_orchestrator_config_key(product_id: str) -> str:
    """Config-store key for a product's orchestrator override (BE-9385d).

    Namespaced under the tenant-wide key so both rungs live in one place and a
    ``LIKE 'system.orchestrator_prompt%'`` sweep finds all of them.
    """
    return f"{DEFAULT_ORCHESTRATOR_CONFIG_KEY}:{product_id}"


def _normalize_product_id(product_id: str | None) -> str | None:
    """Validate a caller-supplied product id and return its canonical form.

    This value becomes part of a database key, and it arrives from agents and from
    the REST boundary, so it is never concatenated raw. Falsy/blank means "no product
    context" -- the ladder simply starts at the tenant rung, which is not an error.
    Anything non-blank that is not a UUID is refused rather than silently writing an
    unreachable key. Canonicalizing through ``uuid.UUID`` also guarantees that a get
    and an update for the same product can never disagree on the key's spelling.
    """
    if product_id is None:
        return None
    candidate = str(product_id).strip()
    if not candidate:
        return None
    try:
        return str(uuid.UUID(candidate))
    except (ValueError, AttributeError, TypeError) as exc:
        # Length only -- the raw value is caller-controlled and must not reach a log.
        raise ValueError(f"product_id must be a UUID string (got {len(candidate)} characters)") from exc


def coerce_product_id(product_id: str | None) -> str | None:
    """Tolerant twin of the strict validation, for INTERNAL resolution paths.

    The strict form is right at the REST boundary, where a malformed id is the
    caller's mistake and deserves a 422. It is wrong inside identity resolution: a
    product id that does not parse would raise, the caller's broad ``except`` would
    swallow it, and the tenant's own override would silently be replaced by the
    packaged seed -- a customization vanishing because of an unrelated data problem.
    Here an unusable id simply means "no product context", which lands the ladder on
    the tenant rung: the documented degradation.
    """
    try:
        return _normalize_product_id(product_id)
    except ValueError:
        return None


@dataclass(frozen=True)
class ResolvedOverride:
    """What the ladder resolved, plus the provenance the reader is owed (FE-9408).

    ``content`` keeps the meaning both identity call sites already relied on: the
    override text, or None to compose from the packaged seed. The rest is what those
    call sites used to throw away -- which rung answered, when that row was saved, and
    (for the product rung) which product's row it was. A silently-substituted persona
    cost three hand-diagnosed incidents precisely because none of it survived the read.

    One type for BOTH identity paths -- the mission resolver and the staging read -- so
    the two surfaces cannot describe the same override differently.
    """

    content: str | None
    scope: str = SCOPE_DEFAULT
    updated_at: datetime | None = None
    product_id: str | None = None


@dataclass
class PromptRecord:
    """Structured prompt payload returned to callers."""

    content: str
    is_override: bool
    updated_at: datetime | None
    updated_by: str | None
    # BE-9385d: additive with a default, so every pre-ladder construction and every
    # existing consumer of this dataclass is unchanged.
    scope: str = SCOPE_DEFAULT


class SystemPromptService:
    """Provide default + override-aware access to system prompts."""

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
        """
        Fetch orchestrator prompt with override metadata for the given tenant.

        BE-9385d: resolves on the ladder **product override -> tenant override ->
        seeded default**. ``product_id=None`` (the pre-ladder call shape, and every
        product-less context) simply starts at the tenant rung, so those callers get
        byte-identical content to before.

        Falls back to the hard-coded default when no override is present or
        when database access is unavailable.
        """
        self._require_tenant_key(tenant_key)
        normalized_product_id = _normalize_product_id(product_id)

        if session:
            override, scope = await self._fetch_ladder(session, tenant_key, normalized_product_id)
        elif self.db_manager:
            async with self.db_manager.get_session_async() as db_session:
                override, scope = await self._fetch_ladder(db_session, tenant_key, normalized_product_id)
        else:
            override, scope = None, SCOPE_DEFAULT

        if override:
            return PromptRecord(
                content=override["content"],
                is_override=True,
                updated_at=override.get("updated_at"),
                updated_by=override.get("updated_by"),
                scope=scope,
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
        """Persist an administrator override for the orchestrator prompt.

        Writes the rung named by ``product_id``: a product id targets that product's
        row, omitting it targets the tenant-wide row. One rung per call -- saving a
        product override never rewrites the tenant-wide one (BE-9385d).
        """
        self._require_tenant_key(tenant_key)
        self._ensure_db_manager()
        normalized_product_id = _normalize_product_id(product_id)
        sanitized_content = content.strip()
        self._validate_content(sanitized_content)

        payload = {
            "content": sanitized_content,
            "updated_by": updated_by,
            "updated_at": datetime.now(UTC),
        }
        config_key = self._config_key(normalized_product_id)

        if session:
            await self._upsert_override(session, tenant_key, config_key, payload)
            return await self.get_orchestrator_prompt(
                tenant_key=tenant_key, product_id=normalized_product_id, session=session
            )

        async with self.db_manager.get_session_async() as db_session:
            await self._upsert_override(db_session, tenant_key, config_key, payload)
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
        """Delete the override at one rung and return whatever the ladder now resolves.

        Resetting a PRODUCT rung means "this product goes back to inheriting": the
        tenant-wide row is left intact and becomes the answer again. Resetting the
        tenant rung deletes only that row and leaves product overrides standing.
        """
        self._require_tenant_key(tenant_key)
        self._ensure_db_manager()
        normalized_product_id = _normalize_product_id(product_id)
        config_key = self._config_key(normalized_product_id)

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

    @staticmethod
    def _config_key(normalized_product_id: str | None) -> str:
        """Config-store key for the rung named by an already-normalized product id."""
        if normalized_product_id:
            return product_orchestrator_config_key(normalized_product_id)
        return DEFAULT_ORCHESTRATOR_CONFIG_KEY

    async def _fetch_ladder(
        self,
        session: AsyncSession,
        tenant_key: str,
        normalized_product_id: str | None,
    ) -> tuple[dict | None, str]:
        """Walk product -> tenant and report which rung answered (BE-9385d)."""
        if normalized_product_id:
            product_override = await self._fetch_override(
                session, tenant_key, product_orchestrator_config_key(normalized_product_id)
            )
            if product_override:
                return product_override, SCOPE_PRODUCT

        tenant_override = await self._fetch_override(session, tenant_key, DEFAULT_ORCHESTRATOR_CONFIG_KEY)
        if tenant_override:
            return tenant_override, SCOPE_TENANT

        return None, SCOPE_DEFAULT

    async def read_tenant_override_row(
        self,
        *,
        tenant_key: str,
        session: AsyncSession | None = None,
    ) -> dict | None:
        """Return the TENANT-WIDE override row, even when a product rung outranks it.

        FE-9408: ``_fetch_ladder`` answers "what content wins" and short-circuits the
        moment the product rung does, so it can never report a tenant-wide row standing
        behind a product one. That short-circuit is right: the ladder runs on EVERY
        identity resolution, and teaching it to look at both rungs would buy an admin
        editor screen a second query on the hot path. This is the sibling read for the
        question only the editor asks -- "is there an account-wide override behind this
        product one, and when was it saved?" -- so the ladder keeps its single query.

        None when no tenant-wide row exists (or when there is no database to ask).
        """
        self._require_tenant_key(tenant_key)
        if session:
            return await self._fetch_override(session, tenant_key, DEFAULT_ORCHESTRATOR_CONFIG_KEY)
        if not self.db_manager:
            return None
        async with self.db_manager.get_session_async() as db_session:
            return await self._fetch_override(db_session, tenant_key, DEFAULT_ORCHESTRATOR_CONFIG_KEY)

    def default_orchestrator_content(self) -> str:
        """Public read of the packaged seed -- the same text the ladder falls back to.

        FE-9408: the editor needs it to answer "is what I am about to save identical to
        the built-in default?". Saving the displayed default is not a no-op -- it pins
        the account to that day's text and detaches it from every later seed
        improvement, which is the 2026-07-03 production row exactly. No I/O; the value
        is cached on the instance by ``_build_default_orchestrator_prompt``.
        """
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
        content = value.get("content")
        if not content:
            return None

        updated_at = value.get("updated_at")
        if isinstance(updated_at, str):
            try:
                updated_at = datetime.fromisoformat(updated_at)
            except ValueError:
                updated_at = None

        return {
            "content": content,
            "updated_by": value.get("updated_by"),
            "updated_at": updated_at,
        }

    async def _upsert_override(self, session: AsyncSession, tenant_key: str, config_key: str, payload: dict) -> None:
        """
        Persist the orchestrator override at ``config_key``.

        HO1027: Converted from select-then-insert-or-update to PostgreSQL
        ``INSERT ... ON CONFLICT (tenant_key, key) DO UPDATE`` so two
        concurrent admin saves cannot create duplicate rows or race past the
        existence check. Requires the ``uq_config_tenant_key`` unique
        constraint added in migration ``ce_0006``.

        BE-9385d: that same ``(tenant_key, key)`` constraint is what lets the
        product rung live here -- a product override is one more row under a
        namespaced key, and the upsert race-safety extends to it unchanged.
        """
        stored_value = {
            "content": payload["content"],
            "updated_by": payload.get("updated_by"),
            "updated_at": payload.get("updated_at").isoformat() if payload.get("updated_at") else None,
        }
        now = datetime.now(UTC)

        is_product_scoped = config_key != DEFAULT_ORCHESTRATOR_CONFIG_KEY
        stmt = pg_insert(Configuration).values(
            tenant_key=tenant_key,
            project_id=None,
            key=config_key,
            value=stored_value,
            category="system",
            description=(
                "Administrator override for orchestrator prompt (product-scoped)"
                if is_product_scoped
                else "Administrator override for orchestrator prompt"
            ),
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
        """
        Return the Layer B "user seed" content for the admin textarea.

        HO1027 (three-layer identity refactor): The default prompt the admin
        sees and edits is ONLY the user-facing seed — no harness mechanics
        (MCP Tool Usage, CHECK-IN PROTOCOL, HARNESS REMINDER OVERRIDE). The
        harness is appended at runtime by ``compose_orchestrator_identity``
        regardless of whether the tenant has saved an override. This keeps
        the textarea readable and prevents admins from accidentally deleting
        harness wiring when they save a custom prompt.
        """
        if self._default_orchestrator_prompt:
            return self._default_orchestrator_prompt

        # Import lazily to avoid circular import issues during startup.
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
    """Return what the ladder resolves for the STAGING identity call site.

    BE-9385d: the shape that call site wants -- "give me the override text, or
    nothing" -- without re-deriving the ``is_override`` check and the tolerant id
    coercion inline. (The get_job_mission side resolves its own product first, so it
    goes through ``orchestrator_product_resolver.resolve_orchestrator_override``.)
    ``product_id`` is coerced, not validated: an unusable id degrades to the tenant
    rung instead of raising into a caller's broad ``except``, where it would have cost
    the tenant its own saved override.

    FE-9408 widened the return from ``str | None`` to :class:`ResolvedOverride`. The
    scope was being computed and dropped one line before the caller needed it, which
    is why staging could serve a substituted persona and say nothing. ``content`` is
    unchanged in every branch, so the resolution this function performs is identical.
    """
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
    )
