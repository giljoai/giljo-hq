# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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



NOTIFICATION_TYPE = "closeout.approval_required"

SIGNAL_RESULT = {
    "summary": "Work done, but a finding was deferred",
    "deferred_findings": ["Race in reaper retry path"],
}




async def _seed_closeout_orchestrator(db_session, tenant_key: str, project_name: str) -> dict:
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
    await SettingsService(db_session, tenant_key).update_settings("general", {"closeout_mode": "hitl"})
    seed = await _seed_closeout_orchestrator(db_session, tenant_key, project_name)

    svc = JobCompletionService(
        db_manager=db_manager,
        tenant_manager=TenantManager(),
        test_session=db_session,
    )
    with pytest.raises(ValidationError):
        await svc.complete_job(job_id=seed["job"].job_id, result=SIGNAL_RESULT, tenant_key=tenant_key)

    stmt = select(Notification).where(
        Notification.tenant_key == tenant_key,
        Notification.type == NOTIFICATION_TYPE,
    )
    rows = (await db_session.execute(stmt)).scalars().all()
    assert len(rows) == 1, f"gate must emit exactly one {NOTIFICATION_TYPE} row, got {len(rows)}"
    return rows[0]




class TestPayloadValidator:

    def _base(self) -> dict:
        return {"project_id": str(uuid4()), "approval_id": str(uuid4()), "reason_count": 2}

    def test_project_name_is_accepted(self):
        payload = {**self._base(), "project_name": "Checkout rewrite"}
        out = validate_notification_payload(NOTIFICATION_TYPE, payload)
        assert out["project_name"] == "Checkout rewrite"

    def test_payload_without_project_name_still_validates(self):
        out = validate_notification_payload(NOTIFICATION_TYPE, self._base())
        assert out["project_name"] is None

    def test_unknown_key_is_still_rejected(self):
        with pytest.raises((ValueError, TypeError)):
            validate_notification_payload(NOTIFICATION_TYPE, {**self._base(), "not_a_real_key": 1})

    def test_over_length_project_name_is_rejected(self):
        with pytest.raises((ValueError, TypeError)):
            validate_notification_payload(NOTIFICATION_TYPE, {**self._base(), "project_name": "x" * 256})




class TestEmitterNamesTheProject:
    async def test_bell_payload_carries_the_project_name(self, db_manager, db_session):
        tenant_key = TenantManager.generate_tenant_key()
        name = f"Ledger reconciliation {uuid4().hex[:6]}"
        row = await _trip_the_gate(db_manager, db_session, tenant_key, name)
        assert row.payload.get("project_name") == name

    async def test_bell_body_names_the_project(self, db_manager, db_session):
        tenant_key = TenantManager.generate_tenant_key()
        name = f"Ledger reconciliation {uuid4().hex[:6]}"
        row = await _trip_the_gate(db_manager, db_session, tenant_key, name)
        assert name in (row.body or ""), f"project name must appear in the body text, got: {row.body!r}"

    async def test_bell_title_names_the_project(self, db_manager, db_session):
        tenant_key = TenantManager.generate_tenant_key()
        name = f"Ledger reconciliation {uuid4().hex[:6]}"
        row = await _trip_the_gate(db_manager, db_session, tenant_key, name)
        assert name in row.title, f"project name must appear in the title, got: {row.title!r}"

    async def test_title_stays_within_the_column_bound(self, db_manager, db_session):
        tenant_key = TenantManager.generate_tenant_key()
        name = "L" + "o" * 250 + "ng"
        row = await _trip_the_gate(db_manager, db_session, tenant_key, name)
        assert len(row.title) <= 255, f"title overflowed its column: {len(row.title)} chars"
        assert row.title.startswith("Lo"), "the truncated title must still lead with the name"

    async def test_reasons_survive_alongside_the_name(self, db_manager, db_session):
        tenant_key = TenantManager.generate_tenant_key()
        row = await _trip_the_gate(db_manager, db_session, tenant_key, f"Project {uuid4().hex[:6]}")
        assert "deferred" in (row.body or "").lower(), f"the closeout reason must survive, got: {row.body!r}"
        assert row.payload.get("reason_count", 0) >= 1




class TestOldRowsStillRender:
    async def test_legacy_payload_survives_the_read_path(self, db_manager, db_session):
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

        response = NotificationResponse.from_orm_row(rows[0])
        assert response.payload == legacy_payload, "legacy payload must pass through untouched"
        assert "project_name" not in response.payload
        assert response.title == "Closeout requires approval"
        assert response.body == "Deferred findings present"
