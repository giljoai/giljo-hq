# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from giljo_mcp.models import Configuration
from giljo_mcp.prompts.orchestrator_seed import ORCHESTRATOR_SEED_INSTRUCTIONS
from giljo_mcp.system_prompts.identity_provenance import format_identity_source
from giljo_mcp.system_prompts.service import (
    MAX_PROMPT_BYTES,
    SystemPromptService,
    product_orchestrator_config_key,
    read_orchestrator_override,
)
from giljo_mcp.template_seeder import compose_orchestrator_identity


pytestmark = pytest.mark.asyncio

OLD_SEED = "# Built-in orchestrator\n\nOLD SEED RULE: the retired instruction."
NEW_SEED = "# Built-in orchestrator\n\nNEW SEED RULE: the corrected instruction."
ADDITIONS = "## House notice\n\nThis deployment builds itself."
PRODUCT_ADDITIONS = "## Product notice\n\nThis product ships weekly."
LEGACY_TEXT = "A full replacement prompt saved before additions existed.\n\n  trailing spaces kept  "


def _product_id() -> str:
    return str(uuid.uuid4())


def _tenant_key() -> str:
    return f"tk_be9754a_{uuid.uuid4().hex[:12]}"


def _use_seed(monkeypatch, text: str) -> None:
    monkeypatch.setattr("giljo_mcp.template_seeder._get_user_facing_orchestrator_seed", lambda: text)


async def _store_raw(session, tenant_key: str, key: str, value: dict) -> None:
    await session.execute(
        pg_insert(Configuration).values(
            tenant_key=tenant_key, project_id=None, key=key, value=value, category="system", description="raw"
        )
    )




async def test_saved_additions_follow_a_seed_change(db_manager, db_session, monkeypatch):
    tenant_key, product_id = _tenant_key(), _product_id()
    _use_seed(monkeypatch, OLD_SEED)
    await SystemPromptService(db_manager=db_manager).update_orchestrator_additions(
        tenant_key=tenant_key, additions=ADDITIONS, updated_by="admin", product_id=product_id, session=db_session
    )

    _use_seed(monkeypatch, NEW_SEED)
    resolved = await read_orchestrator_override(
        db_manager=db_manager, tenant_key=tenant_key, product_id=product_id, session=db_session
    )
    identity = compose_orchestrator_identity(resolved.content, tool="multi_terminal")

    assert "NEW SEED RULE" in identity
    assert "OLD SEED RULE" not in identity
    assert ADDITIONS in identity
    assert identity.index("NEW SEED RULE") < identity.index(ADDITIONS)
    assert resolved.mode == "additions"


async def test_an_additions_row_stored_by_any_writer_is_layered_on_the_seed(db_manager, db_session, monkeypatch):
    tenant_key, product_id = _tenant_key(), _product_id()
    _use_seed(monkeypatch, NEW_SEED)
    await _store_raw(
        db_session,
        tenant_key,
        product_orchestrator_config_key(product_id),
        {"mode": "additions", "additions": ADDITIONS, "updated_by": "admin", "updated_at": "2026-10-08T12:00:00+00:00"},
    )

    record = await SystemPromptService(db_manager=db_manager).get_orchestrator_prompt(
        tenant_key=tenant_key, product_id=product_id, session=db_session
    )

    assert record.content.startswith(NEW_SEED)
    assert record.content.endswith(ADDITIONS)
    assert record.is_override is True
    assert record.mode == "additions"
    assert record.additions == ADDITIONS
    assert record.scope == "product"




async def test_legacy_row_without_mode_is_served_byte_identically(db_manager, db_session, monkeypatch):
    tenant_key, product_id = _tenant_key(), _product_id()
    _use_seed(monkeypatch, NEW_SEED)
    await _store_raw(
        db_session,
        tenant_key,
        product_orchestrator_config_key(product_id),
        {"content": LEGACY_TEXT, "updated_by": "admin", "updated_at": "2026-07-03T09:00:00+00:00"},
    )

    record = await SystemPromptService(db_manager=db_manager).get_orchestrator_prompt(
        tenant_key=tenant_key, product_id=product_id, session=db_session
    )
    resolved = await read_orchestrator_override(
        db_manager=db_manager, tenant_key=tenant_key, product_id=product_id, session=db_session
    )

    assert record.content == LEGACY_TEXT
    assert record.mode == "replace"
    assert record.additions is None
    assert resolved.content == LEGACY_TEXT
    assert compose_orchestrator_identity(resolved.content) == compose_orchestrator_identity(LEGACY_TEXT)
    assert "NEW SEED RULE" not in compose_orchestrator_identity(resolved.content)


