# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""TSK-9210 — per-token ``staged_at`` anchor closes the two-overlapping-tokens edge.

BE-9208 D1 shipped a freshness guard anchored on the tenant-GLOBAL export
watermark ``MAX(last_exported_at)``. Its honestly-flagged limitation: with TWO
live download tokens and a template edit between their stagings, the NEWER
staging's watermark MASKS the OLDER link's staleness, so the older link serves a
pre-change snapshot with a 200.

Timeline that breaks the tenant-global anchor::

    t1  token A staged            -> last_exported_at = t1
    t2  template edited           -> updated_at       = t2   (content > export -> A stale, correctly)
    t3  token B staged            -> last_exported_at = t3   (export jumps PAST t2 -> A looks fresh again)

At t3 the guard compares content(t2) > export(t3) => False, so token A — whose
frozen bytes predate the t2 edit — is served 200. The per-token anchor compares
content(t2) > A.staged_at(t1) => True, so A is correctly refused.

``staged_at`` is stamped in ``TokenManager.mark_ready()``, which runs AFTER
staging commits ``last_exported_at``. That ordering is load-bearing: anchoring on
``token.created_at`` instead would false-positive on EVERY fresh download,
because the staging write bumps ``updated_at`` past the token's creation time
(documented in ``staged_agent_zip_is_stale``).

Two-sided throughout: every test asserts both the refusal AND that the freshly
staged link still serves 200 — a guard that 410s everything would pass a
one-sided test while breaking the product.

Legacy tolerance (data-facing DoD, rule (a) — code tolerates the old shape): the
migration adds ``staged_at`` NULLABLE with no backfill, so tokens minted before
the upgrade carry NULL. Those fall back to the BE-9208 export-watermark
behavior rather than erroring or being blanket-refused. Tokens live 15 minutes,
so the legacy path self-drains almost immediately.

Exercises the FAILING layer — the real HTTP token-download endpoint through
FastAPI DI via the ASGI client — per the failing-layer rule.

Parallel-safe: each test seeds its own unique tenant + token UUIDs, stages into
unique ``temp/<tenant>/<token>/`` dirs, and deletes its temp dir + committed rows
in teardown; no module-level mutable state; no ordering dependency.

Task: TSK-9210.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select, update

from giljo_mcp.file_staging import FileStaging
from giljo_mcp.models import AgentTemplate, DownloadToken
from giljo_mcp.tenant import TenantManager


_FILENAME = "agent_templates.zip"
_DOWNLOAD_TYPE = "agent_templates"


async def _make_template(session, tenant_key: str, name: str) -> None:
    session.add(
        AgentTemplate(
            tenant_key=tenant_key,
            name=name,
            role=name,
            version="1.0.0",
            cli_tool="claude",
            system_instructions=f"Original instructions for {name}.",
            is_active=True,
            is_default=False,
        )
    )
    await session.flush()


async def _stage_token(db_manager, tenant_key: str) -> str:
    """Mint a token, stage the templates ZIP, and mark it ready (which stamps staged_at)."""
    from giljo_mcp.download_tokens import TokenManager

    async with db_manager.get_session_async() as session:
        token_manager = TokenManager(db_session=session)
        token = await token_manager.generate_token(
            tenant_key=tenant_key, download_type=_DOWNLOAD_TYPE, filename=_FILENAME
        )
        staging = FileStaging(db_session=session)
        staging_path = await staging.create_staging_directory(tenant_key, token)
        zip_path, msg = await staging.stage_agent_templates(
            staging_path, tenant_key, db_session=session, platform="claude_code"
        )
        assert zip_path is not None, f"staging failed: {msg}"
        await token_manager.mark_ready(token)

    return token


async def _edit_template(db_manager, tenant_key: str) -> None:
    """A real user edit AFTER staging — bumps updated_at (onupdate) past the staged snapshot."""
    from giljo_mcp.database import tenant_session_context

    async with db_manager.get_session_async() as session:
        with tenant_session_context(session, tenant_key):
            result = await session.execute(select(AgentTemplate).where(AgentTemplate.tenant_key == tenant_key))
            template = result.scalars().first()
            assert template is not None, "expected the seeded template"
            template.system_instructions = "EDITED after staging — token A's frozen bytes predate this."
            await session.commit()


async def _null_out_staged_at(db_manager, tenant_key: str, token: str) -> None:
    """Simulate a token minted BEFORE the migration (staged_at IS NULL, no backfill)."""
    from giljo_mcp.database import tenant_session_context

    async with db_manager.get_session_async() as session:
        with tenant_session_context(session, tenant_key):
            await session.execute(update(DownloadToken).where(DownloadToken.token == token).values(staged_at=None))
            await session.commit()


async def _cleanup(db_manager, tenant_key: str) -> None:
    shutil.rmtree(Path.cwd() / "temp" / tenant_key, ignore_errors=True)
    from giljo_mcp.database import tenant_session_context

    async with db_manager.get_session_async() as session:
        with tenant_session_context(session, tenant_key):
            await session.execute(delete(DownloadToken).where(DownloadToken.tenant_key == tenant_key))
            await session.execute(delete(AgentTemplate).where(AgentTemplate.tenant_key == tenant_key))
            await session.commit()


