# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9436b — the closeout-approval bell row must NAME its project.

Edition Scope: Both (CE core: approvals + job completion + notifications).

WHAT THIS GUARDS:
    ``closeout.approval_required`` is emitted by the BE-9153 gate
    (``job_completion_closeout_gate._emit_approval_bell``) and was the one
    "Action needed" row that named no project — its title is a constant and its
    body was the raw reason list, so an operator with two projects in flight
    could not tell which closeout was waiting on them. FE-9436 (#826) unified the
    surface; naming the row needs the backend, which is this.

    That the defect shipped at all is explained by the coverage: before this
    file, ``_emit_approval_bell`` had NO test of any kind — the gate's three
    BE-9153 test files assert on approvals and execution status and never look
    at the notification. So this file tests the EMITTER, which is the layer the
    bug lived at, not just the schema.

THREE LAYERS, deliberately:
    1. ``TestPayloadValidator`` — the write-boundary schema. Includes the
       mutation that matters: adding a field must not loosen ``extra="forbid"``.
    2. ``TestEmitterNamesTheProject`` — real gate, real DB, real notification row.
    3. ``TestOldRowsStillRender`` — a row written BEFORE this change must keep
       rendering. Simulated honestly by inserting the legacy payload as an ORM
       row (which is what an existing row is: it never re-enters the write-
       boundary validator) and reading it back out through the live read path.

Parallel-safe: ``db_session`` is rolled back at teardown, every test seeds its
own rows under a freshly generated tenant_key, and there is no module-level
mutable state.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from api.endpoints.notifications import NotificationResponse
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.notifications import Notification
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.schemas.jsonb_validators import validate_notification_payload
from giljo_mcp.services.job_completion_service import JobCompletionService
from giljo_mcp.services.notification_service import NotificationService
from giljo_mcp.services.settings_service import SettingsService
from giljo_mcp.tenant import TenantManager


# No module-level ``pytest.mark.asyncio``: this file mixes sync schema tests with
# async DB tests, and pyproject already sets ``--asyncio-mode=auto``, so the async
# ones are collected without a mark while the sync ones stay warning-free.

NOTIFICATION_TYPE = "closeout.approval_required"

# A closeout `result` carrying signal — the same shape BE-9153's own museum file
# uses, because it is what actually trips the gate into creating an approval.
SIGNAL_RESULT = {
    "summary": "Work done, but a finding was deferred",
    "deferred_findings": ["Race in reaper retry path"],
}


# ---------------------------------------------------------------------------
# Seeding (mirrors tests/services/test_be9153_closeout_mode_gate.py)
# ---------------------------------------------------------------------------


async def _seed_closeout_orchestrator(db_session, tenant_key: str, project_name: str) -> dict:
    """Seed a solo orchestrator sitting in the closeout phase, ready to trip the gate.

    ``implementation_launched_at`` + ``staging_status='staging_complete'`` are
    what make ``complete_job`` classify this as the closeout phase, which is the
    only phase the gate runs in.
    """
    suffix = uuid4().hex[:8]
    product = Product(
        id=str(uuid4()),
        name=f"Product {suffix}",
        description="be9436b",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(product)
    await db_session.flush()

    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name=project_name,
        description="x",
        mission="x",
        status="active",
        staging_status="staging_complete",
        implementation_launched_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()

    job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="orchestrator",
        mission="x",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(job)
    await db_session.flush()

    execution = AgentExecution(
        id=str(uuid4()),
        agent_id=str(uuid4()),
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name="orchestrator",
        agent_name="orchestrator",
        status="working",
        started_at=datetime.now(UTC),
    )
    db_session.add(execution)
    await db_session.commit()
    return {"product": product, "project": project, "job": job, "execution": execution}


async def _trip_the_gate(db_manager, db_session, tenant_key: str, project_name: str) -> Notification:
    """Run a signal-bearing closeout under hitl and return the emitted bell row."""
    await SettingsService(db_session, tenant_key).update_settings("general", {"closeout_mode": "hitl"})
    seed = await _seed_closeout_orchestrator(db_session, tenant_key, project_name)

    svc = JobCompletionService(
        db_manager=db_manager,
        tenant_manager=TenantManager(),
        test_session=db_session,
    )
    # The solo path parks the orchestrator and raises; the bell is emitted first.
    with pytest.raises(ValidationError):
        await svc.complete_job(job_id=seed["job"].job_id, result=SIGNAL_RESULT, tenant_key=tenant_key)

    stmt = select(Notification).where(
        Notification.tenant_key == tenant_key,
        Notification.type == NOTIFICATION_TYPE,
    )
    rows = (await db_session.execute(stmt)).scalars().all()
    assert len(rows) == 1, f"gate must emit exactly one {NOTIFICATION_TYPE} row, got {len(rows)}"
    return rows[0]


# ---------------------------------------------------------------------------
# LAYER 1 — the write-boundary schema.
# ---------------------------------------------------------------------------


class TestPayloadValidator:
    """``CloseoutApprovalRequiredPayload`` gains ``project_name`` without loosening."""

    def _base(self) -> dict:
        return {"project_id": str(uuid4()), "approval_id": str(uuid4()), "reason_count": 2}

    def test_project_name_is_accepted(self):
        """RED before the change: extra="forbid" rejects the unknown key."""
        payload = {**self._base(), "project_name": "Checkout rewrite"}
        out = validate_notification_payload(NOTIFICATION_TYPE, payload)
        assert out["project_name"] == "Checkout rewrite"

    def test_payload_without_project_name_still_validates(self):
        """The old shape stays writable — the field is optional, not required.

        This is the emitter's fail-open guarantee expressed at the schema: a
        project whose name cannot be resolved must still produce a bell row.
        """
        out = validate_notification_payload(NOTIFICATION_TYPE, self._base())
        assert out["project_name"] is None

    def test_unknown_key_is_still_rejected(self):
        """MUTATION GUARD: adding a field must not become extra="allow".

        Without this, swapping the model_config to ``extra="allow"`` would make
        the two tests above pass while silently dropping the schema's teeth.
        """
        with pytest.raises((ValueError, TypeError)):
            validate_notification_payload(NOTIFICATION_TYPE, {**self._base(), "not_a_real_key": 1})

    def test_over_length_project_name_is_rejected(self):
        """Bounded like every other name field in the registry (max_length=255)."""
        with pytest.raises((ValueError, TypeError)):
            validate_notification_payload(NOTIFICATION_TYPE, {**self._base(), "project_name": "x" * 256})


# ---------------------------------------------------------------------------
# LAYER 2 — the emitter. This is the layer the defect lived at.
# ---------------------------------------------------------------------------


class TestEmitterNamesTheProject:
    async def test_bell_payload_carries_the_project_name(self, db_manager, db_session):
        tenant_key = TenantManager.generate_tenant_key()
        name = f"Ledger reconciliation {uuid4().hex[:6]}"
        row = await _trip_the_gate(db_manager, db_session, tenant_key, name)
        assert row.payload.get("project_name") == name

    async def test_bell_body_names_the_project(self, db_manager, db_session):
        """The payload field alone is not the fix.

        ``NotificationDropdown`` renders ``notification.body`` generically for
        every type and has no per-type branch, so the BODY is the only text an
        operator actually reads. A payload key nothing renders would leave the
        row exactly as anonymous as before.
        """
        tenant_key = TenantManager.generate_tenant_key()
        name = f"Ledger reconciliation {uuid4().hex[:6]}"
        row = await _trip_the_gate(db_manager, db_session, tenant_key, name)
        assert name in (row.body or ""), f"project name must appear in the body text, got: {row.body!r}"

    async def test_bell_title_names_the_project(self, db_manager, db_session):
        """EM ruling: the name leads the TITLE too, not only the body.

        The title is the prominent line in ``NotificationDropdown`` (the body
        renders below it, truncated behind an expand chevron), and the prelaunch
        exemplar names its project in both. The operator's affiliated-name rule
        is about what is actually exposed, so it has to reach the prominent line.
        """
        tenant_key = TenantManager.generate_tenant_key()
        name = f"Ledger reconciliation {uuid4().hex[:6]}"
        row = await _trip_the_gate(db_manager, db_session, tenant_key, name)
        assert name in row.title, f"project name must appear in the title, got: {row.title!r}"

    async def test_title_stays_within_the_column_bound(self, db_manager, db_session):
        """``Notification.title`` is String(255) and ``project_name`` alone may be 255.

        Composing "<name>: closeout requires approval" can therefore overflow the
        column, which is a write failure the fail-open handler would swallow —
        the operator would lose the bell entirely and nothing would say why.
        """
        tenant_key = TenantManager.generate_tenant_key()
        name = "L" + "o" * 250 + "ng"  # 253 chars, under the project-name cap
        row = await _trip_the_gate(db_manager, db_session, tenant_key, name)
        assert len(row.title) <= 255, f"title overflowed its column: {len(row.title)} chars"
        assert row.title.startswith("Lo"), "the truncated title must still lead with the name"

    async def test_reasons_survive_alongside_the_name(self, db_manager, db_session):
        """Naming the project must not cost the operator the WHY.

        The pre-change body was the reason list; the fix adds to it rather than
        replacing it.
        """
        tenant_key = TenantManager.generate_tenant_key()
        row = await _trip_the_gate(db_manager, db_session, tenant_key, f"Project {uuid4().hex[:6]}")
        assert "deferred" in (row.body or "").lower(), f"the closeout reason must survive, got: {row.body!r}"
        assert row.payload.get("reason_count", 0) >= 1


# ---------------------------------------------------------------------------
# LAYER 3 — data-facing DoD: rows written before this change keep rendering.
# ---------------------------------------------------------------------------


class TestOldRowsStillRender:
    async def test_legacy_payload_survives_the_read_path(self, db_manager, db_session):
        """An already-written row has NO ``project_name`` and must render as today.

        Inserted as a raw ORM row on purpose: that is what a pre-existing row
        genuinely is. It was validated once, at write time, by the OLD schema and
        never passes through ``validate_notification_payload`` again — the two
        production call sites (``NotificationService.create`` and
        ``upsert_by_dedupe_key``) are both writers, and the read path types
        ``payload`` as a bare dict.
        """
        tenant_key = TenantManager.generate_tenant_key()
        legacy_payload = {
            "project_id": str(uuid4()),
            "approval_id": str(uuid4()),
            "reason_count": 3,
        }
        db_session.add(
            Notification(
                id=str(uuid4()),
                tenant_key=tenant_key,
                user_id=None,
                type=NOTIFICATION_TYPE,
                severity="warning",
                title="Closeout requires approval",
                body="Deferred findings present",
                payload=legacy_payload,
                dedupe_key=f"{NOTIFICATION_TYPE}:{uuid4()}",
                surface="both",
                dismissible=True,
            )
        )
        await db_session.commit()

        service = NotificationService(db_manager=db_manager, session=db_session)
        rows = await service.list_for_user(tenant_key=tenant_key, user_id=str(uuid4()))
        assert len(rows) == 1, "the tenant-scoped legacy row must still be listed"

        # The API serializer is the last thing between the row and the bell.
        response = NotificationResponse.from_orm_row(rows[0])
        assert response.payload == legacy_payload, "legacy payload must pass through untouched"
        assert "project_name" not in response.payload
        assert response.title == "Closeout requires approval"
        assert response.body == "Deferred findings present"
