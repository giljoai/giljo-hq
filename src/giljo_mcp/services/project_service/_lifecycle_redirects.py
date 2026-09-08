# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9499b: status-transition redirects for ``ProjectService.update_project``.

Split out of ``_mutation_mixin.py`` to keep that file's Guardrail-1 (800-line
file cap) and Guardrail-7 (200-line function cap) intact. Free functions that
take the live ``ProjectService`` instance as ``service`` rather than a mixin --
two narrowly-scoped helpers don't earn another MRO participant.

``route_active_inactive_status_transition`` closes the activate-bypass bug
(BE-9016's Sentry symptom) and adds the revival door ``continue_working`` had
no MCP path to: two status transitions are dedicated LIFECYCLE actions with
side effects the plain column write in ``update_project`` cannot reproduce --
activation (sibling auto-deactivate + orchestrator fixture mint) and reviving
a completed project (resuming decommissioned agent executions). Routing the
ONE source state each lifecycle facade actually handles through that SAME
facade here -- at the single writer both REST PATCH and the MCP tool call --
means no per-transport special-casing can drift the two doors apart. Every other status combination, including PARKED -> ACTIVE (IMP-9258's
deliberate two-way door), falls through unchanged to the plain write.

``validate_supersede_successor`` / ``require_supersede_successor`` enforce
that ``status='superseded'`` always carries a valid, eligible successor --
matching FE-9508's picker list exactly (active / completed / inactive).
"""

from __future__ import annotations

from typing import Any

from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.exceptions import AlreadyExistsError, ResourceNotFoundError, ValidationError
from giljo_mcp.models.projects import Project
from giljo_mcp.schemas.service_responses import ProjectData


# BE-9499b: matches FE-9508's frontend picker (frontend/src/stores/projects.js:
# fetchSuccessorCandidates) exactly. cancelled / terminated / deleted are dead
# ends of their own; superseded is excluded because a superseded successor
# risks looping the pointer chain. One door offering what the other refuses is
# the failure ruling 1 exists to prevent -- keep these two lists in step.
ELIGIBLE_SUPERSEDE_SUCCESSOR_STATUSES: frozenset[ProjectStatus] = frozenset(
    {ProjectStatus.ACTIVE, ProjectStatus.COMPLETED, ProjectStatus.INACTIVE}
)


async def route_active_inactive_status_transition(
    service: Any,
    project_id: str,
    updates: dict[str, Any],
    websocket_manager: Any | None,
) -> ProjectData | None:
    """Handle the two redirected transitions; return ``None`` to fall through
    to the plain write in ``ProjectService.update_project``."""
    if updates.get("status") not in (ProjectStatus.ACTIVE, ProjectStatus.INACTIVE):
        return None

    tenant_key = service.tenant_manager.get_current_tenant()
    async with service._get_session(tenant_key) as probe_session:
        probe = await service._repo.get_by_id(probe_session, tenant_key, project_id)
    if not probe:
        raise ResourceNotFoundError(message="Project not found", context={"project_id": project_id})

    if probe.status == ProjectStatus.COMPLETED:
        return await _revive_completed(service, project_id, updates, websocket_manager)

    if probe.status == ProjectStatus.INACTIVE and updates["status"] == ProjectStatus.ACTIVE:
        return await _activate_via_lifecycle(service, project_id, updates, websocket_manager)

    return None


async def _revive_completed(
    service: Any, project_id: str, updates: dict[str, Any], websocket_manager: Any | None
) -> ProjectData:
    tenant_key = service.tenant_manager.get_current_tenant()
    await service.lifecycle.continue_working(project_id, tenant_key=tenant_key)
    remaining = {k: v for k, v in updates.items() if k != "status"}
    if updates["status"] == ProjectStatus.ACTIVE:
        # continue_working always lands INACTIVE (avoids the single active
        # project constraint) -- an explicit ACTIVE request finishes the
        # transition through the activation redirect via one more pass
        # through update_project.
        return await service.update_project(
            project_id, {**remaining, "status": ProjectStatus.ACTIVE}, websocket_manager=websocket_manager
        )
    if remaining:
        return await service.update_project(project_id, remaining, websocket_manager=websocket_manager)
    return await _fresh_project_data(service, tenant_key, project_id)


async def _activate_via_lifecycle(
    service: Any, project_id: str, updates: dict[str, Any], websocket_manager: Any | None
) -> ProjectData:
    tenant_key = service.tenant_manager.get_current_tenant()
    other_updates = {k: v for k, v in updates.items() if k != "status"}
    if other_updates:
        await service.update_project(project_id, other_updates, websocket_manager=websocket_manager)
    await service.activate_project(project_id, tenant_key=tenant_key, websocket_manager=websocket_manager)
    fresh = await _fresh_project_data(service, tenant_key, project_id)
    if fresh.status != ProjectStatus.ACTIVE:
        # BE-9521, kept unreachable-but-harmless per BE-9525b: this guarded
        # against a concurrent SIBLING activation auto-deactivating this
        # project between its own commit and this re-read. BE-9525b (ruling 5
        # amended) removed that auto-deactivate step from
        # ProjectLifecycleService.activate_project entirely -- no code path
        # left ever flips another project's status during an activation -- so
        # this branch can no longer be entered. Left in place rather than
        # deleted: removing a weeks-old incident-fix guard is a separate
        # cleanup with its own zero-reachability proof, not bundled here.
        raise AlreadyExistsError(
            message=(
                "Another project is already active for this product. "
                "Deactivate it first, or use the activate endpoint, "
                "which handles this automatically."
            ),
            error_code="ANOTHER_PROJECT_ACTIVE",
            context={"project_id": project_id},
        )
    return fresh


async def _fresh_project_data(service: Any, tenant_key: str, project_id: str) -> ProjectData:
    async with service._get_session(tenant_key) as fresh_session:
        fresh = await service._repo.get_by_id_with_type(fresh_session, tenant_key, project_id)
    return service._build_project_data(fresh)


def validate_supersede_successor(project_id: str, updates: dict[str, Any], successor: Project) -> None:
    """Raise SUPERSEDE_REQUIRES_SUCCESSOR if ``successor`` is ineligible."""
    if updates.get("status") != ProjectStatus.SUPERSEDED:
        return
    if successor.status in ELIGIBLE_SUPERSEDE_SUCCESSOR_STATUSES:
        return
    raise ValidationError(
        message=(
            f"Successor project has status '{successor.status.value}', which cannot receive "
            "a superseded predecessor. Eligible successor statuses: "
            f"{', '.join(sorted(s.value for s in ELIGIBLE_SUPERSEDE_SUCCESSOR_STATUSES))}."
        ),
        error_code="SUPERSEDE_REQUIRES_SUCCESSOR",
        context={
            "project_id": project_id,
            "successor_project_id": str(successor.id),
            "successor_status": successor.status.value,
        },
    )


def require_supersede_successor(project_id: str, updates: dict[str, Any]) -> None:
    """Raise SUPERSEDE_REQUIRES_SUCCESSOR if superseded with no successor at all.

    A null-successor row is an audit-trail dead end
    (``_memory_helpers.refuse_if_superseded`` hands agents the pointer as the
    remedy for hitting a superseded project, which only works if it's always
    populated).
    """
    if updates.get("status") == ProjectStatus.SUPERSEDED and not updates.get("successor_project_id"):
        raise ValidationError(
            message="Marking a project superseded requires a successor_project_id in the same call.",
            error_code="SUPERSEDE_REQUIRES_SUCCESSOR",
            context={"project_id": project_id},
        )
