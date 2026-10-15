# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from giljo_mcp.system_prompts.service import SystemPromptService
from giljo_mcp.template_seeder import compose_orchestrator_identity


OTHER_PRODUCT_TEXT = "ANOTHER PRODUCT's orchestrator seed for BE-9385d."
PRODUCT_TEXT = "PRODUCT-SCOPED orchestrator seed for BE-9385d."
MEMBER_PROJECT_ID = "proj-be9385d-member"


def _make_mission_service(db_manager, *, project_row):
    from giljo_mcp.services.mission_service import MissionService

    svc = MissionService.__new__(MissionService)
    svc._logger = logging.getLogger("test_be9385d_identity")
    svc.db_manager = db_manager
    svc.tenant_manager = None
    svc._repo = MagicMock()
    svc._repo.get_project_by_id = AsyncMock(return_value=project_row)
    return svc


def _orchestrator_job(*, project_id: str | None):
    return SimpleNamespace(
        job_type="orchestrator",
        template_id=None,
        project_id=project_id,
        job_id=f"job-{project_id or 'conductor'}",
    )


def _execution():
    return SimpleNamespace(
        agent_name="orchestrator",
        agent_display_name="orchestrator",
        agent_id="agent-be9385d-conductor",
    )


def _project_row(product_id: str | None):
    return SimpleNamespace(
        id=MEMBER_PROJECT_ID,
        product_id=product_id,
        execution_mode="multi_terminal",
    )


async def _seed_overrides(db_manager, db_session, tenant_key, *, product_id=None):
    service = SystemPromptService(db_manager=db_manager)
    await service.update_orchestrator_prompt(
        tenant_key=tenant_key,
        content=OTHER_PRODUCT_TEXT,
        updated_by="admin",
        product_id=str(uuid.uuid4()),
        session=db_session,
    )
    if product_id:
        await service.update_orchestrator_prompt(
            tenant_key=tenant_key,
            content=PRODUCT_TEXT,
            updated_by="admin",
            product_id=product_id,
            session=db_session,
        )
    await db_session.commit()


@pytest.mark.asyncio
class TestProjectBoundOrchestratorIdentity:
    async def test_member_orchestrator_gets_its_products_override(self, db_manager, db_session, test_tenant_key):
        product_id = str(uuid.uuid4())
        await _seed_overrides(db_manager, db_session, test_tenant_key, product_id=product_id)

        svc = _make_mission_service(db_manager, project_row=_project_row(product_id))
        identity, _status, _source, _template = await svc._resolve_mission_template(
            db_session, _orchestrator_job(project_id=MEMBER_PROJECT_ID), _execution(), test_tenant_key
        )

        assert PRODUCT_TEXT in identity
        assert OTHER_PRODUCT_TEXT not in identity

    async def test_a_products_saved_text_is_served_byte_identically(self, db_manager, db_session, test_tenant_key):
        from giljo_mcp.services.mission_service import _EXECUTION_MODE_TO_TOOL

        product_id = str(uuid.uuid4())
        await _seed_overrides(db_manager, db_session, test_tenant_key, product_id=product_id)

        svc = _make_mission_service(db_manager, project_row=_project_row(product_id))
        identity, _status, _source, _template = await svc._resolve_mission_template(
            db_session, _orchestrator_job(project_id=MEMBER_PROJECT_ID), _execution(), test_tenant_key
        )

        expected_tool = _EXECUTION_MODE_TO_TOOL.get("multi_terminal", "multi_terminal")
        composed, _, source_line = identity.rpartition("\n\n")
        assert composed == compose_orchestrator_identity(PRODUCT_TEXT, tool=expected_tool)
        assert source_line.startswith("identity source: product override, saved ")

    async def test_seed_used_when_the_product_has_no_override(self, db_manager, db_session, test_tenant_key):
        from giljo_mcp.services.mission_service import _EXECUTION_MODE_TO_TOOL

        svc = _make_mission_service(db_manager, project_row=_project_row(str(uuid.uuid4())))
        identity, _status, _source, _template = await svc._resolve_mission_template(
            db_session, _orchestrator_job(project_id=MEMBER_PROJECT_ID), _execution(), test_tenant_key
        )

        expected_tool = _EXECUTION_MODE_TO_TOOL.get("multi_terminal", "multi_terminal")
        composed, _, source_line = identity.rpartition("\n\n")
        assert composed == compose_orchestrator_identity(None, tool=expected_tool)
        assert source_line == "identity source: built-in default"

    async def test_project_without_a_product_gets_the_built_in_prompt(self, db_manager, db_session, test_tenant_key):
        await _seed_overrides(db_manager, db_session, test_tenant_key)

        svc = _make_mission_service(db_manager, project_row=_project_row(None))
        identity, _status, _source, _template = await svc._resolve_mission_template(
            db_session, _orchestrator_job(project_id=MEMBER_PROJECT_ID), _execution(), test_tenant_key
        )
        assert OTHER_PRODUCT_TEXT not in identity
        assert identity.endswith("identity source: built-in default")

    async def test_unusable_product_id_degrades_to_the_built_in_prompt_without_raising(
        self, db_manager, db_session, test_tenant_key
    ):
        await _seed_overrides(db_manager, db_session, test_tenant_key)

        svc = _make_mission_service(db_manager, project_row=_project_row("not-a-uuid"))
        identity, _status, _source, _template = await svc._resolve_mission_template(
            db_session, _orchestrator_job(project_id=MEMBER_PROJECT_ID), _execution(), test_tenant_key
        )
        assert OTHER_PRODUCT_TEXT not in identity
        assert identity.endswith("identity source: built-in default")


