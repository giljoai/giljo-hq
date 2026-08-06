# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9085 / BE-9085b -- closeout-hook detector for a pre-launch work-product skip.

Regression tests at the closeout tool boundary (write_360_memory), the layer
the detector lives at. A project_completion closeout that carries git commits
while ``ever_launched_at`` is still NULL means the human Implement gate was
never crossed in this project's life; the detector raises an operator-visible
NotificationService banner (never blocks the closeout -- alarm, not a lock).

BE-9085b replaced the shipped accept-and-note restage false-positive with a
durable ``ever_launched_at`` set-once signal (survives restage, cleared only
by reset_to_prestage) -- see test_restage_survivor_suppresses_alarm below.
"""

from __future__ import annotations

import random
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from giljo_mcp.models import Project
from giljo_mcp.models.notifications import Notification
from giljo_mcp.tools.write_memory_entry import write_360_memory


@pytest.fixture(autouse=True)
def _stub_staleness():
    """Tuning staleness check needs a real db_manager; not under test here."""

    async def _noop(*args, **kwargs):
        return {"is_stale": False, "projects_since_tune": 0, "threshold": 3, "enabled": True}

    with patch(
        "giljo_mcp.services.product_tuning_service.ProductTuningService.check_tuning_staleness",
        new=_noop,
    ):
        yield


def _mock_db_manager_over(db_session):
    """A db_manager whose get_session_async() yields the shared test session.

    NotificationService.upsert_by_dedupe_key opens its own session via
    db_manager.get_session_async() (per the BE-9085 WO: never handed the
    active closeout session). Wiring it to the transactional test session
    lets assertions see the row without a second real connection.
    """
    mock_db_manager = MagicMock()

    @asynccontextmanager
    async def _yield_db_session():
        yield db_session

    mock_db_manager.get_session_async = MagicMock(side_effect=_yield_db_session)
    return mock_db_manager


async def _make_project(
    db_session,
    test_tenant_key,
    test_product,
    *,
    implementation_launched: bool,
    ever_launched: bool | None = None,
):
    """``ever_launched`` defaults to matching ``implementation_launched`` (the
    normal case). Pass it explicitly to build the restage scenario: launched
    once (ever_launched=True) but currently un-launched
    (implementation_launched=False) after a restage cleared the live field."""
    if ever_launched is None:
        ever_launched = implementation_launched

    project = Project(
        id=str(uuid.uuid4()),
        name="BE-9085 detector project",
        description="pre-launch workproduct detection",
        mission="test",
        status="active",
        tenant_key=test_tenant_key,
        product_id=test_product.id,
        series_number=random.randint(1, 9000),
        implementation_launched_at=datetime.now(UTC) if implementation_launched else None,
        ever_launched_at=datetime.now(UTC) if ever_launched else None,
    )
    db_session.add(project)
    await db_session.commit()
    return project


async def _open_notification(db_session, tenant_key, project_id):
    stmt = select(Notification).where(
        Notification.tenant_key == tenant_key,
        Notification.dedupe_key == f"project.pre_launch_workproduct:{project_id}",
        Notification.resolved_at.is_(None),
    )
    result = await db_session.execute(stmt)
    return result.scalars().first()


@pytest.mark.asyncio
async def test_never_launched_closeout_with_commits_fires_notification(db_session, test_tenant_key, test_product):
    project = await _make_project(db_session, test_tenant_key, test_product, implementation_launched=False)
    db_manager = _mock_db_manager_over(db_session)

    result = await write_360_memory(
        project_id=str(project.id),
        tenant_key=test_tenant_key,
        summary="Closeout with commits, never launched",
        key_outcomes=["shipped anyway"],
        decisions_made=["decision"],
        entry_type="project_completion",
        git_commits=[{"sha": "a" * 40, "message": "fix", "author": "agent"}],
        db_manager=db_manager,
        session=db_session,
    )
    assert result.get("entry_id")

    notification = await _open_notification(db_session, test_tenant_key, str(project.id))
    assert notification is not None
    assert notification.type == "project.pre_launch_workproduct"
    assert notification.severity == "warning"
    assert notification.payload["commit_count"] == 1
    assert notification.payload["project_id"] == str(project.id)
    # BE-9085b: no more "may be a false alarm" hedge in the body -- the
    # durable signal means we're certain when this fires now.
    assert "false alarm" not in notification.body.lower()


@pytest.mark.asyncio
async def test_notification_is_emitted_to_the_bell_surface(db_session, test_tenant_key, test_product):
    """FE-9229: the row must be addressed to the surface that actually renders it.

    Regression for the surface mismatch: this notification was emitted with
    surface="banner", but SystemStatusBanner renders only its ALLOWED_TYPES
    allowlist of singleton ``system.*`` state and silently discards any
    ``project.*`` row -- so the notification rendered on no surface it was
    addressed to, surviving only because the bell happens to ignore ``surface``.
    Pinning "bell" here makes the bell's persistence a contract rather than an
    accident. Do NOT "fix" this back to "banner"/"both" without also admitting
    the type to SystemStatusBanner's allowlist -- and note that this fires once
    per project, so a headless chain of N closeouts would stack N sticky banners.
    """
    project = await _make_project(db_session, test_tenant_key, test_product, implementation_launched=False)
    db_manager = _mock_db_manager_over(db_session)

    await write_360_memory(
        project_id=str(project.id),
        tenant_key=test_tenant_key,
        summary="Closeout with commits, never launched",
        key_outcomes=["shipped anyway"],
        decisions_made=["decision"],
        entry_type="project_completion",
        git_commits=[{"sha": "b" * 40, "message": "fix", "author": "agent"}],
        db_manager=db_manager,
        session=db_session,
    )

    notification = await _open_notification(db_session, test_tenant_key, str(project.id))
    assert notification is not None
    assert notification.surface == "bell"


@pytest.mark.asyncio
async def test_enriched_notification_carries_taxonomy_alias_and_name(db_session, test_tenant_key, test_product):
    """FE-9222: the pre-launch banner names the project by taxonomy_alias + name in
    the title, body, and payload (enrichment; zero new queries), and the body reads
    informationally rather than error-toned."""
    project = await _make_project(db_session, test_tenant_key, test_product, implementation_launched=False)
    db_manager = _mock_db_manager_over(db_session)

    result = await write_360_memory(
        project_id=str(project.id),
        tenant_key=test_tenant_key,
        summary="Closeout with commits, never launched",
        key_outcomes=["shipped anyway"],
        decisions_made=["decision"],
        entry_type="project_completion",
        git_commits=[{"sha": "e" * 40, "message": "fix", "author": "agent"}],
        db_manager=db_manager,
        session=db_session,
    )
    assert result.get("entry_id")

    notification = await _open_notification(db_session, test_tenant_key, str(project.id))
    assert notification is not None
    # Payload carries the tag + name (+ the still-required commit_count/project_id).
    # A non-empty taxonomy_alias proves the enricher read the SELECT-time
    # column_property off the ORM instance (a missing/None value would fail here).
    alias = notification.payload["taxonomy_alias"]
    assert alias, "enriched notification should carry a non-empty taxonomy_alias"
    assert notification.payload["project_name"] == "BE-9085 detector project"
    assert notification.payload["commit_count"] == 1
    # Tag + name lead the human-facing copy.
    assert alias in notification.title
    assert alias in notification.body
    assert "BE-9085 detector project" in notification.body
    # Informational, not error-toned: the headless/CLI framing is present and the
    # old "ever_launched_at is unset" internals are gone.
    assert "headless" in notification.body.lower()
    assert "ever_launched_at" not in notification.body


@pytest.mark.asyncio
async def test_launched_project_with_commits_no_notification(db_session, test_tenant_key, test_product):
    project = await _make_project(db_session, test_tenant_key, test_product, implementation_launched=True)
    db_manager = _mock_db_manager_over(db_session)

    result = await write_360_memory(
        project_id=str(project.id),
        tenant_key=test_tenant_key,
        summary="Closeout with commits, properly launched",
        key_outcomes=["shipped"],
        decisions_made=["decision"],
        entry_type="project_completion",
        git_commits=[{"sha": "b" * 40, "message": "fix", "author": "agent"}],
        db_manager=db_manager,
        session=db_session,
    )
    assert result.get("entry_id")

    notification = await _open_notification(db_session, test_tenant_key, str(project.id))
    assert notification is None


@pytest.mark.asyncio
async def test_prelaunch_closeout_with_no_commits_no_notification(db_session, test_tenant_key, test_product):
    project = await _make_project(db_session, test_tenant_key, test_product, implementation_launched=False)
    db_manager = _mock_db_manager_over(db_session)

    result = await write_360_memory(
        project_id=str(project.id),
        tenant_key=test_tenant_key,
        summary="Closeout with no commits, never launched",
        key_outcomes=["nothing shipped"],
        decisions_made=["decision"],
        entry_type="project_completion",
        git_commits=[],
        db_manager=db_manager,
        session=db_session,
    )
    assert result.get("entry_id")

    notification = await _open_notification(db_session, test_tenant_key, str(project.id))
    assert notification is None


@pytest.mark.asyncio
async def test_fail_open_closeout_still_succeeds_when_emit_raises(db_session, test_tenant_key, test_product):
    """FAIL-OPEN (mandatory): if the notification emit raises, the closeout
    still returns normally and the 360 memory entry still exists."""
    project = await _make_project(db_session, test_tenant_key, test_product, implementation_launched=False)
    db_manager = _mock_db_manager_over(db_session)

    with patch(
        "giljo_mcp.services.notification_service.NotificationService.upsert_by_dedupe_key",
        new=AsyncMock(side_effect=RuntimeError("simulated notification backend failure")),
    ):
        result = await write_360_memory(
            project_id=str(project.id),
            tenant_key=test_tenant_key,
            summary="Closeout where the notification emit blows up",
            key_outcomes=["shipped anyway"],
            decisions_made=["decision"],
            entry_type="project_completion",
            git_commits=[{"sha": "c" * 40, "message": "fix", "author": "agent"}],
            db_manager=db_manager,
            session=db_session,
        )

    assert result.get("entry_id"), "closeout must still succeed when the detector's emit raises"
    assert result.get("error") is None


@pytest.mark.asyncio
async def test_restage_survivor_suppresses_alarm(db_session, test_tenant_key, test_product):
    """BE-9085b -- THE false-positive this change fixes.

    A project that was launched, produced legitimate commits, then was
    restaged (which clears ``implementation_launched_at`` back to NULL but
    leaves ``ever_launched_at`` untouched) and later closed out without
    re-launching must NOT fire the alarm -- it was launched at some point in
    its life, restage doesn't erase that fact.
    """
    project = await _make_project(
        db_session,
        test_tenant_key,
        test_product,
        implementation_launched=False,
        ever_launched=True,
    )
    db_manager = _mock_db_manager_over(db_session)

    result = await write_360_memory(
        project_id=str(project.id),
        tenant_key=test_tenant_key,
        summary="Closeout after a restage that cleared implementation_launched_at",
        key_outcomes=["restaged then closed without relaunching"],
        decisions_made=["decision"],
        entry_type="project_completion",
        git_commits=[{"sha": "d" * 40, "message": "pre-restage work", "author": "agent"}],
        db_manager=db_manager,
        session=db_session,
    )
    assert result.get("entry_id")

    notification = await _open_notification(db_session, test_tenant_key, str(project.id))
    assert notification is None, "ever_launched_at must suppress the restage false-positive"
