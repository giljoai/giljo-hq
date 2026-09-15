# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import hashlib
import json
import zipfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import DateTime, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from api.endpoints import tenant_data
from api.exception_handlers import register_exception_handlers
from giljo_mcp.auth.dependencies import get_current_active_user, get_db_session
from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import (
    CommParticipant,
    CommThread,
    Configuration,
    Message,
    Product,
    ProductArchitecture,
    ProductMemoryEntry,
    ProductTechStack,
    ProductTestConfig,
    User,
    VisionDocument,
)
from giljo_mcp.models.organizations import Organization
from giljo_mcp.services.capture_tables import capture_models
from giljo_mcp.services.tenant_export_service import (
    TenantExportService,
    _fidelity_restore_order,
    _to_json_safe,
)
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio




async def _seed_user(
    db_session: AsyncSession,
    tenant_key: str,
    *,
    password_hash: str = "$2b$12$abcdefghijklmnopqrstuv",
    recovery_pin_hash: str = "$2b$12$PIN_HASH_SECRET_VALUE12",
    username_suffix: str | None = None,
) -> User:
    suffix = username_suffix or uuid4().hex[:8]
    org = Organization(
        name=f"Org {suffix}",
        slug=f"org-{suffix}",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(org)
    await db_session.flush()

    user = User(
        username=f"user_{suffix}",
        email=f"u_{suffix}@example.com",
        password_hash=password_hash,
        recovery_pin_hash=recovery_pin_hash,
        tenant_key=tenant_key,
        role="developer",
        org_id=org.id,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _seed_product(db_session: AsyncSession, tenant_key: str, name: str = "P") -> Product:
    product = Product(
        id=str(uuid4()),
        name=name,
        description="seed",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(product)
    await db_session.flush()
    return product




async def test_export_strips_credentials(db_session: AsyncSession) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    secret_pw = "$2b$12$NEEDLE_PASSWORD_HASH_VALUE"
    secret_pin = "$2b$12$NEEDLE_PIN_HASH_VALUE_X"
    await _seed_user(db_session, tenant_key, password_hash=secret_pw, recovery_pin_hash=secret_pin)
    await db_session.commit()

    service = TenantExportService(db_session=db_session)
    zip_path, _ = await service.export(tenant_key=tenant_key)

    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            if name.startswith("data/") and name.endswith(".json"):
                blob = zf.read(name)
                assert secret_pw.encode() not in blob, f"password_hash leaked in {name}"
                assert secret_pin.encode() not in blob, f"recovery_pin_hash leaked in {name}"


async def test_export_strips_platform_metadata(db_session: AsyncSession) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    user = await _seed_user(db_session, tenant_key)
    needle = "ctm_NEEDLE_BILLING_CUSTOMER"
    from giljo_mcp.models import Configuration

    cfg = Configuration(
        tenant_key=tenant_key,
        key="billing.customer_id",
        value=needle,
        category="billing",
    )
    db_session.add(cfg)
    object.__setattr__(user, "customer_id", "ctm_FIELD_NEEDLE_USER")
    await db_session.commit()

    service = TenantExportService(db_session=db_session)
    zip_path, _ = await service.export(tenant_key=tenant_key)

    with zipfile.ZipFile(zip_path, "r") as zf:
        user_blob = zf.read("data/User.json")
        assert b"cus_FIELD_NEEDLE_USER" not in user_blob


async def test_export_strips_tenant_key_from_rows(db_session: AsyncSession) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    await _seed_user(db_session, tenant_key)
    await _seed_product(db_session, tenant_key)
    await db_session.commit()

    service = TenantExportService(db_session=db_session)
    zip_path, _ = await service.export(tenant_key=tenant_key)

    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            if name.startswith("data/") and name.endswith(".json"):
                rows = json.loads(zf.read(name))
                assert isinstance(rows, list)
                for row in rows:
                    assert "tenant_key" not in row, f"tenant_key leaked in {name}"
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["tenant_key"] == tenant_key


async def test_export_redacts_tenant_key_values_in_text_and_jsonb(
    db_session: AsyncSession,
) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    await _seed_user(db_session, tenant_key)
    from giljo_mcp.models import Configuration

    foreign_tk = "tk_FOREIGN0123456789ABCDEFGHIJKL"
    cfg = Configuration(
        tenant_key=tenant_key,
        key="diag.last_seen_tenant_keys",
        value={"observed": [foreign_tk, "tk_OTHER9876543210ZZZZZZZZZZZZZZ"]},
        category="diagnostics",
    )
    db_session.add(cfg)
    await db_session.commit()

    service = TenantExportService(db_session=db_session)
    zip_path, _ = await service.export(tenant_key=tenant_key)

    import re as _re

    pattern = _re.compile(rb"tk_[A-Za-z0-9]{20,}")
    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            if name.startswith("data/") and name.endswith(".json"):
                blob = zf.read(name)
                matches = pattern.findall(blob)
                assert not matches, f"tenant_key value(s) leaked in {name}: {matches[:3]}"
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["tenant_key"] == tenant_key


async def test_export_excludes_ephemeral_tables(db_session: AsyncSession) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    await _seed_user(db_session, tenant_key)
    await db_session.commit()

    service = TenantExportService(db_session=db_session)
    zip_path, _ = await service.export(tenant_key=tenant_key)

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = set(zf.namelist())
        for forbidden in (
            "data/APIKey.json",
            "data/ApiKeyIpLog.json",
            "data/DownloadToken.json",
            "data/ApiMetrics.json",
            "data/OAuthAuthorizationCode.json",
            "data/MCPSession.json",
            "data/OptimizationMetric.json",
        ):
            assert forbidden not in names, f"ephemeral table leaked: {forbidden}"


async def test_export_excludes_ops_tables(db_session: AsyncSession) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    await _seed_user(db_session, tenant_key)
    await db_session.commit()

    service = TenantExportService(db_session=db_session)
    zip_path, _ = await service.export(tenant_key=tenant_key)

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = set(zf.namelist())
        assert "data/ops_audit_log.json" not in names
        assert "data/ops_billing_links.json" not in names


async def test_manifest_sha256_matches_contents(db_session: AsyncSession) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    await _seed_user(db_session, tenant_key)
    await _seed_product(db_session, tenant_key)
    await db_session.commit()

    service = TenantExportService(db_session=db_session)
    zip_path, _ = await service.export(tenant_key=tenant_key)

    with zipfile.ZipFile(zip_path, "r") as zf:
        manifest = json.loads(zf.read("manifest.json"))
        files = manifest["files"]
        assert files, "manifest.files must include at least one entry"
        for entry in files:
            zpath = entry["zip_path"]
            expected = entry["sha256"]
            actual = hashlib.sha256(zf.read(zpath)).hexdigest()
            assert actual == expected, f"checksum mismatch for {zpath}"


async def test_inline_vision_document_in_export_data(db_session: AsyncSession, tmp_path: Path) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    product = await _seed_product(db_session, tenant_key, name="VisProduct")

    vd_id = str(uuid4())
    vd = VisionDocument(
        id=vd_id,
        product_id=product.id,
        tenant_key=tenant_key,
        document_name="Readme",
        document_type="vision",
        storage_type="inline",
        vision_document="# Vision\nHello world.\n",
        vision_path=None,
    )
    db_session.add(vd)
    await db_session.commit()

    service = TenantExportService(db_session=db_session, products_root=tmp_path / "products")
    zip_path, _ = await service.export(tenant_key=tenant_key)

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        assert "data/VisionDocument.json" in names, f"VisionDocument data missing; got {names}"
        rows = json.loads(zf.read("data/VisionDocument.json"))
        assert any(row.get("id") == vd_id for row in rows), f"inline VisionDocument id not found in export rows: {rows}"
        assert not any(n.startswith("files/") for n in names), (
            f"inline docs must not be bundled as files/ entries; got {names}"
        )


async def test_export_no_file_entries_for_inline_docs(db_session: AsyncSession, tmp_path: Path) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    product = await _seed_product(db_session, tenant_key, name="VisInline")
    vd = VisionDocument(
        id=str(uuid4()),
        product_id=product.id,
        tenant_key=tenant_key,
        document_name="Inline",
        document_type="vision",
        storage_type="inline",
        vision_document="# Inline content\n",
        vision_path=None,
    )
    db_session.add(vd)
    await db_session.commit()

    service = TenantExportService(db_session=db_session, products_root=tmp_path / "products")
    zip_path, _ = await service.export(tenant_key=tenant_key)

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        assert "manifest.json" in names
        assert not any(n.startswith("files/") for n in names), (
            f"inline-only export must not contain files/ entries; got {names}"
        )


async def test_schema_md_includes_redaction_notice(db_session: AsyncSession) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    await _seed_user(db_session, tenant_key)
    await db_session.commit()

    service = TenantExportService(db_session=db_session)
    zip_path, _ = await service.export(tenant_key=tenant_key)

    with zipfile.ZipFile(zip_path, "r") as zf:
        schema_md = zf.read("schema.md").decode("utf-8")

    assert "Password hashes" in schema_md
    assert "redacted" in schema_md.lower()




def _build_app(
    db_manager,
    db_session: AsyncSession | None,
    user: User | None,
) -> FastAPI:
    app = FastAPI()
    app.include_router(tenant_data.router, prefix="/api/v1/account")
    register_exception_handlers(app)

    ws = MagicMock()
    ws.broadcast_event_to_tenant = AsyncMock()
    app.state.websocket_manager = ws

    if user is not None:

        async def _override_user() -> User:
            return user

        app.dependency_overrides[get_current_active_user] = _override_user

    if db_session is not None:

        async def _override_db() -> AsyncIterator[AsyncSession]:
            if user is not None:
                with tenant_session_context(db_session, user.tenant_key):
                    yield db_session
            else:
                yield db_session

        app.dependency_overrides[get_db_session] = _override_db

    return app


@pytest_asyncio.fixture
async def export_user(db_session: AsyncSession) -> User:
    tenant_key = TenantManager.generate_tenant_key()
    user = await _seed_user(db_session, tenant_key, username_suffix="alpha")
    await _seed_product(db_session, tenant_key, name="AlphaProduct")
    await db_session.commit()
    return user


async def test_endpoint_returns_download_url_in_ce(db_manager, db_session: AsyncSession, export_user: User) -> None:
    app = _build_app(db_manager, db_session, export_user)

    transport = ASGITransport(app=app)
    with patch("api.app_state.GILJO_MODE", "ce"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/account/export")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "download_url" in body
    assert "expires_at" in body
    assert "model_counts" in body
    assert isinstance(body["model_counts"], dict)


async def test_endpoint_200_in_saas_for_admin(db_manager, db_session: AsyncSession, export_user: User) -> None:
    export_user.role = "admin"
    db_session.add(export_user)
    await db_session.commit()

    app = _build_app(db_manager, db_session, export_user)
    transport = ASGITransport(app=app)
    with patch("api.app_state.GILJO_MODE", "saas"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/account/export")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "download_url" in body
    assert "model_counts" in body


async def test_endpoint_403_in_saas_for_non_admin(db_manager, db_session: AsyncSession, export_user: User) -> None:
    export_user.role = "developer"
    db_session.add(export_user)
    await db_session.commit()

    app = _build_app(db_manager, db_session, export_user)
    transport = ASGITransport(app=app)
    with patch("api.app_state.GILJO_MODE", "saas"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/account/export")
    assert resp.status_code == 403
    body = resp.json()
    detail = body.get("detail") or body.get("message") or ""
    assert "admin" in detail.lower()


async def test_endpoint_requires_auth(db_manager, db_session: AsyncSession) -> None:
    app = _build_app(db_manager, db_session, user=None)
    transport = ASGITransport(app=app)
    with patch("api.app_state.GILJO_MODE", "ce"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/account/export")
    assert resp.status_code in (401, 403)


async def test_endpoint_tenant_isolation(db_manager, db_session: AsyncSession) -> None:
    tk_a = TenantManager.generate_tenant_key()
    tk_b = TenantManager.generate_tenant_key()
    user_a = await _seed_user(db_session, tk_a, username_suffix="aaa")
    needle_b = f"bbb_{uuid4().hex[:8]}"
    await _seed_user(db_session, tk_b, username_suffix=needle_b)
    await _seed_product(db_session, tk_b, name="OtherTenantProduct")
    await db_session.commit()

    app = _build_app(db_manager, db_session, user_a)
    transport = ASGITransport(app=app)
    with patch("api.app_state.GILJO_MODE", "ce"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/account/export")

    assert resp.status_code == 200, resp.text

    service = TenantExportService(db_session=db_session)
    with tenant_session_context(db_session, tk_a):
        zip_path, _ = await service.export(tenant_key=tk_a)

    with zipfile.ZipFile(zip_path, "r") as zf:
        blob = b""
        for name in zf.namelist():
            if name.startswith("data/") and name.endswith(".json"):
                blob += zf.read(name)
    assert needle_b.encode() not in blob
    assert b"OtherTenantProduct" not in blob




async def test_download_type_constraint_admits_tenant_export(db_session: AsyncSession) -> None:
    from datetime import UTC, datetime, timedelta

    from giljo_mcp.models import DownloadToken

    tk = TenantManager.generate_tenant_key()
    record = DownloadToken(
        tenant_key=tk,
        download_type="tenant_export",
        filename="tenant_export.zip",
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )
    db_session.add(record)
    await db_session.commit()
    assert record.id is not None
    assert record.download_type == "tenant_export"


async def test_download_type_constraint_still_rejects_unknown(db_session: AsyncSession) -> None:
    from datetime import UTC, datetime, timedelta

    from sqlalchemy.exc import IntegrityError

    from giljo_mcp.models import DownloadToken

    tk = TenantManager.generate_tenant_key()
    record = DownloadToken(
        tenant_key=tk,
        download_type="not_a_real_type",
        filename="bogus.zip",
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )
    db_session.add(record)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()




_FIDELITY_TK_NEEDLE = "tk_FIDELITY0123456789ABCDEFGHIJ"


async def _seed_fidelity_graph(db_session: AsyncSession, tenant_key: str) -> User:
    user = await _seed_user(db_session, tenant_key, username_suffix="fidel")
    product = await _seed_product(db_session, tenant_key, name="FidelityProduct")
    product.org_id = user.org_id
    db_session.add(product)

    db_session.add(
        ProductTechStack(
            id=str(uuid4()),
            product_id=product.id,
            tenant_key=tenant_key,
            programming_languages="Python",
            backend_frameworks="FastAPI",
        )
    )
    db_session.add(
        ProductArchitecture(
            id=str(uuid4()),
            product_id=product.id,
            tenant_key=tenant_key,
            primary_pattern="layered",
            api_style="REST",
        )
    )
    db_session.add(
        ProductTestConfig(
            id=str(uuid4()),
            product_id=product.id,
            tenant_key=tenant_key,
            test_strategy="pytest",
            coverage_target=90,
        )
    )
    db_session.add(
        VisionDocument(
            id=str(uuid4()),
            product_id=product.id,
            tenant_key=tenant_key,
            document_name="Fidelity Vision",
            document_type="vision",
            storage_type="inline",
            vision_document="# Vision\nrestore-grade.\n",
            vision_path=None,
            meta_data={"author": "tester", "tags": ["a", "b"]},
        )
    )
    db_session.add(
        ProductMemoryEntry(
            id=uuid4(),
            product_id=product.id,
            tenant_key=tenant_key,
            sequence=1,
            entry_type="decision",
            source="write_360_memory_v1",
            timestamp=datetime.now(UTC),
            summary="A fidelity-mode memory entry.",
            key_outcomes=["shipped"],
            metrics={"coverage": 0.9},
            significance_score=0.75,
        )
    )
    db_session.add(
        Configuration(
            id=str(uuid4()),
            tenant_key=tenant_key,
            key="diag.observed_tenant_keys",
            value={"observed": [_FIDELITY_TK_NEEDLE]},
            category="diagnostics",
        )
    )
    thread_id = str(uuid4())
    message_id = str(uuid4())
    db_session.add(
        CommThread(
            id=thread_id,
            tenant_key=tenant_key,
            serial=1,
            subject="fidelity hub thread",
            status="active",
            next_action_owner="BE-1",
            product_id=product.id,
        )
    )
    db_session.add(
        CommParticipant(
            id=str(uuid4()),
            tenant_key=tenant_key,
            thread_id=thread_id,
            participant_id="BE-1",
            participant_type="agent",
            last_read_message_id=message_id,
            last_read_at=datetime.now(UTC),
        )
    )
    db_session.add(Message(id=message_id, tenant_key=tenant_key, thread_id=thread_id, content="anchored hub post"))
    await db_session.commit()
    return user


def _read_fidelity_dump(zip_path: Path) -> tuple[dict[str, list[dict]], dict]:
    model_rows: dict[str, list[dict]] = {}
    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            if name.startswith("data/") and name.endswith(".json"):
                model_rows[name[len("data/") : -len(".json")]] = json.loads(zf.read(name))
        manifest = json.loads(zf.read("manifest.json"))
    return model_rows, manifest


def _coerce_for_reconstruct(model: type, row: dict) -> dict:
    cols = {c.name: c for c in sa_inspect(model).columns}
    kwargs: dict = {}
    for key, val in row.items():
        col = cols.get(key)
        if col is None or val is None:
            kwargs[key] = val
        elif isinstance(col.type, DateTime):
            kwargs[key] = datetime.fromisoformat(val)
        elif isinstance(col.type, PG_UUID):
            kwargs[key] = UUID(val)
        else:
            kwargs[key] = val
    return kwargs


async def _live_instances(db_session: AsyncSession, model: type, tenant_key: str) -> dict[str, object]:
    pk_name = next(c.name for c in sa_inspect(model).primary_key)
    result = await db_session.execute(select(model).where(model.tenant_key == tenant_key))
    return {str(getattr(inst, pk_name)): inst for inst in result.scalars().all()}


async def test_fidelity_retains_tenant_key_pk_and_fk_for_every_model(db_session: AsyncSession) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    await _seed_fidelity_graph(db_session, tenant_key)

    service = TenantExportService(db_session=db_session)
    zip_path, _ = await service.export(tenant_key=tenant_key, fidelity=True)
    model_rows, _ = _read_fidelity_dump(zip_path)

    by_name = {m.__name__: m for m in capture_models()}
    seen_models = 0
    for name, rows in model_rows.items():
        if not rows:
            continue
        model = by_name[name]
        pk_cols = [c.name for c in sa_inspect(model).primary_key]
        fk_cols = [c.name for c in sa_inspect(model).columns if c.foreign_keys]
        seen_models += 1
        for row in rows:
            assert row.get("tenant_key") == tenant_key, f"{name}: tenant_key not retained in fidelity dump"
            for pk in pk_cols:
                assert pk in row and row[pk] is not None, f"{name}: primary key {pk} missing/null"
            for fk in fk_cols:
                assert fk in row, f"{name}: FK column {fk} missing from fidelity dump"

    assert seen_models >= 6, f"expected >=6 populated models, got {seen_models}"


async def test_fidelity_does_not_redact_credentials(db_session: AsyncSession) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    secret_pw = "$2b$12$FIDELITY_KEEPS_THIS_HASH"
    secret_pin = "$2b$12$FIDELITY_KEEPS_THE_PIN"
    await _seed_user(db_session, tenant_key, password_hash=secret_pw, recovery_pin_hash=secret_pin)
    await db_session.commit()

    service = TenantExportService(db_session=db_session)
    zip_path, _ = await service.export(tenant_key=tenant_key, fidelity=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        user_rows = json.loads(zf.read("data/User.json"))
    assert user_rows, "expected at least one User row"
    assert any(r.get("password_hash") == secret_pw for r in user_rows), "password_hash was redacted in fidelity mode"
    assert any(r.get("recovery_pin_hash") == secret_pin for r in user_rows), "recovery_pin_hash was redacted"


async def test_fidelity_does_not_scrub_tenant_key_values(db_session: AsyncSession) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    await _seed_fidelity_graph(db_session, tenant_key)

    service = TenantExportService(db_session=db_session)
    zip_path, _ = await service.export(tenant_key=tenant_key, fidelity=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        cfg_blob = zf.read("data/Configuration.json").decode("utf-8")
    assert _FIDELITY_TK_NEEDLE in cfg_blob, "fidelity mode wrongly scrubbed an embedded tk_ value"


async def test_fidelity_roundtrips_losslessly_for_every_model(db_session: AsyncSession) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    await _seed_fidelity_graph(db_session, tenant_key)

    service = TenantExportService(db_session=db_session)
    zip_path, _ = await service.export(tenant_key=tenant_key, fidelity=True)
    model_rows, _ = _read_fidelity_dump(zip_path)

    by_name = {m.__name__: m for m in capture_models()}
    checked = 0
    for name, rows in model_rows.items():
        if not rows:
            continue
        model = by_name[name]
        pk_name = next(c.name for c in sa_inspect(model).primary_key)
        live = await _live_instances(db_session, model, tenant_key)
        col_names = [c.name for c in sa_inspect(model).columns]
        for row in rows:
            reconstructed = model(**_coerce_for_reconstruct(model, row))
            assert reconstructed is not None
            inst = live[str(row[pk_name])]
            for col in col_names:
                assert row.get(col) == _to_json_safe(getattr(inst, col)), (
                    f"{name}.{col}: fidelity dump diverged from live row"
                )
            checked += 1
    assert checked >= 8, f"expected to round-trip >=8 rows, got {checked}"


async def test_fidelity_manifest_records_mode_revision_version_and_restore_order(db_session: AsyncSession) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    await _seed_fidelity_graph(db_session, tenant_key)

    service = TenantExportService(db_session=db_session)
    zip_path, _ = await service.export(tenant_key=tenant_key, fidelity=True)
    _, manifest = _read_fidelity_dump(zip_path)

    assert manifest["mode"] == "fidelity"
    assert manifest["tenant_key"] == tenant_key
    assert "alembic_revision" in manifest
    assert manifest.get("giljo_mcp_version")
    order = manifest["restore_order"]
    assert order == _fidelity_restore_order()
    pos = {name: i for i, name in enumerate(order)}
    assert pos["organizations"] < pos["products"]
    assert pos["organizations"] < pos["users"]
    for child in ("product_tech_stacks", "product_architectures", "product_test_configs", "vision_documents"):
        assert pos["products"] < pos[child], f"products must precede {child} in restore_order"
    assert pos["products"] < pos["product_memory_entries"]


async def test_portability_mode_is_unchanged_default(db_session: AsyncSession) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    await _seed_fidelity_graph(db_session, tenant_key)

    service = TenantExportService(db_session=db_session)
    zip_path, _ = await service.export(tenant_key=tenant_key)

    with zipfile.ZipFile(zip_path, "r") as zf:
        manifest = json.loads(zf.read("manifest.json"))
        user_rows = json.loads(zf.read("data/User.json"))
    assert manifest["mode"] == "portability"
    assert "restore_order" not in manifest
    for row in user_rows:
        assert "tenant_key" not in row, "portability must still strip tenant_key"


def test_restore_order_symmetry_covers_every_fk_both_directions() -> None:
    order = _fidelity_restore_order()
    tables = {m.__tablename__: m.__table__ for m in capture_models()}
    assert set(order) == set(tables), "restore_order must cover exactly the discovered capture set"

    pos = {name: i for i, name in enumerate(order)}
    purge_pos = {name: i for i, name in enumerate(reversed(order))}
    checked = 0
    for name, table in tables.items():
        for fk in table.foreign_keys:
            parent = fk.column.table.name
            if parent == name or parent not in pos:
                continue
            checked += 1
            assert pos[parent] < pos[name], f"insert direction: {parent} must precede {name}"
            assert purge_pos[name] < purge_pos[parent], f"purge direction: {name} must be deleted before {parent}"
    assert checked >= 10, f"expected to check >=10 in-set FK edges, got {checked}"

    assert pos["comm_threads"] < pos["comm_participants"]
    assert pos["comm_threads"] < pos["messages"]


async def test_portability_export_includes_hub_thread_context(db_session: AsyncSession) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    await _seed_fidelity_graph(db_session, tenant_key)

    service = TenantExportService(db_session=db_session)
    zip_path, _ = await service.export(tenant_key=tenant_key)

    with zipfile.ZipFile(zip_path, "r") as zf:
        threads = json.loads(zf.read("data/CommThread.json"))
        participants = json.loads(zf.read("data/CommParticipant.json"))
        messages = json.loads(zf.read("data/Message.json"))
    assert len(threads) == 1 and threads[0]["subject"] == "fidelity hub thread"
    assert len(participants) == 1 and participants[0]["participant_id"] == "BE-1"
    thread_ids = {t["id"] for t in threads}
    assert all(m["thread_id"] in thread_ids for m in messages if m.get("thread_id")), (
        "every exported message anchor must resolve inside the archive"
    )
    for row in threads + participants:
        assert "tenant_key" not in row, "portability must strip tenant_key from hub rows too"