@pytest_asyncio.fixture(scope="function")
async def tenant_key(db_manager):
    key = TenantManager.generate_tenant_key()
    async with db_manager.get_session_async() as session:
        await _make_template(session, key, "agent-tsk9210")
        await session.commit()
    try:
        yield key
    finally:
        await _cleanup(db_manager, key)


def _url(token: str) -> str:
    return f"/api/download/temp/{token}/{_FILENAME}"


@pytest.mark.asyncio
async def test_older_of_two_overlapping_tokens_is_refused(api_client: AsyncClient, db_manager, tenant_key: str) -> None:
    """THE regression: a second staging must not mask the first link's staleness.

    Pre-fix this was RED — token A returned 200 with the pre-edit snapshot, because
    B's staging pushed the tenant-global export watermark past the edit. The
    per-token anchor judges A against ITS OWN staging time, so the edit still counts.
    """
    token_a = await _stage_token(db_manager, tenant_key)
    await _edit_template(db_manager, tenant_key)
    token_b = await _stage_token(db_manager, tenant_key)

    resp_a = await api_client.get(_url(token_a))
    assert resp_a.status_code == 410, (
        "token A was staged BEFORE the template edit, so its frozen bytes are a "
        f"pre-change snapshot and must be refused — got {resp_a.status_code}. "
        "A 200 here means token B's staging masked A's staleness (the BE-9208 "
        "tenant-global watermark limitation this task closes)."
    )

    # Two-sided: the guard must still let the CURRENT link through.
    resp_b = await api_client.get(_url(token_b))
    assert resp_b.status_code == 200, f"token B was staged after the edit and must still serve: {resp_b.text}"


@pytest.mark.asyncio
async def test_second_staging_supersedes_the_older_link_even_without_an_edit(
    api_client: AsyncClient, db_manager, tenant_key: str
) -> None:
    """PINNED CONSEQUENCE of the per-token anchor: re-staging supersedes the older link.

    Staging stamps ``last_exported_at`` on the packaged templates, and that UPDATE
    fires ``AgentTemplate.updated_at``'s ``onupdate=now()``. So token B's staging
    pushes the tenant's content watermark past token A's ``staged_at`` even when the
    user changed NOTHING — and A is refused.

    This is a DELIBERATE, fail-closed trade of the approved design, not a bug:
      * it only fires in the rare two-live-tokens-inside-15-minutes case;
      * it errs toward refusing a link rather than serving possibly-stale bytes;
      * the newest link — the one the user just generated — always works, which is
        the link they actually follow.
    Distinguishing an export-stamp bump from a real user edit at the watermark level
    is not possible without a separate edit-tracking column (a larger design change,
    deliberately out of scope for this single-concern task).

    This test exists so the behavior is a STATED CONTRACT: anyone "fixing" this
    refusal must not do it by widening the anchor back toward the tenant-global
    watermark, which is exactly the masking bug TSK-9210 closes.
    """
    token_a = await _stage_token(db_manager, tenant_key)
    token_b = await _stage_token(db_manager, tenant_key)  # no edit in between

    resp_a = await api_client.get(_url(token_a))
    assert resp_a.status_code == 410, f"expected the superseded older link to be refused, got {resp_a.status_code}"

    resp_b = await api_client.get(_url(token_b))
    assert resp_b.status_code == 200, f"the newest link must always serve: {resp_b.text}"


@pytest.mark.asyncio
async def test_legacy_null_staged_at_still_refuses_a_stale_link(
    api_client: AsyncClient, db_manager, tenant_key: str
) -> None:
    """Tolerance (data-facing DoD): a pre-upgrade token (staged_at IS NULL) keeps BE-9208 behavior.

    No backfill runs, so tokens minted before the migration carry NULL. They must
    fall back to the tenant-global export watermark — not error, and not be
    blanket-refused.
    """
    token = await _stage_token(db_manager, tenant_key)
    await _null_out_staged_at(db_manager, tenant_key, token)
    await _edit_template(db_manager, tenant_key)

    resp = await api_client.get(_url(token))
    assert resp.status_code == 410, (
        f"legacy NULL-staged_at token with a post-staging edit must still be refused via the "
        f"export-watermark fallback — got {resp.status_code}"
    )


@pytest.mark.asyncio
async def test_legacy_null_staged_at_fresh_link_still_served(
    api_client: AsyncClient, db_manager, tenant_key: str
) -> None:
    """The load-bearing half of tolerance: a legacy token with NO post-staging write still serves 200.

    Guards against the fallback degrading into "NULL means refuse", which would
    410 every in-flight link the moment the migration lands.
    """
    token = await _stage_token(db_manager, tenant_key)
    await _null_out_staged_at(db_manager, tenant_key, token)

    resp = await api_client.get(_url(token))
    assert resp.status_code == 200, f"legacy token with no post-staging write must still serve: {resp.text}"
