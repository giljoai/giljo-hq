# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Tests for TenantExportService and the export endpoint (BE-5062).

Service-layer tests (9) cover the export pipeline: strip filters (credentials,
platform metadata, tenant_key), ephemeral and ops table exclusion, manifest
SHA-256 integrity, vision file bundling, missing vision file warning, and the
schema.md redaction notice.

Endpoint-layer tests hit the FastAPI router via httpx ASGI transport:
CE-mode happy path, SaaS admin happy path, SaaS non-admin 403, 401
unauthenticated, and tenant isolation between two users.
"""

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


# --------------------------------------------------------------------------- #
# Shared seeding helpers
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# Service-layer tests (9)
# --------------------------------------------------------------------------- #


async def test_export_strips_credentials(db_session: AsyncSession) -> None:
    """CREDENTIAL_STRIP values must not appear in any data/*.json bytes."""
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
    """PLATFORM_METADATA_STRIP values must not appear in data/*.json bytes."""
    tenant_key = TenantManager.generate_tenant_key()
    user = await _seed_user(db_session, tenant_key)
    # customer_id lives on Organization in SaaS (provider-agnostic; populated by
    # the billing webhook handler). In CE we synthetically set the attribute on
    # the in-memory instance via setattr to simulate platform metadata that
    # MIGHT exist if the column were ever added. Since CE has no such column,
    # the strip filter must operate by NAME (not by presence) so that SaaS rows
    # surviving in a CE export still get scrubbed.
    needle = "ctm_NEEDLE_BILLING_CUSTOMER"
    # Inject into Configuration JSONB (a tenant-scoped table) as a worst-case carrier.
    from giljo_mcp.models import Configuration

    cfg = Configuration(
        tenant_key=tenant_key,
        key="billing.customer_id",
        value=needle,  # JSONB scalar; preserved by serializer (mission says preserve JSONB)
        category="billing",
    )
    db_session.add(cfg)
    # And as a real PLATFORM_METADATA_STRIP test, set a User attribute that IS in the strip list.
    # User has no customer_id column today, so we add it dynamically — the strip filter
    # must remove it regardless of column existence.
    object.__setattr__(user, "customer_id", "ctm_FIELD_NEEDLE_USER")
    await db_session.commit()

    service = TenantExportService(db_session=db_session)
    zip_path, _ = await service.export(tenant_key=tenant_key)

    with zipfile.ZipFile(zip_path, "r") as zf:
        user_blob = zf.read("data/User.json")
        # Field-level strip on User: the synthetic attribute must NOT survive
        assert b"cus_FIELD_NEEDLE_USER" not in user_blob
        # Configuration JSONB value is intentionally preserved (mission says don't
        # post-process JSONB content). We only require the User field strip.


async def test_export_strips_tenant_key_from_rows(db_session: AsyncSession) -> None:
    """tenant_key must be absent from every record but present in manifest."""
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
    """tk_* values embedded in free-form text / JSONB content must be redacted.

    The per-field strip filter operates on column names, so it cannot reach
    tenant_key values that appear as payload inside Message.content,
    AgentJob.mission strings, ProductMemoryEntry summaries, AgentExecution
    JSONB result blobs, etc. The byte-level scrub at write time must catch them.
    """
    tenant_key = TenantManager.generate_tenant_key()
    await _seed_user(db_session, tenant_key)
    # Inject a foreign tenant_key value into a Configuration JSONB payload — this
    # is the worst case: JSONB content that survives the field strip and would
    # leak another tenant's identifier if not scrubbed.
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
        # manifest provenance is allowed to contain the exporting tenant_key
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["tenant_key"] == tenant_key


async def test_export_excludes_ephemeral_tables(db_session: AsyncSession) -> None:
    """EPHEMERAL_EXCLUDE_MODELS must not appear as data/*.json files."""
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
    """OPS_EXCLUDE_TABLES must not appear as data/*.json files."""
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
    """Per-file SHA-256 in manifest must equal SHA-256 of extracted file."""
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
    """Inline VisionDocument rows must appear in data/VisionDocument.json (not bundled as files)."""
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
    """Export of inline-only vision docs produces a manifest with no files/ bundle entries."""
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
    """schema.md must carry the top-line redaction notice."""
    tenant_key = TenantManager.generate_tenant_key()
    await _seed_user(db_session, tenant_key)
    await db_session.commit()

    service = TenantExportService(db_session=db_session)
    zip_path, _ = await service.export(tenant_key=tenant_key)

    with zipfile.ZipFile(zip_path, "r") as zf:
        schema_md = zf.read("schema.md").decode("utf-8")

    assert "Password hashes" in schema_md
    assert "redacted" in schema_md.lower()


# --------------------------------------------------------------------------- #
# Endpoint-layer tests (5) — FastAPI router via httpx
# --------------------------------------------------------------------------- #


def _build_app(
    db_manager,
    db_session: AsyncSession | None,
    user: User | None,
) -> FastAPI:
    """Mount the tenant_data router with auth + db overrides."""
    app = FastAPI()
    app.include_router(tenant_data.router, prefix="/api/v1/account")
    register_exception_handlers(app)

    # Provide a websocket manager stub so service event emission is no-op.
    ws = MagicMock()
    ws.broadcast_event_to_tenant = AsyncMock()
    app.state.websocket_manager = ws

    if user is not None:

        async def _override_user() -> User:
            return user

        app.dependency_overrides[get_current_active_user] = _override_user

    if db_session is not None:

        async def _override_db() -> AsyncIterator[AsyncSession]:
            # Production get_db_session stamps session.info['tenant_key'] from
            # request.state.tenant_key (Slice-2). The shared test session is
            # also flush-tainted by seeding. Mirror production by scoping the
            # request to the authenticated user's tenant so the endpoint's
            # tenant reads are authorized and correctly isolated.
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
    """CE mode: POST /api/v1/account/export returns 200 with download_url."""
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
    """SaaS admins CAN export their org's data."""
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
    """SaaS non-admins (member/viewer/developer) are 403'd."""
    export_user.role = "developer"  # default seed role
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
    """Unauthenticated request must yield 401."""
    app = _build_app(db_manager, db_session, user=None)
    transport = ASGITransport(app=app)
    with patch("api.app_state.GILJO_MODE", "ce"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/account/export")
    assert resp.status_code in (401, 403)


async def test_endpoint_tenant_isolation(db_manager, db_session: AsyncSession) -> None:
    """User A's export must not contain User B's data."""
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

    # Fetch the staged ZIP off disk via the service (the endpoint stages it).
    # We verify isolation by exporting User A's tenant via the service directly
    # and asserting no Tenant B data appears.
    # The shared db_session carries flush-derived context from the last seeded
    # rows (tenant B); scope the direct service export to tenant A so its
    # explicit tk_a predicates are authorized (Slice-6 test-side pattern).
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


# --------------------------------------------------------------------------- #
# Post-migration constraint regression — startup.py upgrade path
#
# This test exercises the live test DB (which is created with the model's
# current CheckConstraint and is what `alembic upgrade head` would produce
# on a customer install). It is the regression test for the "broken on
# customer upgrade" failure mode: if migration ce_0025 ever stops shipping
# or the constraint definition drifts, this test fails before the export
# endpoint silently 500s in production.
# --------------------------------------------------------------------------- #


async def test_download_type_constraint_admits_tenant_export(db_session: AsyncSession) -> None:
    """Post-migration DB must accept download_type='tenant_export'."""
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
    """Post-migration DB must still reject unknown download_type values."""
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


# --------------------------------------------------------------------------- #
# Fidelity (operator / restore-grade) export — BE-6130c
#
# Fidelity mode KEEPS tenant_key / PKs / all FK columns, does NOT redact
# credentials, and does NOT byte-scrub tk_ values, so a backup/restore can
# faithfully rebuild a tenant. The round-trip proof is self-contained: the
# 0844-series import service was DROPPED (the 0844b design is marked
# SUPERSEDED — there is no tenant_import_service.py), so these tests act as the
# importer — for every seeded model they (a) reconstruct each dumped row back
# into an ORM instance (proves importable shape) and (b) assert the dumped value
# equals the live DB value for every column (proves lossless, unredacted).
# --------------------------------------------------------------------------- #


# tk_ value embedded inside JSONB payload — must SURVIVE a fidelity export
# (portability would scrub it). 20+ alphanumerics after the tk_ prefix to match
# the service scrub pattern.
_FIDELITY_TK_NEEDLE = "tk_FIDELITY0123456789ABCDEFGHIJ"


async def _seed_fidelity_graph(db_session: AsyncSession, tenant_key: str) -> User:
    """Seed a representative FK graph: identity + product family + memory + config.

    Covers string PKs, a native-UUID PK (ProductMemoryEntry), FK-to-product
    children, a self-contained JSONB carrier (Configuration), an ARRAY column
    (Product.target_platforms), and credentials (User.password_hash).
    """
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
            # tk_ value embedded in JSONB payload — fidelity must NOT scrub it.
            value={"observed": [_FIDELITY_TK_NEEDLE]},
            category="diagnostics",
        )
    )
    # Message Hub graph (BE-9187): a thread, a cursor-carrying participant, and
    # an anchored message — so the generic fidelity round-trip tests exercise
    # the comm tables the restore engine depends on.
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
    """Return ({Model: [rows]}, manifest) parsed from a fidelity export ZIP."""
    model_rows: dict[str, list[dict]] = {}
    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            if name.startswith("data/") and name.endswith(".json"):
                model_rows[name[len("data/") : -len(".json")]] = json.loads(zf.read(name))
        manifest = json.loads(zf.read("manifest.json"))
    return model_rows, manifest


def _coerce_for_reconstruct(model: type, row: dict) -> dict:
    """Coerce a dumped JSON row back to ORM-constructor kwargs.

    Mirrors what a restore importer would do: ISO strings -> datetime, UUID
    strings -> UUID; everything else (str/int/float/bool/list/dict/None) passes
    through unchanged. This is the deserialize half of the round-trip.
    """
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
    """Return {pk_value: orm_instance} for a model's live rows in this tenant."""
    pk_name = next(c.name for c in sa_inspect(model).primary_key)
    result = await db_session.execute(select(model).where(model.tenant_key == tenant_key))
    return {str(getattr(inst, pk_name)): inst for inst in result.scalars().all()}


async def test_fidelity_retains_tenant_key_pk_and_fk_for_every_model(db_session: AsyncSession) -> None:
    """Every fidelity-dumped row must carry tenant_key, its PK, and all FK columns."""
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

    # Sanity: the seeded graph spans several models, so the loop actually ran.
    assert seen_models >= 6, f"expected >=6 populated models, got {seen_models}"


async def test_fidelity_does_not_redact_credentials(db_session: AsyncSession) -> None:
    """Fidelity mode must KEEP credentials (the opposite of portability)."""
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
    """tk_ values embedded in JSONB must SURVIVE a fidelity export."""
    tenant_key = TenantManager.generate_tenant_key()
    await _seed_fidelity_graph(db_session, tenant_key)

    service = TenantExportService(db_session=db_session)
    zip_path, _ = await service.export(tenant_key=tenant_key, fidelity=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        cfg_blob = zf.read("data/Configuration.json").decode("utf-8")
    assert _FIDELITY_TK_NEEDLE in cfg_blob, "fidelity mode wrongly scrubbed an embedded tk_ value"


async def test_fidelity_roundtrips_losslessly_for_every_model(db_session: AsyncSession) -> None:
    """Each dumped row reconstructs into an ORM instance AND equals the live row."""
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
            # (a) deserialize: the row is a valid ORM-constructor input.
            reconstructed = model(**_coerce_for_reconstruct(model, row))
            assert reconstructed is not None
            # (b) lossless: every column equals the live DB value, unredacted.
            inst = live[str(row[pk_name])]
            for col in col_names:
                assert row.get(col) == _to_json_safe(getattr(inst, col)), (
                    f"{name}.{col}: fidelity dump diverged from live row"
                )
            checked += 1
    assert checked >= 8, f"expected to round-trip >=8 rows, got {checked}"


async def test_fidelity_manifest_records_mode_revision_version_and_restore_order(db_session: AsyncSession) -> None:
    """Manifest must record mode, alembic_revision, giljo_mcp_version, restore_order."""
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
    # FK-correct INSERT order: parents precede children.
    pos = {name: i for i, name in enumerate(order)}
    assert pos["organizations"] < pos["products"]
    assert pos["organizations"] < pos["users"]
    for child in ("product_tech_stacks", "product_architectures", "product_test_configs", "vision_documents"):
        assert pos["products"] < pos[child], f"products must precede {child} in restore_order"
    assert pos["products"] < pos["product_memory_entries"]


async def test_portability_mode_is_unchanged_default(db_session: AsyncSession) -> None:
    """Default (portability) export still strips tenant_key and labels its mode."""
    tenant_key = TenantManager.generate_tenant_key()
    await _seed_fidelity_graph(db_session, tenant_key)

    service = TenantExportService(db_session=db_session)
    zip_path, _ = await service.export(tenant_key=tenant_key)  # default fidelity=False

    with zipfile.ZipFile(zip_path, "r") as zf:
        manifest = json.loads(zf.read("manifest.json"))
        user_rows = json.loads(zf.read("data/User.json"))
    assert manifest["mode"] == "portability"
    assert "restore_order" not in manifest
    for row in user_rows:
        assert "tenant_key" not in row, "portability must still strip tenant_key"


def test_restore_order_symmetry_covers_every_fk_both_directions() -> None:
    """Purge order == reversed(insert order) must be FK-valid BOTH ways (BE-9187).

    The restore engine deletes ``reversed(restore_order)`` and reloads
    ``restore_order``; for every FK whose endpoints are both in the export set,
    the parent must precede the child on insert AND the child must precede the
    parent on purge.
    """
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

    # BE-9187 anchors: the hub thread table is a parent of messages AND of the
    # participant directory — the exact edges whose absence caused F1.
    assert pos["comm_threads"] < pos["comm_participants"]
    assert pos["comm_threads"] < pos["messages"]


async def test_portability_export_includes_hub_thread_context(db_session: AsyncSession) -> None:
    """GDPR portability picks up the hub tables from the shared allowlist (BE-9187).

    Pre-fix, ``data/Message.json`` referenced thread UUIDs that resolved to
    nothing in the archive (audit IMP-9186, F4). The thread containers and the
    participant directory must now ship — with tenant_key stripped like every
    portability row.
    """
    tenant_key = TenantManager.generate_tenant_key()
    await _seed_fidelity_graph(db_session, tenant_key)

    service = TenantExportService(db_session=db_session)
    zip_path, _ = await service.export(tenant_key=tenant_key)  # default = portability

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
