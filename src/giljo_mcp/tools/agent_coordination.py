# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Any

from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import ValidationError


logger = logging.getLogger(__name__)


class _AgentCoordinationState:

    db_manager_instance: DatabaseManager | None = None
    test_session = None


def _get_db_manager() -> DatabaseManager:
    if _AgentCoordinationState.db_manager_instance is None:
        _AgentCoordinationState.db_manager_instance = DatabaseManager()
    return _AgentCoordinationState.db_manager_instance


def set_db_manager(db_manager: DatabaseManager) -> None:
    _AgentCoordinationState.db_manager_instance = db_manager


def init_for_testing(db_manager: DatabaseManager, db_session) -> None:
    _AgentCoordinationState.db_manager_instance = db_manager
    _AgentCoordinationState.test_session = db_session


def _create_job_manager():
    from giljo_mcp.services.agent_job_manager import AgentJobManager
    from giljo_mcp.tenant import TenantManager

    db_manager = _get_db_manager()
    tenant_manager = TenantManager()
    return AgentJobManager(
        db_manager=db_manager,
        tenant_manager=tenant_manager,
        test_session=_AgentCoordinationState.test_session,
    )


async def spawn_agent(
    job_id: str,
    agent_display_name: str,
    tenant_key: str,
    spawned_by_agent_id: str = None,
) -> dict[str, Any]:
    if not job_id or not job_id.strip():
        raise ValidationError(message="job_id cannot be empty")

    if not agent_display_name or not agent_display_name.strip():
        raise ValidationError(message="agent_display_name cannot be empty")

    if not tenant_key or not tenant_key.strip():
        raise ValidationError(message="tenant_key cannot be empty")

    job_manager = _create_job_manager()
    job_id, new_agent_id = await job_manager.spawn_execution(
        job_id=job_id,
        agent_display_name=agent_display_name,
        tenant_key=tenant_key,
        spawned_by=spawned_by_agent_id,
    )

    logger.info(f"[spawn_agent] Spawned agent_id={new_agent_id} for job_id={job_id}, tenant={tenant_key}")

    return {
        "success": True,
        "job_id": job_id,
        "agent_id": new_agent_id,
    }


async def get_team_agents(
    job_id: str,
    tenant_key: str,
    include_inactive: bool = False,
) -> dict[str, Any]:
    if not job_id or not job_id.strip():
        raise ValidationError(message="job_id cannot be empty")

    if not tenant_key or not tenant_key.strip():
        raise ValidationError(message="tenant_key cannot be empty")

    job_manager = _create_job_manager()
    team_members = await job_manager.list_team_agents(
        job_id=job_id,
        tenant_key=tenant_key,
        include_inactive=include_inactive,
    )

    logger.info(
        f"[get_team_agents] Retrieved {len(team_members)} teammates for job {job_id}, "
        f"include_inactive={include_inactive}, tenant={tenant_key}"
    )

    return {
        "success": True,
        "team": team_members,
    }
