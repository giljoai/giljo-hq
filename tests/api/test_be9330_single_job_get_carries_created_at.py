# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9330 -- ``GET /api/agent-jobs/{job_id}`` must return the job's REAL
``created_at``, not 500 and not a substitute timestamp.

The route built its ``JobResponse`` out of a ``MissionResponse`` (the agent
mission-delivery payload) via a hand-written dict bridge. ``MissionResponse``
is a protocol payload, not a job record: on the implementation-launch gate's
BLOCKED branch (``mission_implementation_gate.py``) it is constructed with
``job_id`` + the block wording ONLY -- ``created_at``, ``status``,
``agent_display_name`` and ``started_at`` are all left at their optional
defaults. ``JobResponse.created_at`` is REQUIRED, so a staging orchestrator
(project not yet launched -> gated) fed ``None`` into a required datetime and
pydantic raised -> 500.

The bridge also hardcoded ``completed_at=None``, so even on the non-gated path
a genuinely completed job reported no completion time at all.

HTTP-boundary test on purpose: the defect lives BETWEEN two schemas, so a unit
test on either side alone passes while the endpoint 500s (house rule -- test at
the failing layer; BE-5042). Full app via ``api_client``, real JWT via
``auth_headers``, real PostgreSQL. Every assertion compares the response value
against the value read back from the DB row -- "not None" would also pass
against an ``or datetime.now()`` anti-fix, which would make the API lie.

Edition Scope: Both.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from giljo_mcp.models import AgentExecution, AgentJob, Project
from giljo_mcp.models.products import Product


def _extract_tenant_key(auth_headers: dict) -> str:
    """Decode the tenant_key baked into the JWT access_token cookie."""
    cookie = auth_headers["Cookie"]
    access_segment = next(p for p in cookie.split(";") if p.strip().startswith("access_token="))
    token = access_segment.split("=", 1)[1]
    payload_b64 = token.split(".")[1]
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))["tenant_key"]


# Sentinel: "caller did not choose a mission" -- distinct from an explicit
# ``mission=None``, which is the NULL-mission row under test.
_DERIVE_MISSION = "<derive from display_name>"


async def _seed_project(db_manager, tenant_key: str, *, launched: bool) -> str:
    """One project. ``launched=False`` leaves ``implementation_launched_at``
    NULL -- the state that gates an orchestrator's mission and produced the 500.
    """
    project_id = str(uuid4())
    product_id = str(uuid4())
    async with db_manager.get_session_async() as session:
        # BE-9437: a project belongs to a product.
        session.add(
            Product(
                id=product_id,
                tenant_key=tenant_key,
                name=f"BE-9330 product {uuid4().hex[:8]}",
                description="seeded",
                is_active=False,
            )
        )
        session.add(
            Project(
                id=project_id,
                product_id=product_id,
                name=f"BE-9330 project {uuid4().hex[:8]}",
                description="single-job GET created_at bridge",
                mission="single-job GET created_at bridge mission",
                status="active",
                tenant_key=tenant_key,
                execution_mode="multi_terminal",
                staging_status="staging_complete" if not launched else "staged",
                implementation_launched_at=datetime.now(UTC) if launched else None,
            )
        )
        await session.commit()
    return project_id


async def _seed_job(
    db_manager,
    tenant_key: str,
    project_id: str,
    *,
    job_type: str,
    display_name: str,
    status: str,
    spawned_by: str | None = None,
    completed_at: datetime | None = None,
    mission: str | None = _DERIVE_MISSION,
) -> tuple[str, datetime, datetime | None]:
    """Seed one job + execution. Returns (job_id, job.created_at, execution.completed_at)
    read back FROM THE DB -- ``created_at`` is a server_default, so the truth
    only exists after the row is written.

    ``mission=None`` seeds the real NULL-mission row (a chain conductor, or a
    specialist staged but not yet given its Phase-2 mission). It is a distinct
    case from the default, which derives a mission from ``display_name``.
    """
    job_id = str(uuid4())
    async with db_manager.get_session_async() as session:
        job = AgentJob(
            job_id=job_id,
            tenant_key=tenant_key,
            project_id=project_id,
            job_type=job_type,
            mission=(f"mission for {display_name}" if mission is _DERIVE_MISSION else mission),
            status="completed" if completed_at else "active",
        )
        session.add(job)
        execution = AgentExecution(
            job_id=job_id,
            tenant_key=tenant_key,
            agent_display_name=display_name,
            status=status,
            spawned_by=spawned_by,
            started_at=datetime.now(UTC) - timedelta(minutes=5),
            completed_at=completed_at,
            messages_sent_count=0,
            messages_waiting_count=0,
            messages_read_count=0,
        )
        session.add(execution)
        await session.commit()
        await session.refresh(job)
        await session.refresh(execution)
        return job.job_id, job.created_at, execution.completed_at


