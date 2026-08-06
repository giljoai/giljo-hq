# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.
"""SEC-9093 regressions.

D1 -- three genuinely-unscoped Class-B call sites are scoped so the tenant guard stops
     warning (and the write stays tenant-isolated on the happy path):
       * APIKey.last_used update   (auth/dependencies.py _record_api_key_usage)
       * AgentTemplate updated_at restore (services/template_service.py)
       * TemplateArchive delete    (repositories/template_repository.py delete_archives)
     The fix targets the RAW table so the guard injects the tenant predicate. A mapped-class
     bulk UPDATE/DELETE wraps the table in an AnnotatedTable the guard cannot match -- and
     merely adding an explicit tenant predicate to the mapped class only flips Class-B ->
     Class-A (still warns); the raw table is what makes it go quiet. These tests pin both the
     "raw is quiet" and the "mapped warns" halves so a revert is caught.

D2 -- the guard's _audit_warn routes ONLY the predicate-absent (Class-B) UPDATE/DELETE class
     to the SaaS Sentry tripwire, fail-open and env-gated (no-op in CE / without a DSN).
"""

import sys
import types
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy import update as sql_update

from giljo_mcp import tenant_guard
from giljo_mcp.models.auth import APIKey, User
from giljo_mcp.models.templates import AgentTemplate, TemplateArchive
from giljo_mcp.repositories.template_repository import TemplateRepository
from giljo_mcp.tenant import TenantManager


def _tk() -> str:
    return TenantManager.generate_tenant_key()


def _classb_warns(caplog, model_name: str, stype: str) -> list[str]:
    """Class-B == 'no tenant predicate injectable' for <model>/<stype> WITHOUT the
    'carries an explicit tenant predicate' clause."""
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


# ---------------------------------------------------------------------------
# D1 -- APIKey.last_used update (real path: _record_api_key_usage)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_apikey_update_real_path_is_quiet(db_session, caplog):
    """Real production path (_record_api_key_usage) no longer warns Class-B."""
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
    """The fixed raw-table form stamps only the in-tenant key and leaves other tenants alone."""
    tenant_a, tenant_b = _tk(), _tk()
    user_a = await _mk_user(db_session, tenant_a)
    user_b = await _mk_user(db_session, tenant_b)
    key_a = await _mk_apikey(db_session, tenant_a, user_a.id)
    key_b = await _mk_apikey(db_session, tenant_b, user_b.id)
    await db_session.flush()
    db_session.info["tenant_key"] = tenant_a
    now = datetime.now(UTC)

    # exact fixed form from auth/dependencies.py (guard injects AND tenant_key == <ctx>)
    await db_session.execute(
        sql_update(APIKey.__table__).where(APIKey.__table__.c.id == key_a.id).values(last_used=now)
    )
    # cross-tenant probe: target B's id under tenant-A context -> guard scopes it out.
    await db_session.execute(
        sql_update(APIKey.__table__).where(APIKey.__table__.c.id == key_b.id).values(last_used=now)
    )
    await db_session.flush()

    # bulk UPDATE bypasses the identity map; populate_existing forces a fresh DB read.
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
    """SEC-9094 flip: the mapped-class form now INJECTS (matcher unwraps the AnnotatedTable), so it
    no longer emits a Class-B warn -- it is quiet, exactly like the raw-table form. (Pre-SEC-9094
    this shape warned; the D1 fix targeted the raw table precisely because the mapped shape could
    not inject. SEC-9094 closed that gap, so both shapes are now equivalent.)"""
    tenant_a = _tk()
    user_a = await _mk_user(db_session, tenant_a)
    key_a = await _mk_apikey(db_session, tenant_a, user_a.id)
    await db_session.commit()
    db_session.info["tenant_key"] = tenant_a
    tenant_guard._AUDIT_WARN_SEEN.clear()

    with caplog.at_level("WARNING", logger="giljo_mcp.tenant_guard"):
        await db_session.execute(sql_update(APIKey).where(APIKey.id == key_a.id).values(last_used=datetime.now(UTC)))
    assert _classb_warns(caplog, "APIKey", "update") == [], "mapped-class update(APIKey) now injects, no Class-B warn"


# ---------------------------------------------------------------------------
# D1 -- TemplateArchive delete (real path: delete_archives)
# ---------------------------------------------------------------------------
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
    # A's archive gone; B's archive survives.
    assert (
        await db_session.execute(select(TemplateArchive).where(TemplateArchive.id == arc_a.id))
    ).scalar_one_or_none() is None
    db_session.info["tenant_key"] = tenant_b
    assert (
        await db_session.execute(select(TemplateArchive).where(TemplateArchive.id == arc_b.id))
    ).scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_template_archive_delete_mapped_class_now_injects(db_session, caplog):
    """SEC-9094 flip: mapped-class delete(TemplateArchive) now injects the tenant predicate
    (matcher unwraps the AnnotatedTable) -- no longer a Class-B warn."""
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


# ---------------------------------------------------------------------------
# D1 -- AgentTemplate updated_at restore (statement-level: raw quiet vs mapped warns)
# ---------------------------------------------------------------------------
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
        # exact fixed form from template_service.py (raw table -> guard injects tenant_key)
        await db_session.execute(sql_update(t).where(t.c.id == tpl_a.id).values(updated_at=backdate))
    assert _classb_warns(caplog, "AgentTemplate", "update") == []

    # cross-tenant: target B's id under tenant-A context; the guard-injected tenant predicate
    # (== tenant_a) must scope it out so B is never touched.
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
    """SEC-9094 flip: mapped-class update(AgentTemplate) now injects the tenant predicate
    (matcher unwraps the AnnotatedTable) -- no longer a Class-B warn."""
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