async def test_legacy_content_put_still_writes_a_replace_row(db_manager, db_session, monkeypatch):
    tenant_key = _tenant_key()
    _use_seed(monkeypatch, NEW_SEED)
    record = await SystemPromptService(db_manager=db_manager).update_orchestrator_prompt(
        tenant_key=tenant_key,
        content="Whole replacement.",
        updated_by="admin",
        product_id=_product_id(),
        session=db_session,
    )

    assert record.content == "Whole replacement."
    assert record.mode == "replace"
    assert record.additions is None


async def test_seed_answer_reports_no_mode(db_manager, db_session):
    record = await SystemPromptService(db_manager=db_manager).get_orchestrator_prompt(
        tenant_key=_tenant_key(), session=db_session
    )
    assert record.is_override is False
    assert record.mode is None
    assert record.additions is None




async def test_each_product_resolves_its_own_additions(db_manager, db_session, monkeypatch):
    tenant_key = _tenant_key()
    product_id, other_product = _product_id(), _product_id()
    _use_seed(monkeypatch, NEW_SEED)
    service = SystemPromptService(db_manager=db_manager)
    await service.update_orchestrator_additions(
        tenant_key=tenant_key, additions=ADDITIONS, updated_by="admin", product_id=other_product, session=db_session
    )
    await service.update_orchestrator_additions(
        tenant_key=tenant_key,
        additions=PRODUCT_ADDITIONS,
        updated_by="admin",
        product_id=product_id,
        session=db_session,
    )

    product_record = await service.get_orchestrator_prompt(
        tenant_key=tenant_key, product_id=product_id, session=db_session
    )
    other_record = await service.get_orchestrator_prompt(
        tenant_key=tenant_key, product_id=other_product, session=db_session
    )

    assert product_record.scope == "product"
    assert product_record.additions == PRODUCT_ADDITIONS
    assert product_record.content.startswith(NEW_SEED) and product_record.content.endswith(PRODUCT_ADDITIONS)
    assert ADDITIONS not in product_record.content
    assert other_record.additions == ADDITIONS
    assert other_record.content.startswith(NEW_SEED) and other_record.content.endswith(ADDITIONS)


async def test_read_rung_additions_reads_one_products_row(db_manager, db_session):
    tenant_key = _tenant_key()
    product_id, other_product = _product_id(), _product_id()
    service = SystemPromptService(db_manager=db_manager)
    await service.update_orchestrator_additions(
        tenant_key=tenant_key, additions=ADDITIONS, updated_by="admin", product_id=product_id, session=db_session
    )

    assert (
        await service.read_rung_additions(tenant_key=tenant_key, product_id=product_id, session=db_session) == ADDITIONS
    )
    assert (
        await service.read_rung_additions(tenant_key=tenant_key, product_id=other_product, session=db_session) is None
    )
    assert (
        await service.read_rung_additions(tenant_key=_tenant_key(), product_id=product_id, session=db_session) is None
    )
    assert await service.read_rung_additions(tenant_key=tenant_key, session=db_session) is None


async def test_read_rung_additions_is_none_for_a_legacy_row(db_manager, db_session):
    tenant_key, product_id = _tenant_key(), _product_id()
    service = SystemPromptService(db_manager=db_manager)
    await service.update_orchestrator_prompt(
        tenant_key=tenant_key, content=LEGACY_TEXT, updated_by="admin", product_id=product_id, session=db_session
    )
    assert await service.read_rung_additions(tenant_key=tenant_key, product_id=product_id, session=db_session) is None


async def test_saving_additions_over_a_legacy_row_converts_it(db_manager, db_session, monkeypatch):
    tenant_key, product_id = _tenant_key(), _product_id()
    _use_seed(monkeypatch, NEW_SEED)
    service = SystemPromptService(db_manager=db_manager)
    await service.update_orchestrator_prompt(
        tenant_key=tenant_key, content=LEGACY_TEXT, updated_by="admin", product_id=product_id, session=db_session
    )

    record = await service.update_orchestrator_additions(
        tenant_key=tenant_key, additions=ADDITIONS, updated_by="admin", product_id=product_id, session=db_session
    )

    assert record.mode == "additions"
    assert LEGACY_TEXT.strip() not in record.content
    assert record.content.startswith(NEW_SEED)


async def test_reset_clears_an_additions_row(db_manager, db_session, monkeypatch):
    tenant_key, product_id = _tenant_key(), _product_id()
    _use_seed(monkeypatch, NEW_SEED)
    service = SystemPromptService(db_manager=db_manager)
    await service.update_orchestrator_additions(
        tenant_key=tenant_key, additions=ADDITIONS, updated_by="admin", product_id=product_id, session=db_session
    )

    record = await service.reset_orchestrator_prompt(tenant_key=tenant_key, product_id=product_id, session=db_session)

    assert record.is_override is False
    assert record.mode is None
    assert record.content == NEW_SEED