def _assert_same_instant(actual: str | None, expected: datetime, label: str) -> None:
    """The response value must be the SAME INSTANT as the DB row's value.

    Not "is present", not "is recent" -- the exact stored instant, so a
    ``or datetime.now()`` style guard (which turns the 500 into a wrong
    timestamp) fails this test rather than passing it.
    """
    assert actual is not None, f"{label} was dropped from the response entirely"
    parsed = datetime.fromisoformat(actual)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    delta = abs((parsed - expected).total_seconds())
    assert delta < 0.001, f"{label} is not the row's value: response={parsed.isoformat()} db={expected.isoformat()}"


@pytest.mark.asyncio
async def test_get_single_job_returns_real_created_at_for_staging_orchestrator(api_client, auth_headers, db_manager):
    """THE REPRODUCTION: an orchestrator on a project that has not launched
    implementation. Its mission is gated, so the mission payload carries no
    created_at -- and the job-details route 500s on a job whose row has the
    value sitting right there.
    """
    tenant_key = _extract_tenant_key(auth_headers)
    project_id = await _seed_project(db_manager, tenant_key, launched=False)
    job_id, db_created_at, _ = await _seed_job(
        db_manager,
        tenant_key,
        project_id,
        job_type="orchestrator",
        display_name="orchestrator",
        status="waiting",
    )

    resp = await api_client.get(f"/api/agent-jobs/{job_id}", headers=auth_headers)

    assert resp.status_code == 200, f"single-job GET failed for a staging orchestrator: {resp.text}"
    body = resp.json()
    assert body["job_id"] == job_id
    _assert_same_instant(body["created_at"], db_created_at, "created_at")


@pytest.mark.asyncio
async def test_get_single_job_returns_real_created_at_for_spawned_worker(api_client, auth_headers, db_manager):
    """A spawned worker on a launched project -- the path that already
    returned 200. It must keep returning the row's own created_at (a fix that
    repairs the gated path by breaking this one is not a fix).
    """
    tenant_key = _extract_tenant_key(auth_headers)
    project_id = await _seed_project(db_manager, tenant_key, launched=True)
    parent_agent_id = str(uuid4())
    job_id, db_created_at, _ = await _seed_job(
        db_manager,
        tenant_key,
        project_id,
        job_type="implementer",
        display_name="implementer",
        status="working",
        spawned_by=parent_agent_id,
    )

    resp = await api_client.get(f"/api/agent-jobs/{job_id}", headers=auth_headers)

    assert resp.status_code == 200, f"single-job GET failed for a spawned worker: {resp.text}"
    body = resp.json()
    _assert_same_instant(body["created_at"], db_created_at, "created_at")
    assert body["spawned_by"] == parent_agent_id
    assert body["status"] == "working"


@pytest.mark.asyncio
async def test_get_single_job_returns_real_created_at_and_completed_at_for_completed_job(
    api_client, auth_headers, db_manager
):
    """A finished job. ``completed_at`` was hardcoded to ``None`` in the same
    dict bridge, so the API reported a completed agent as never having
    completed -- the identical silent drop as created_at, one field over.
    """
    tenant_key = _extract_tenant_key(auth_headers)
    project_id = await _seed_project(db_manager, tenant_key, launched=True)
    finished_at = datetime.now(UTC) - timedelta(minutes=1)
    job_id, db_created_at, db_completed_at = await _seed_job(
        db_manager,
        tenant_key,
        project_id,
        job_type="implementer",
        display_name="implementer",
        status="complete",
        completed_at=finished_at,
    )

    resp = await api_client.get(f"/api/agent-jobs/{job_id}", headers=auth_headers)

    assert resp.status_code == 200, f"single-job GET failed for a completed job: {resp.text}"
    body = resp.json()
    _assert_same_instant(body["created_at"], db_created_at, "created_at")
    assert db_completed_at is not None
    _assert_same_instant(body["completed_at"], db_completed_at, "completed_at")


