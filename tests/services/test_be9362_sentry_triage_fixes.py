# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from giljo_mcp.database import tenant_session_context
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.organizations import Organization
from giljo_mcp.repositories.org_repository import OrgRepository
from giljo_mcp.repositories.product_memory_repository import ProductMemoryRepository
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.dto import MemoryEntryCreateParams
from giljo_mcp.services.org_service import OrgService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


def _tk(suffix: str) -> str:
    return f"tk_be9362_{suffix}_{uuid.uuid4().hex[:8]}"


def _org(tenant_key: str, *, name: str, slug: str, setup_complete: bool = False) -> Organization:
    return Organization(
        tenant_key=tenant_key,
        name=name,
        slug=slug,
        settings={},
        org_setup_complete=setup_complete,
    )




async def test_slug_check_sees_other_tenants_under_guard(db_session):
    tenant_a, tenant_b = _tk("checkA"), _tk("checkB")
    taken_slug = f"my-workspace-{uuid.uuid4().hex[:6]}"
    db_session.add(_org(tenant_b, name="Other Org", slug=taken_slug, setup_complete=True))
    await db_session.flush()

    repo = OrgRepository()
    with tenant_session_context(db_session, tenant_a):
        taken = await repo.slug_taken_by_other_org(db_session, taken_slug, exclude_org_id="not-a-real-org-id")
    assert taken is True, "cross-tenant slug owner must be visible to the global uniqueness check"


async def test_second_tenant_default_workspace_name_succeeds(db_session):
    tenant_a, tenant_b = _tk("setupA"), _tk("setupB")
    marker = uuid.uuid4().hex[:6]
    wanted_name = f"My Workspace {marker}"
    base_slug = f"my-workspace-{marker}"

    org_a = _org(tenant_a, name="Pending", slug=f"pending-{uuid.uuid4().hex[:8]}")
    db_session.add(org_a)
    db_session.add(_org(tenant_b, name=wanted_name, slug=base_slug, setup_complete=True))
    await db_session.flush()

    with tenant_session_context(db_session, tenant_a):
        svc = OrgService(db_session)
        org = await svc.complete_first_login_setup(
            org_id=org_a.id,
            tenant_key=tenant_a,
            org_name=wanted_name,
        )

    assert org.org_setup_complete is True
    assert org.slug != base_slug
    assert org.slug.startswith(f"{base_slug}-"), "collision must resolve by suffixing, not by failing"


async def test_slug_race_retries_with_suffix_instead_of_500(db_session, monkeypatch):
    tenant_a = _tk("raceA")
    marker = uuid.uuid4().hex[:6]
    wanted_name = f"My Workspace {marker}"
    base_slug = f"my-workspace-{marker}"

    org_a = _org(tenant_a, name="Pending", slug=f"pending-{uuid.uuid4().hex[:8]}")
    db_session.add(org_a)
    await db_session.flush()

    from sqlalchemy.exc import IntegrityError as SAIntegrityError

    real_commit = db_session.commit
    fired = {"n": 0}

    async def _commit_collides_once(*args, **kwargs):
        if fired["n"] == 0:
            fired["n"] += 1
            raise SAIntegrityError(
                "UPDATE organizations SET slug=...",
                {},
                Exception('duplicate key value violates unique constraint "idx_org_slug"'),
            )
        return await real_commit(*args, **kwargs)

    async def _rollback_noop(*args, **kwargs):
        pass

    monkeypatch.setattr(db_session, "commit", _commit_collides_once)
    monkeypatch.setattr(db_session, "rollback", _rollback_noop)

    with tenant_session_context(db_session, tenant_a):
        svc = OrgService(db_session)
        org = await svc.complete_first_login_setup(
            org_id=org_a.id,
            tenant_key=tenant_a,
            org_name=wanted_name,
        )

    assert fired["n"] == 1, "the injected collision must have fired"
    assert org.org_setup_complete is True
    assert org.slug.startswith(f"{base_slug}-"), "IntegrityError path must recover via the suffix retry"




def _comm_service(db_manager, db_session) -> CommThreadService:
    return CommThreadService(db_manager, TenantManager(), session=db_session)