@pytest.mark.asyncio
class TestProjectLessConductorIdentity:

    async def test_conductor_resolves_the_same_override_as_its_member(self, db_manager, db_session, test_tenant_key):
        product_id = str(uuid.uuid4())
        await _seed_overrides(db_manager, db_session, test_tenant_key, product_id=product_id)

        job = _orchestrator_job(project_id=MEMBER_PROJECT_ID)
        execution = _execution()

        member_svc = _make_mission_service(db_manager, project_row=_project_row(product_id))
        member_identity, _, _src, _template = await member_svc._resolve_mission_template(
            db_session, job, execution, test_tenant_key
        )

        conductor_svc = _make_mission_service(db_manager, project_row=_project_row(product_id))
        with patch("giljo_mcp.services.sequence_run_service.SequenceRunService") as run_cls:
            run_cls.return_value.find_active_run_for_conductor = AsyncMock(
                return_value={"resolved_order": [MEMBER_PROJECT_ID]}
            )
            conductor_identity, _, _src, _template = await conductor_svc._resolve_mission_template(
                db_session,
                _orchestrator_job(project_id=None),
                execution,
                test_tenant_key,
                is_chain_conductor=True,
                chain_execution_mode="multi_terminal",
            )

        assert PRODUCT_TEXT in member_identity
        assert PRODUCT_TEXT in conductor_identity, (
            "the project-less conductor fell through to a different override than its members -- "
            "this is premortem #4, an inconsistent chain persona"
        )
        assert OTHER_PRODUCT_TEXT not in conductor_identity

    async def test_conductor_with_no_active_run_gets_the_built_in_prompt(self, db_manager, db_session, test_tenant_key):
        product_id = str(uuid.uuid4())
        await _seed_overrides(db_manager, db_session, test_tenant_key, product_id=product_id)

        svc = _make_mission_service(db_manager, project_row=_project_row(product_id))
        with patch("giljo_mcp.services.sequence_run_service.SequenceRunService") as run_cls:
            run_cls.return_value.find_active_run_for_conductor = AsyncMock(return_value=None)
            identity, _, _source, _template = await svc._resolve_mission_template(
                db_session,
                _orchestrator_job(project_id=None),
                _execution(),
                test_tenant_key,
                is_chain_conductor=True,
                chain_execution_mode="multi_terminal",
            )

        assert PRODUCT_TEXT not in identity
        assert OTHER_PRODUCT_TEXT not in identity
        assert identity.endswith("identity source: built-in default")

    async def test_product_resolution_failure_never_breaks_identity_delivery(
        self, db_manager, db_session, test_tenant_key
    ):
        await _seed_overrides(db_manager, db_session, test_tenant_key)

        svc = _make_mission_service(db_manager, project_row=_project_row(None))
        with patch("giljo_mcp.services.sequence_run_service.SequenceRunService") as run_cls:
            run_cls.return_value.find_active_run_for_conductor = AsyncMock(
                side_effect=RuntimeError("sequence_run lookup failed")
            )
            identity, _, _source, _template = await svc._resolve_mission_template(
                db_session,
                _orchestrator_job(project_id=None),
                _execution(),
                test_tenant_key,
                is_chain_conductor=True,
                chain_execution_mode="multi_terminal",
            )

        assert OTHER_PRODUCT_TEXT not in identity
        assert identity.endswith("identity source: built-in default"), "a failed product resolution must degrade"
