# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from api.endpoints.projects.lifecycle import archive_project as archive_endpoint
from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.schemas.service_responses import ProjectData
from giljo_mcp.services.project_service._archive_mixin import ArchiveMixin


pytestmark = pytest.mark.asyncio


class _RecordingArchiveService(ArchiveMixin):

    def __init__(self, *, early_termination: bool = False, status: str = "active") -> None:
        self.update_calls: list[dict] = []
        self.deactivated: list[str] = []
        self.closed_for: list[str] = []
        self.tenant_manager = SimpleNamespace(get_current_tenant=lambda: "tk")
        self._websocket_manager = None
        self._project = SimpleNamespace(
            id="p-be9343",
            name="Ship date under test",
            status=status,
            early_termination=early_termination,
        )
        self.closeout = SimpleNamespace(close_completed_agents_with_commit=self._close_agents)

    async def get_project(self, project_id: str, tenant_key: str):  # noqa: ARG002
        return self._project

    async def deactivate_project(self, project_id: str, tenant_key: str | None = None):  # noqa: ARG002
        self.deactivated.append(project_id)

    async def update_project(self, project_id: str, updates: dict, websocket_manager=None):  # noqa: ARG002
        self.update_calls.append(updates)
        return ProjectData(id=self._project.id, name=self._project.name, status=str(updates.get("status", "")))

    async def _close_agents(self, project_id: str, tenant_key: str):  # noqa: ARG002
        self.closed_for.append(project_id)
        return []

    async def _missing_closeout_blockers(self, project_id: str, tenant_key: str):  # noqa: ARG002
        return None


_USER = SimpleNamespace(username="patrik", tenant_key="tk")


async def test_archive_does_not_send_completed_at() -> None:
    service = _RecordingArchiveService()

    await service.archive_project(project_id="p-be9343", tenant_key="tk", force=True)

    assert len(service.update_calls) == 1, "archive must issue exactly one update"
    updates = service.update_calls[0]
    assert "completed_at" not in updates, (
        "archive must NOT pass completed_at — the service stamps it only when absent, so "
        "passing one overwrites the real closeout/ship date with the archive-press time"
    )
    assert updates == {"status": ProjectStatus.COMPLETED}, "archive should send the status transition and nothing else"


async def test_archive_of_an_early_terminated_project_also_sends_no_date() -> None:
    service = _RecordingArchiveService(early_termination=True)

    await service.archive_project(project_id="p-be9343", tenant_key="tk", force=True)

    assert service.update_calls == [{"status": ProjectStatus.TERMINATED}]


async def test_archive_still_deactivates_a_running_project() -> None:
    service = _RecordingArchiveService(status="active")

    result = await service.archive_project(project_id="p-be9343", tenant_key="tk", force=True)

    assert service.deactivated == ["p-be9343"], "an active project must still be deactivated first"
    assert result.deactivated is True, "the result must report the step that actually ran"


async def test_archive_skips_deactivation_for_an_already_terminal_project() -> None:
    service = _RecordingArchiveService(status=ProjectStatus.COMPLETED)

    result = await service.archive_project(project_id="p-be9343", tenant_key="tk", force=True)

    assert service.deactivated == []
    assert result.deactivated is False


async def test_archive_closes_completed_agents() -> None:
    service = _RecordingArchiveService()

    await service.archive_project(project_id="p-be9343", tenant_key="tk", force=True)

    assert service.closed_for == ["p-be9343"], "archive must always run the agent-closure step"


async def test_the_endpoint_delegates_instead_of_keeping_its_own_copy() -> None:
    calls: list[dict] = []

    class _DelegatingService:
        async def archive_project(self, project_id: str, tenant_key: str | None = None, force: bool = False):
            calls.append({"project_id": project_id, "tenant_key": tenant_key, "force": force})

        async def get_project(self, project_id: str, tenant_key: str):  # noqa: ARG002
            return SimpleNamespace(
                id=project_id,
                alias="BE-9343",
                name="Ship date under test",
                description="",
                mission="",
                status=ProjectStatus.COMPLETED,
                staging_status=None,
                early_termination=False,
                cancellation_reason=None,
                created_at=datetime(2026, 7, 1, tzinfo=UTC),
                updated_at=datetime(2026, 7, 20, tzinfo=UTC),
                completed_at=datetime(2026, 7, 1, 10, 0, tzinfo=UTC),
                product_id="prod-1",
                tenant_key="tk",
                execution_mode="claude_code_cli",
                auto_checkin_enabled=False,
                auto_checkin_interval=15,
                project_type_id=None,
                project_type=None,
                series_number=1,
                subseries=None,
                taxonomy_alias="BE-9343",
                hidden=False,
                successor_project_id=None,
                implementation_launched_at=None,
                agents=[],
                agent_count=0,
                message_count=0,
            )

    await archive_endpoint(project_id="p-be9343", current_user=_USER, project_service=_DelegatingService())

    assert calls == [{"project_id": "p-be9343", "tenant_key": "tk", "force": True}]