async def _seed_comm(db_session, tenant: str) -> None:
    with tenant_session_context(db_session, tenant):
        await ensure_default_types_seeded(db_session, tenant)


async def test_join_thread_long_role_is_clamped_not_500(db_manager, db_session):
    tenant = _tk("role")
    await _seed_comm(db_session, tenant)
    svc = _comm_service(db_manager, db_session)

    thread = await svc.create_thread(subject="role cap", creator_id="agent-orch", tenant_key=tenant)
    long_role = "HRMS_Config knowledge owner / Hermes rebuild reference"
    assert len(long_role) > 50

    result = await svc.join_thread(
        thread_id=thread["thread_id"],
        participant_id="HRMS_folder_agent",
        display_name="HRMS Folder Agent",
        role=long_role,
        tenant_key=tenant,
    )
    assert result["participant_id"] == "HRMS_folder_agent"

    from sqlalchemy import select

    from giljo_mcp.models.comm import CommParticipant

    with tenant_session_context(db_session, tenant):
        row = (
            await db_session.execute(
                select(CommParticipant).where(
                    CommParticipant.tenant_key == tenant,
                    CommParticipant.thread_id == thread["thread_id"],
                    CommParticipant.participant_id == "HRMS_folder_agent",
                )
            )
        ).scalar_one()
    assert row.role == long_role[:50]


async def test_join_thread_long_display_name_is_clamped(db_manager, db_session):
    tenant = _tk("dname")
    await _seed_comm(db_session, tenant)
    svc = _comm_service(db_manager, db_session)
    thread = await svc.create_thread(subject="name cap", creator_id="agent-orch", tenant_key=tenant)

    long_name = "N" * 300
    await svc.join_thread(
        thread_id=thread["thread_id"],
        participant_id="agent-long-name",
        display_name=long_name,
        tenant_key=tenant,
    )

    from sqlalchemy import select

    from giljo_mcp.models.comm import CommParticipant

    with tenant_session_context(db_session, tenant):
        row = (
            await db_session.execute(
                select(CommParticipant).where(
                    CommParticipant.tenant_key == tenant,
                    CommParticipant.thread_id == thread["thread_id"],
                    CommParticipant.participant_id == "agent-long-name",
                )
            )
        ).scalar_one()
    assert row.display_name == "N" * 255


async def test_join_thread_oversized_participant_id_rejected(db_manager, db_session):
    tenant = _tk("pid")
    await _seed_comm(db_session, tenant)
    svc = _comm_service(db_manager, db_session)
    thread = await svc.create_thread(subject="pid cap", creator_id="agent-orch", tenant_key=tenant)

    with pytest.raises(ValidationError):
        await svc.join_thread(
            thread_id=thread["thread_id"],
            participant_id="p" * 300,
            tenant_key=tenant,
        )




async def test_git_history_sort_survives_none_dates(db_session, test_product, test_tenant_key):
    repo = ProductMemoryRepository()
    await repo.create_entry(
        session=db_session,
        params=MemoryEntryCreateParams(
            tenant_key=test_tenant_key,
            product_id=test_product.id,
            sequence=1,
            entry_type="project_completion",
            source="test_v1",
            timestamp=datetime.now(tz=UTC),
            git_commits=[
                {"sha": "a" * 40, "message": "dated", "date": "2026-08-01T00:00:00Z"},
                {"sha": "b" * 40, "message": "null date", "date": None},
            ],
        ),
    )
    await repo.create_entry(
        session=db_session,
        params=MemoryEntryCreateParams(
            tenant_key=test_tenant_key,
            product_id=test_product.id,
            sequence=2,
            entry_type="project_completion",
            source="test_v1",
            timestamp=datetime.now(tz=UTC),
            git_commits=[{"sha": "c" * 40, "message": "no date key"}],
        ),
    )

    commits = await repo.get_git_history(
        session=db_session,
        product_id=test_product.id,
        tenant_key=test_tenant_key,
        limit=10,
    )

    assert len(commits) == 3
    assert commits[0]["message"] == "dated", "dated commits sort before undated ones"