# ---------------------------------------------------------------------------
# D2 -- classify-and-capture: only the predicate-absent (Class-B) class hits Sentry
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_classb_triggers_sentry_capture_classa_does_not(db_session, monkeypatch):
    """After SEC-9094 the mapped-class direct-table shape INJECTS, so it is no longer a tripwire
    class. The remaining warn/tripwire class is a genuinely-uninjectable UPDATE/DELETE whose target
    table is NOT itself a detected tenant model. We force that shape deterministically (walk reports
    an unrelated tenant model while the DELETE targets a different table -- the same technique as
    test_sec9156_guard_failclosed.py) and re-assert the D2 classification: the predicate-ABSENT
    (Class-B) case feeds the Sentry tripwire (and, since SEC-9156 shipped Step 2, now also raises);
    the explicit-predicate (Class-A) case does neither."""
    calls = []
    monkeypatch.setattr(
        tenant_guard,
        "_capture_unscoped_write_to_sentry",
        lambda model_names, statement_type, path: calls.append((tuple(model_names), statement_type)),
    )
    # Walk reports APIKey as "touched" while the DELETE targets TemplateArchive's table -> no model
    # matches the target -> nothing injectable -> the no-match tripwire branch (never injects/executes
    # a cross-tenant write here: the guard just classifies + records).
    monkeypatch.setattr(tenant_guard, "_tenant_models_for_statement", lambda statement: frozenset({APIKey}))
    tenant_a = _tk()
    db_session.info["tenant_key"] = tenant_a

    # Class-B: no explicit tenant predicate -> capture fires once, then the guard raises (SEC-9156).
    tenant_guard._AUDIT_WARN_SEEN.clear()
    with pytest.raises(tenant_guard.TenantIsolationError):
        await db_session.execute(sql_delete(TemplateArchive).where(TemplateArchive.id == "no-such-id"))
    assert calls == [(("APIKey",), "delete")], "Class-B (predicate-absent, uninjectable) must feed the tripwire once"

    # Class-A: an explicit tenant predicate is present -> capture must NOT fire.
    calls.clear()
    tenant_guard._AUDIT_WARN_SEEN.clear()
    await db_session.execute(sql_delete(TemplateArchive).where(TemplateArchive.tenant_key == tenant_a))
    assert calls == [], "Class-A (explicit predicate present) must NOT feed the tripwire"


# ---------------------------------------------------------------------------
# D2 -- helper env-gating + fail-open (unit)
# ---------------------------------------------------------------------------
def _fake_sentry(record: list):
    scope = types.SimpleNamespace(set_tag=lambda *a, **k: None, set_context=lambda *a, **k: None)

    class _Scope:
        def __enter__(self):
            return scope

        def __exit__(self, *a):
            return False

    mod = types.ModuleType("sentry_sdk")
    mod.new_scope = _Scope
    mod.capture_message = lambda msg, level=None: record.append((msg, level))
    return mod


def test_capture_noop_in_ce(monkeypatch):
    record = []
    monkeypatch.delenv("GILJO_MODE", raising=False)
    monkeypatch.setenv("SENTRY_DSN_BACKEND", "https://x@example/1")
    monkeypatch.setitem(sys.modules, "sentry_sdk", _fake_sentry(record))
    tenant_guard._capture_unscoped_write_to_sentry(["Task"], "delete", None)
    assert record == [], "CE (GILJO_MODE unset) must never capture"


def test_capture_noop_without_dsn(monkeypatch):
    record = []
    monkeypatch.setenv("GILJO_MODE", "saas")
    monkeypatch.delenv("SENTRY_DSN_BACKEND", raising=False)
    monkeypatch.setitem(sys.modules, "sentry_sdk", _fake_sentry(record))
    tenant_guard._capture_unscoped_write_to_sentry(["Task"], "delete", None)
    assert record == [], "SaaS without a DSN must never capture"


def test_capture_fires_in_saas_with_dsn(monkeypatch):
    record = []
    monkeypatch.setenv("GILJO_MODE", "saas")
    monkeypatch.setenv("SENTRY_DSN_BACKEND", "https://x@example/1")
    monkeypatch.setitem(sys.modules, "sentry_sdk", _fake_sentry(record))
    tenant_guard._capture_unscoped_write_to_sentry(["Message"], "update", "/api/x")
    assert len(record) == 1
    msg, level = record[0]
    assert level == "error"
    assert "Message" in msg and "update" in msg


def test_capture_fail_open_on_sentry_error(monkeypatch):
    monkeypatch.setenv("GILJO_MODE", "saas")
    monkeypatch.setenv("SENTRY_DSN_BACKEND", "https://x@example/1")
    boom = types.ModuleType("sentry_sdk")

    def _raise():
        raise RuntimeError("sentry down")

    boom.new_scope = _raise
    monkeypatch.setitem(sys.modules, "sentry_sdk", boom)
    # Must NOT raise -- fail-open guarantees the write path is never affected.
    tenant_guard._capture_unscoped_write_to_sentry(["Task"], "delete", None)
