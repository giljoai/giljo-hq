# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
BE-9385d: ``services/orchestrator_product_resolver`` and the identity it produces.

**Edition Scope:** Both.

The resolver answers "which product's orchestrator override applies to this job", then
walks the product -> tenant -> seed ladder for it. These tests reach it the way
production does -- through ``MissionService._resolve_mission_template`` against the
REAL ``SystemPromptService`` (only the repository and the sequence-run lookup are
doubled) -- so they exercise the real resolver and the real ladder rather than a
re-implementation of either.

**Premortem #4 is the reason this file exists.** The dedicated chain conductor is
PROJECT-LESS (``job.project_id IS NULL``, BE-6184), so a naive ``project.product_id``
read drops the conductor to the tenant rung while its member projects resolve the
product one. The chain then runs with two different orchestrator personas -- which
presents as flakiness, not as a bug, and is therefore expensive to find later.
``test_conductor_resolves_the_same_rung_as_its_member`` pins that shut.

Note the conductor identity is additionally role-TRIMMED (BE-6211g) and so is not
byte-equal to a member's. That is deliberate and orthogonal: parity here means "same
rung of the override ladder", which is what these tests assert.
"""

from __future__ import annotations

import logging
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from giljo_mcp.system_prompts.service import SystemPromptService
from giljo_mcp.template_seeder import compose_orchestrator_identity


TENANT_TEXT = "TENANT-WIDE orchestrator seed for BE-9385d."
PRODUCT_TEXT = "PRODUCT-SCOPED orchestrator seed for BE-9385d."
MEMBER_PROJECT_ID = "proj-be9385d-member"


def _make_mission_service(db_manager, *, project_row):
    """A MissionService with only its repository doubled (identity path is real)."""
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


async def _seed_overrides(db_manager, db_session, tenant_key, *, product_id=None, tenant=True, product=False):
    service = SystemPromptService(db_manager=db_manager)
    if tenant:
        await service.update_orchestrator_prompt(
            tenant_key=tenant_key, content=TENANT_TEXT, updated_by="admin", session=db_session
        )
    if product:
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
        await _seed_overrides(db_manager, db_session, test_tenant_key, product_id=product_id, tenant=True, product=True)

        svc = _make_mission_service(db_manager, project_row=_project_row(product_id))
        identity, _status, _source = await svc._resolve_mission_template(
            db_session, _orchestrator_job(project_id=MEMBER_PROJECT_ID), _execution(), test_tenant_key
        )

        assert PRODUCT_TEXT in identity
        assert TENANT_TEXT not in identity

    async def test_falls_back_to_tenant_override_byte_identically(self, db_manager, db_session, test_tenant_key):
        """No override for this product -> the tenant's saved bytes, unchanged.

        Equality against ``compose_orchestrator_identity`` is the real assertion: a
        tenant that customized its orchestrator before this feature existed must get
        exactly the identity it got yesterday.
        """
        from giljo_mcp.services.mission_service import _EXECUTION_MODE_TO_TOOL

        await _seed_overrides(db_manager, db_session, test_tenant_key, tenant=True, product=False)

        svc = _make_mission_service(db_manager, project_row=_project_row(str(uuid.uuid4())))
        identity, _status, _source = await svc._resolve_mission_template(
            db_session, _orchestrator_job(project_id=MEMBER_PROJECT_ID), _execution(), test_tenant_key
        )

        expected_tool = _EXECUTION_MODE_TO_TOOL.get("multi_terminal", "multi_terminal")
        # FE-9408 made the served identity composed-bytes + one appended provenance
        # line. Splitting on that delta keeps this assertion exactly as strict as it was
        # about the CONTENT -- which is the whole point of the test -- while also
        # pinning that the line names the rung that actually answered.
        composed, _, source_line = identity.rpartition("\n\n")
        assert composed == compose_orchestrator_identity(TENANT_TEXT, tool=expected_tool)
        assert source_line.startswith("identity source: tenant-wide override, saved ")

    async def test_seed_used_when_no_override_at_any_rung(self, db_manager, db_session, test_tenant_key):
        from giljo_mcp.services.mission_service import _EXECUTION_MODE_TO_TOOL

        svc = _make_mission_service(db_manager, project_row=_project_row(str(uuid.uuid4())))
        identity, _status, _source = await svc._resolve_mission_template(
            db_session, _orchestrator_job(project_id=MEMBER_PROJECT_ID), _execution(), test_tenant_key
        )

        expected_tool = _EXECUTION_MODE_TO_TOOL.get("multi_terminal", "multi_terminal")
        composed, _, source_line = identity.rpartition("\n\n")
        assert composed == compose_orchestrator_identity(None, tool=expected_tool)
        assert source_line == "identity source: built-in default"

    async def test_project_without_a_product_uses_the_tenant_rung(self, db_manager, db_session, test_tenant_key):
        """A project with no product_id is a product-less context, not an error."""
        await _seed_overrides(db_manager, db_session, test_tenant_key, tenant=True, product=False)

        svc = _make_mission_service(db_manager, project_row=_project_row(None))
        identity, _status, _source = await svc._resolve_mission_template(
            db_session, _orchestrator_job(project_id=MEMBER_PROJECT_ID), _execution(), test_tenant_key
        )
        assert TENANT_TEXT in identity

    async def test_unusable_product_id_still_yields_the_tenant_override(self, db_manager, db_session, test_tenant_key):
        """An id that is not a UUID must degrade to the tenant rung, NOT to the seed.

        The strict boundary validation raises on a malformed product_id, which is
        right for REST. Reaching identity resolution, that same raise would be caught
        by the surrounding broad ``except`` and the tenant's own saved override would
        be quietly replaced by the packaged default -- a customization disappearing
        because of an unrelated data problem, and looking like nothing at all.
        """
        await _seed_overrides(db_manager, db_session, test_tenant_key, tenant=True, product=False)

        svc = _make_mission_service(db_manager, project_row=_project_row("not-a-uuid"))
        identity, _status, _source = await svc._resolve_mission_template(
            db_session, _orchestrator_job(project_id=MEMBER_PROJECT_ID), _execution(), test_tenant_key
        )
        assert TENANT_TEXT in identity, "a malformed product id must not cost the tenant its override"


@pytest.mark.asyncio
class TestProjectLessConductorIdentity:
    """PREMORTEM #4 -- the conductor must not silently sit on a different rung."""

    async def test_conductor_resolves_the_same_rung_as_its_member(self, db_manager, db_session, test_tenant_key):
        product_id = str(uuid.uuid4())
        await _seed_overrides(db_manager, db_session, test_tenant_key, product_id=product_id, tenant=True, product=True)

        job = _orchestrator_job(project_id=MEMBER_PROJECT_ID)
        execution = _execution()

        # The MEMBER: project-bound, product resolved off its own project row.
        member_svc = _make_mission_service(db_manager, project_row=_project_row(product_id))
        member_identity, _, _src = await member_svc._resolve_mission_template(
            db_session, job, execution, test_tenant_key
        )

        # The CONDUCTOR: project-less, product resolved through its active run's head
        # project -- the same rule conductor_staging_builder already uses.
        conductor_svc = _make_mission_service(db_manager, project_row=_project_row(product_id))
        with patch("giljo_mcp.services.sequence_run_service.SequenceRunService") as run_cls:
            run_cls.return_value.find_active_run_for_conductor = AsyncMock(
                return_value={"resolved_order": [MEMBER_PROJECT_ID]}
            )
            conductor_identity, _, _src = await conductor_svc._resolve_mission_template(
                db_session,
                _orchestrator_job(project_id=None),
                execution,
                test_tenant_key,
                is_chain_conductor=True,
                chain_execution_mode="multi_terminal",
            )

        assert PRODUCT_TEXT in member_identity
        assert PRODUCT_TEXT in conductor_identity, (
            "the project-less conductor fell through to a different rung than its members -- "
            "this is premortem #4, an inconsistent chain persona"
        )
        assert TENANT_TEXT not in conductor_identity

    async def test_conductor_with_no_active_run_uses_the_tenant_rung(self, db_manager, db_session, test_tenant_key):
        product_id = str(uuid.uuid4())
        await _seed_overrides(db_manager, db_session, test_tenant_key, product_id=product_id, tenant=True, product=True)

        svc = _make_mission_service(db_manager, project_row=_project_row(product_id))
        with patch("giljo_mcp.services.sequence_run_service.SequenceRunService") as run_cls:
            run_cls.return_value.find_active_run_for_conductor = AsyncMock(return_value=None)
            identity, _, _source = await svc._resolve_mission_template(
                db_session,
                _orchestrator_job(project_id=None),
                _execution(),
                test_tenant_key,
                is_chain_conductor=True,
                chain_execution_mode="multi_terminal",
            )

        assert TENANT_TEXT in identity
        assert PRODUCT_TEXT not in identity

    async def test_product_resolution_failure_never_breaks_identity_delivery(
        self, db_manager, db_session, test_tenant_key
    ):
        """Unknown context lands on the tenant rung and NEVER raises (brief, premortem #4)."""
        await _seed_overrides(db_manager, db_session, test_tenant_key, tenant=True, product=False)

        svc = _make_mission_service(db_manager, project_row=_project_row(None))
        with patch("giljo_mcp.services.sequence_run_service.SequenceRunService") as run_cls:
            run_cls.return_value.find_active_run_for_conductor = AsyncMock(
                side_effect=RuntimeError("sequence_run lookup failed")
            )
            identity, _, _source = await svc._resolve_mission_template(
                db_session,
                _orchestrator_job(project_id=None),
                _execution(),
                test_tenant_key,
                is_chain_conductor=True,
                chain_execution_mode="multi_terminal",
            )

        assert TENANT_TEXT in identity, "a failed product resolution must degrade, not propagate"