@pytest.mark.asyncio
async def test_get_single_job_agrees_with_the_list_endpoint(api_client, auth_headers, db_manager):
    """The two endpoints read the same row and must not disagree. The list
    endpoint served this job correctly the whole time the detail endpoint
    500'd -- that divergence IS the defect, so pin the agreement.
    """
    tenant_key = _extract_tenant_key(auth_headers)
    project_id = await _seed_project(db_manager, tenant_key, launched=False)
    job_id, _db_created_at, _ = await _seed_job(
        db_manager,
        tenant_key,
        project_id,
        job_type="orchestrator",
        display_name="orchestrator",
        status="waiting",
    )

    detail = await api_client.get(f"/api/agent-jobs/{job_id}", headers=auth_headers)
    listing = await api_client.get("/api/agent-jobs/", headers=auth_headers, params={"project_id": project_id})

    assert detail.status_code == 200, detail.text
    assert listing.status_code == 200, listing.text
    from_list = next(job for job in listing.json()["jobs"] if job["job_id"] == job_id)
    detail_body = detail.json()

    for field in ("job_id", "agent_id", "created_at", "status", "agent_display_name", "project_id", "mission"):
        assert detail_body[field] == from_list[field], (
            f"detail and list disagree on {field}: detail={detail_body[field]!r} list={from_list[field]!r}"
        )


@pytest.mark.asyncio
async def test_get_single_job_serves_a_job_whose_mission_is_still_null(api_client, auth_headers, db_manager):
    """``AgentJob.mission`` is nullable BY DESIGN -- a chain conductor is minted
    with ``mission=None`` and stays NULL until it calls ``update_job_mission``
    (permanently, if it never does), and so is any specialist staged but not yet
    given a Phase-2 mission. ``JobResponse.mission`` is a required ``str``, so
    passing the column through raw feeds ``None`` into a required field and
    pydantic raises -> 500 on this very route.

    Same defect class as the rest of this file: a field that is LEGITIMATELY
    absent at this moment read as though it were always populated. The fix
    belongs at the producer (empty string), NOT in the schema -- weakening
    ``mission`` to optional would push the ``None`` downstream, exactly as it
    would have for ``created_at``.

    Both endpoints are asserted because they now share one producer
    (``_build_job_dict``): the LIST route had this same NULL-mission 500
    independently, and the shared producer closes it in the same line.
    """
    tenant_key = _extract_tenant_key(auth_headers)
    project_id = await _seed_project(db_manager, tenant_key, launched=True)
    job_id, db_created_at, _ = await _seed_job(
        db_manager,
        tenant_key,
        project_id,
        job_type="orchestrator",
        display_name="conductor",
        status="waiting",
        mission=None,
    )

    detail = await api_client.get(f"/api/agent-jobs/{job_id}", headers=auth_headers)
    listing = await api_client.get("/api/agent-jobs/", headers=auth_headers, params={"project_id": project_id})

    assert detail.status_code == 200, f"single-job GET failed for a NULL-mission job: {detail.text}"
    assert listing.status_code == 200, f"list GET failed for a NULL-mission job: {listing.text}"

    body = detail.json()
    assert body["mission"] == "", "an unwritten mission must serve as empty, never as null or invented text"
    _assert_same_instant(body["created_at"], db_created_at, "created_at")

    from_list = next(job for job in listing.json()["jobs"] if job["job_id"] == job_id)
    assert from_list["mission"] == body["mission"], (
        f"detail and list disagree on a NULL mission: detail={body['mission']!r} list={from_list['mission']!r}"
    )


@pytest.mark.asyncio
async def test_get_single_job_is_tenant_isolated(api_client, auth_headers, db_manager):
    """ADR-009: another tenant's job must be 404, never readable."""
    other_tenant = f"tk_{uuid4().hex}"
    project_id = await _seed_project(db_manager, other_tenant, launched=True)
    job_id, _created, _completed = await _seed_job(
        db_manager,
        other_tenant,
        project_id,
        job_type="implementer",
        display_name="implementer",
        status="working",
    )

    resp = await api_client.get(f"/api/agent-jobs/{job_id}", headers=auth_headers)

    assert resp.status_code == 404, f"another tenant's job was reachable: {resp.status_code} {resp.text}"


@pytest.mark.asyncio
async def test_get_single_job_unknown_id_is_404(api_client, auth_headers):
    """An unknown job_id stays a 404, not a 500."""
    resp = await api_client.get(f"/api/agent-jobs/{uuid4()}", headers=auth_headers)
    assert resp.status_code == 404, resp.text
