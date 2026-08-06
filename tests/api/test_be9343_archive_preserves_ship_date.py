# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9343 audit F3 — the Archive press must not overwrite a real ship date.

``archive_project`` passed ``completed_at=datetime.now(UTC)`` UNCONDITIONALLY. Because
BE-9343's service-layer stamp is deliberately additive — it steps aside whenever the
caller supplies the field — that unconditional value won every time, and it destroyed
the ship date on the ordinary solo flow:

    T1  an agent runs write_project_closeout  -> completed_at = T1 (the real ship date)
    T2  the user presses Archive              -> completed_at = T2 (the press time)

That is precisely the "archiving a project changed its completion date" defect BE-9343
exists to remove, and it sat against ``ce_0088``, which deliberately prefers the exact
``closeout_executed_at`` over a drifted timestamp. The migration and the live archive
path embodied opposite philosophies.

The fix is subtraction: the endpoint stops passing the field and lets the service's
``is None`` guard decide. So the endpoint's *composition of the update dict* is the
failing layer, and that is what these tests pin — a service-layer test cannot see a
field the endpoint chose to send.

Edition Scope: CE (``api/endpoints/projects/lifecycle.py`` is CE).
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from api.endpoints.projects.lifecycle import archive_project
from giljo_mcp.domain.project_status import ProjectStatus


pytestmark = pytest.mark.asyncio


class _RecordingProjectService:
    """Records every ``update_project`` call so the update dict itself can be asserted."""

    def __init__(self, *, early_termination: bool = False, status: str = "active") -> None:
        self.update_calls: list[dict] = []
        self.deactivated: list[str] = []
        self._project = SimpleNamespace(
            id="p-be9343",
            alias="BE-9343",
            name="Ship date under test",
            description="",
            mission="",
            status=status,
            staging_status=None,
            early_termination=early_termination,
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
        self.closeout = SimpleNamespace(close_completed_agents_with_commit=self._close_agents)

    async def get_project(self, project_id: str, tenant_key: str):  # noqa: ARG002
        return self._project

    async def deactivate_project(self, project_id: str):
        self.deactivated.append(project_id)

    async def update_project(self, project_id: str, updates: dict):  # noqa: ARG002
        self.update_calls.append(updates)
        return self._project

    async def _close_agents(self, project_id: str, tenant_key: str):  # noqa: ARG002
        return []


_USER = SimpleNamespace(username="patrik", tenant_key="tk")


async def test_archive_does_not_send_completed_at() -> None:
    """THE regression. Sending the field at all is what destroyed the ship date.

    Asserted on the update dict rather than on a stored value, because the service's
    stamp is additive by design: any value the endpoint sends wins, so "did the endpoint
    send one" IS the defect.
    """
    service = _RecordingProjectService()

    await archive_project(project_id="p-be9343", current_user=_USER, project_service=service)

    assert len(service.update_calls) == 1, "archive must issue exactly one update"
    updates = service.update_calls[0]
    assert "completed_at" not in updates, (
        "archive must NOT pass completed_at — the service stamps it only when absent, so "
        "passing one overwrites the real closeout/ship date with the archive-press time"
    )
    assert updates == {"status": ProjectStatus.COMPLETED}, "archive should send the status transition and nothing else"


async def test_archive_of_an_early_terminated_project_also_sends_no_date() -> None:
    """The early-termination branch picks a different status and must not regress either."""
    service = _RecordingProjectService(early_termination=True)

    await archive_project(project_id="p-be9343", current_user=_USER, project_service=service)

    assert service.update_calls == [{"status": ProjectStatus.TERMINATED}]


async def test_archive_still_deactivates_a_running_project() -> None:
    """Guard the surrounding behaviour the fix must not disturb.

    Removing an argument is the kind of edit that quietly takes a neighbouring branch
    with it, so the deactivate-skip gate is pinned in the same file.
    """
    service = _RecordingProjectService(status="active")

    await archive_project(project_id="p-be9343", current_user=_USER, project_service=service)

    assert service.deactivated == ["p-be9343"], "an active project must still be deactivated first"


async def test_archive_skips_deactivation_for_an_already_terminal_project() -> None:
    """The other side of that gate — a completed project must not be deactivated again."""
    service = _RecordingProjectService(status=ProjectStatus.COMPLETED)

    await archive_project(project_id="p-be9343", current_user=_USER, project_service=service)

    assert service.deactivated == []
