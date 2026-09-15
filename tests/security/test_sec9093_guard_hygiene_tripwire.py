# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

import types
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy import update as sql_update

from giljo_mcp import signals, tenant_guard
from giljo_mcp.models.auth import APIKey, User
from giljo_mcp.models.templates import AgentTemplate, TemplateArchive
from giljo_mcp.repositories.template_repository import TemplateRepository
from giljo_mcp.tenant import TenantManager


@pytest.fixture(autouse=True)
def _clean_signal_observers():
    signals.clear_signal_observers()
    yield
    signals.clear_signal_observers()


def _tk() -> str:
    return TenantManager.generate_tenant_key()


def _classb_warns(caplog, model_name: str, stype: str) -> list[str]:
    out = []
    for rec in caplog.records:
        if rec.name != "giljo_mcp.tenant_guard":
            continue
        msg = rec.getMessage()
        if (
            "no tenant predicate injectable" in msg
            and "carries an explicit" not in msg
            and f"touching: {model_name}" in msg
            and f"statement_type={stype}" in msg
        ):
            out.append(msg)
    return out


async def _mk_user(session, tenant: str) -> User:
    user = User(
        id=str(uuid4()),
        tenant_key=tenant,
        username=f"u_{uuid4().hex[:8]}",
        email=f"{uuid4().hex[:8]}@ex.com",
        password_hash="x",
        role="developer",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _mk_apikey(session, tenant: str, user_id: str, last_used=None) -> APIKey:
    key = APIKey(
        id=str(uuid4()),
        tenant_key=tenant,
        user_id=user_id,
        name="k",
        key_hash=f"h_{uuid4().hex}",
        key_prefix="gk_test",
        permissions=[],
        last_used=last_used,
    )
    session.add(key)
    await session.flush()
    return key


async def _mk_template(session, tenant: str) -> AgentTemplate:
    tpl = AgentTemplate(
        id=str(uuid4()),
        tenant_key=tenant,
        name="orchestrator",
        category="core",
        system_instructions="do things",
    )
    session.add(tpl)
    await session.flush()
    return tpl


async def _mk_archive(session, tenant: str, template_id: str) -> TemplateArchive:
    arc = TemplateArchive(
        id=str(uuid4()),
        tenant_key=tenant,
        template_id=template_id,
        name="orchestrator",
        category="core",
        version="1.0.0",
    )
    session.add(arc)
    await session.flush()
    return arc


@pytest.mark.asyncio
async def test_apikey_update_real_path_is_quiet(db_session, caplog):
    from giljo_mcp.auth.dependencies import _record_api_key_usage

    tenant_a = _tk()
    user_a = await _mk_user(db_session, tenant_a)
    key_a = await _mk_apikey(db_session, tenant_a, user_a.id)
    await db_session.commit()
    db_session.info["tenant_key"] = tenant_a
    tenant_guard._AUDIT_WARN_SEEN.clear()

    fake_request = types.SimpleNamespace(client=types.SimpleNamespace(host="192.0.2.9"))
    with caplog.at_level("WARNING", logger="giljo_mcp.tenant_guard"):
        await _record_api_key_usage(db_session, fake_request, key_a.id)

    assert _classb_warns(caplog, "APIKey", "update") == [], "APIKey update must not warn Class-B after fix"


@pytest.mark.asyncio
async def test_apikey_update_fixed_stmt_is_scoped(db_session):
    tenant_a, tenant_b = _tk(), _tk()
    user_a = await _mk_user(db_session, tenant_a)
    user_b = await _mk_user(db_session, tenant_b)
    key_a = await _mk_apikey(db_session, tenant_a, user_a.id)
    key_b = await _mk_apikey(db_session, tenant_b, user_b.id)
    await db_session.flush()
    db_session.info["tenant_key"] = tenant_a
    now = datetime.now(UTC)

    await db_session.execute(
        sql_update(APIKey.__table__).where(APIKey.__table__.c.id == key_a.id).values(last_used=now)
    )
    await db_session.execute(
        sql_update(APIKey.__table__).where(APIKey.__table__.c.id == key_b.id).values(last_used=now)
    )
    await db_session.flush()

    a = (
        await db_session.execute(select(APIKey).where(APIKey.id == key_a.id).execution_options(populate_existing=True))
    ).scalar_one()
    assert a.last_used is not None
    db_session.info["tenant_key"] = tenant_b
    b = (
        await db_session.execute(select(APIKey).where(APIKey.id == key_b.id).execution_options(populate_existing=True))
    ).scalar_one()
    assert b.last_used is None


@pytest.mark.asyncio
async def test_apikey_update_mapped_class_now_injects(db_session, caplog):
    tenant_a = _tk()
    user_a = await _mk_user(db_session, tenant_a)
    key_a = await _mk_apikey(db_session, tenant_a, user_a.id)
    await db_session.commit()
    db_session.info["tenant_key"] = tenant_a
    tenant_guard._AUDIT_WARN_SEEN.clear()

    with caplog.at_level("WARNING", logger="giljo_mcp.tenant_guard"):
        await db_session.execute(sql_update(APIKey).where(APIKey.id == key_a.id).values(last_used=datetime.now(UTC)))
    assert _classb_warns(caplog, "APIKey", "update") == [], "mapped-class update(APIKey) now injects, no Class-B warn"


@pytest.mark.asyncio
async def test_template_archive_delete_is_quiet_and_tenant_scoped(db_session, caplog):
    tenant_a, tenant_b = _tk(), _tk()
    tpl_a = await _mk_template(db_session, tenant_a)
    tpl_b = await _mk_template(db_session, tenant_b)
    arc_a = await _mk_archive(db_session, tenant_a, tpl_a.id)
    arc_b = await _mk_archive(db_session, tenant_b, tpl_b.id)
    await db_session.commit()
    db_session.info["tenant_key"] = tenant_a
    tenant_guard._AUDIT_WARN_SEEN.clear()

    repo = TemplateRepository()
    with caplog.at_level("WARNING", logger="giljo_mcp.tenant_guard"):
        await repo.delete_archives(db_session, tpl_a.id)
    await db_session.flush()

    assert _classb_warns(caplog, "TemplateArchive", "delete") == []
    assert (
        await db_session.execute(select(TemplateArchive).where(TemplateArchive.id == arc_a.id))
    ).scalar_one_or_none() is None
    db_session.info["tenant_key"] = tenant_b
    assert (
        await db_session.execute(select(TemplateArchive).where(TemplateArchive.id == arc_b.id))
    ).scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_template_archive_delete_mapped_class_now_injects(db_session, caplog):
    tenant_a = _tk()
    tpl_a = await _mk_template(db_session, tenant_a)
    await _mk_archive(db_session, tenant_a, tpl_a.id)
    await db_session.commit()
    db_session.info["tenant_key"] = tenant_a
    tenant_guard._AUDIT_WARN_SEEN.clear()

    with caplog.at_level("WARNING", logger="giljo_mcp.tenant_guard"):
        await db_session.execute(sql_delete(TemplateArchive).where(TemplateArchive.template_id == tpl_a.id))
    assert _classb_warns(caplog, "TemplateArchive", "delete") == [], (
        "mapped-class delete(TemplateArchive) now injects, no Class-B warn"
    )


@pytest.mark.asyncio
async def test_agent_template_update_raw_is_quiet_and_scoped(db_session, caplog):
    tenant_a, tenant_b = _tk(), _tk()
    tpl_a = await _mk_template(db_session, tenant_a)
    tpl_b = await _mk_template(db_session, tenant_b)
    await db_session.commit()
    db_session.info["tenant_key"] = tenant_a
    tenant_guard._AUDIT_WARN_SEEN.clear()
    backdate = datetime(2020, 1, 1, tzinfo=UTC)

    t = AgentTemplate.__table__
    with caplog.at_level("WARNING", logger="giljo_mcp.tenant_guard"):
        await db_session.execute(sql_update(t).where(t.c.id == tpl_a.id).values(updated_at=backdate))
    assert _classb_warns(caplog, "AgentTemplate", "update") == []

    tenant_guard._AUDIT_WARN_SEEN.clear()
    await db_session.execute(sql_update(t).where(t.c.id == tpl_b.id).values(updated_at=backdate))
    await db_session.flush()
    db_session.info["tenant_key"] = tenant_b
    refreshed_b = (
        await db_session.execute(
            select(AgentTemplate).where(AgentTemplate.id == tpl_b.id).execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert refreshed_b.updated_at != backdate


@pytest.mark.asyncio
async def test_agent_template_update_mapped_class_now_injects(db_session, caplog):
    tenant_a = _tk()
    tpl_a = await _mk_template(db_session, tenant_a)
    await db_session.commit()
    db_session.info["tenant_key"] = tenant_a
    tenant_guard._AUDIT_WARN_SEEN.clear()

    with caplog.at_level("WARNING", logger="giljo_mcp.tenant_guard"):
        await db_session.execute(
            sql_update(AgentTemplate).where(AgentTemplate.id == tpl_a.id).values(updated_at=datetime.now(UTC))
        )
    assert _classb_warns(caplog, "AgentTemplate", "update") == [], (
        "mapped-class update(AgentTemplate) now injects, no Class-B warn"
    )


@pytest.mark.asyncio
async def test_classb_triggers_sentry_capture_classa_does_not(db_session, monkeypatch):
    calls = []
    signals.register_signal_observer(
        signals.SIGNAL_UNSCOPED_WRITE,
        lambda payload: calls.append((tuple(payload["models"]), payload["statement_type"])),
    )
    monkeypatch.setattr(tenant_guard, "_tenant_models_for_statement", lambda statement: frozenset({APIKey}))
    tenant_a = _tk()
    db_session.info["tenant_key"] = tenant_a

    tenant_guard._AUDIT_WARN_SEEN.clear()
    with pytest.raises(tenant_guard.TenantIsolationError):
        await db_session.execute(sql_delete(TemplateArchive).where(TemplateArchive.id == "no-such-id"))
    assert calls == [(("APIKey",), "delete")], "Class-B (predicate-absent, uninjectable) must announce once"

    calls.clear()
    tenant_guard._AUDIT_WARN_SEEN.clear()
    await db_session.execute(sql_delete(TemplateArchive).where(TemplateArchive.tenant_key == tenant_a))
    assert calls == [], "Class-A (explicit predicate present) must NOT announce"