@pytest.mark.parametrize("bad", ["", "   \n  "])
async def test_blank_additions_are_refused(db_manager, db_session, bad):
    with pytest.raises(ValueError, match="empty"):
        await SystemPromptService(db_manager=db_manager).update_orchestrator_additions(
            tenant_key=_tenant_key(), additions=bad, updated_by="admin", product_id=_product_id(), session=db_session
        )


async def test_oversized_additions_are_refused(db_manager, db_session):
    with pytest.raises(ValueError, match="limit"):
        await SystemPromptService(db_manager=db_manager).update_orchestrator_additions(
            tenant_key=_tenant_key(),
            additions="x" * (MAX_PROMPT_BYTES + 1),
            updated_by="admin",
            product_id=_product_id(),
            session=db_session,
        )


async def test_additions_are_tenant_scoped(db_manager, db_session):
    mine, theirs, product_id = _tenant_key(), _tenant_key(), _product_id()
    service = SystemPromptService(db_manager=db_manager)
    await service.update_orchestrator_additions(
        tenant_key=theirs, additions=ADDITIONS, updated_by="a", product_id=product_id, session=db_session
    )

    record = await service.get_orchestrator_prompt(tenant_key=mine, product_id=product_id, session=db_session)
    assert record.is_override is False
    assert ADDITIONS not in record.content


async def test_product_additions_row_lives_under_the_product_key(db_manager, db_session):
    from sqlalchemy import select

    tenant_key = _tenant_key()
    product_id = str(uuid.uuid4())
    await SystemPromptService(db_manager=db_manager).update_orchestrator_additions(
        tenant_key=tenant_key,
        additions=PRODUCT_ADDITIONS,
        updated_by="admin",
        product_id=product_id,
        session=db_session,
    )
    row = (
        await db_session.execute(
            select(Configuration).where(
                Configuration.tenant_key == tenant_key,
                Configuration.key == product_orchestrator_config_key(product_id),
            )
        )
    ).scalar_one()

    assert row.value["mode"] == "additions"
    assert row.value["additions"] == PRODUCT_ADDITIONS
    assert "content" not in row.value




async def test_served_identity_is_seed_then_additions_then_harness(db_manager, db_session):
    tenant_key, product_id = _tenant_key(), _product_id()
    await SystemPromptService(db_manager=db_manager).update_orchestrator_additions(
        tenant_key=tenant_key, additions=ADDITIONS, updated_by="admin", product_id=product_id, session=db_session
    )
    resolved = await read_orchestrator_override(
        db_manager=db_manager, tenant_key=tenant_key, product_id=product_id, session=db_session
    )

    identity = compose_orchestrator_identity(resolved.content, tool="multi_terminal")
    seed_only = compose_orchestrator_identity(None, tool="multi_terminal")
    seed_body, harness = seed_only.split("\n\n---\n\n", 1)

    assert identity.startswith(seed_body)
    assert identity.endswith(harness)
    assert identity.index(ADDITIONS) > len(seed_body)
    assert identity.index(ADDITIONS) < identity.rindex(harness)

    conductor = compose_orchestrator_identity(resolved.content, tool="multi_terminal", role="conductor")
    assert ADDITIONS in conductor
    assert "## Three-Phase Workflow" not in conductor




async def test_provenance_names_built_in_plus_additions():
    saved = datetime(2026, 10, 8, 12, tzinfo=UTC)
    assert (
        format_identity_source("product", updated_at=saved, product_name="Acme", mode="additions")
        == "identity source: built-in + your product additions for Acme (saved 2026-10-08)"
    )
    assert (
        format_identity_source("product", updated_at=saved, mode="additions")
        == "identity source: built-in + your product additions (saved 2026-10-08)"
    )
    assert format_identity_source("product", mode="additions") == "identity source: built-in + your product additions"


async def test_provenance_for_legacy_and_seed_is_unchanged():
    saved = datetime(2026, 7, 3, tzinfo=UTC)
    assert (
        format_identity_source("product", updated_at=saved, product_name="Acme", mode="replace")
        == "identity source: product override (Acme), saved 2026-07-03"
    )
    assert (
        format_identity_source("product", updated_at=saved, product_name="Acme")
        == "identity source: product override (Acme), saved 2026-07-03"
    )
    assert format_identity_source("default") == "identity source: built-in default"




async def test_seed_git_and_test_rules_are_conditional():
    git_body = ORCHESTRATOR_SEED_INSTRUCTIONS.split("## Git: One Committer Per Working Tree\n\n", 1)[1]
    assert git_body.startswith("If the project uses git:")
    assert "(7) the git instruction, if the project uses git;" in ORCHESTRATOR_SEED_INSTRUCTIONS

    accepting = ORCHESTRATOR_SEED_INSTRUCTIONS.split("## Accepting Deliverables\n\n", 1)[1].split("\n## ", 1)[0]
    assert "Where the project has tests" in accepting
    assert "otherwise, a before/after observation of the behaviour" in accepting
