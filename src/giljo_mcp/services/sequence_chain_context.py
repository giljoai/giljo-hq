# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import ImplementationNotReadyError
from giljo_mcp.models.projects import Project
from giljo_mcp.services.execution_mode_gate import effective_execution_mode
from giljo_mcp.services.sequence_run_service import SequenceRunService, active_chain_run
from giljo_mcp.tenant import TenantManager


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChainContext:

    run_id: str
    role: str
    current_index: int
    resolved_order: list[str]
    is_staging: bool
    conductor_agent_id: str | None
    execution_mode: str | None = None
    chain_mission: str | None = None


async def chain_execution_mode_for_project(session: AsyncSession, *, project_id: str, tenant_key: str) -> str | None:
    run = await active_chain_run(session, project_id, tenant_key)
    return run.get("execution_mode") if run else None


async def renders_multi_terminal(session: AsyncSession, *, project: Any, project_id: str, tenant_key: str) -> bool:
    mode = effective_execution_mode(
        getattr(project, "execution_mode", "multi_terminal"),
        await chain_execution_mode_for_project(session, project_id=project_id, tenant_key=tenant_key),
    )
    return (mode or "multi_terminal") == "multi_terminal"


class SequenceChainContextResolver:

    def __init__(
        self,
        db_manager: DatabaseManager | None,
        tenant_manager: TenantManager | None,
        websocket_manager=None,
        test_session: AsyncSession | None = None,
    ):
        self.db_manager = db_manager
        self.tenant_manager = tenant_manager
        self._websocket_manager = websocket_manager
        self._test_session = test_session

    def _get_session(self, tenant_key: str | None = None):
        if self._test_session is not None:

            @asynccontextmanager
            async def _test_session_wrapper():
                if tenant_key:
                    self._test_session.info["tenant_key"] = tenant_key
                yield self._test_session

            return _test_session_wrapper()

        if tenant_key:

            @asynccontextmanager
            async def _tenant_session_wrapper():
                async with self.db_manager.get_session_async() as session:
                    session.info["tenant_key"] = tenant_key
                    yield session

            return _tenant_session_wrapper()
        return self.db_manager.get_session_async()

    async def resolve(
        self,
        session: AsyncSession,
        *,
        project_id: str,
        tenant_key: str,
        orchestrator_agent_id: str,
        is_staging: bool,
    ) -> ChainContext | None:
        svc = SequenceRunService(
            db_manager=self.db_manager,
            tenant_manager=self.tenant_manager,
            session=session,
        )
        run = await svc.find_active_run_for_project(project_id=project_id, tenant_key=tenant_key)
        if run is None:
            return None

        resolved_order: list[str] = run.get("resolved_order") or []
        effective_conductor_agent_id: str | None = run.get("conductor_agent_id")

        role = (
            "conductor"
            if (effective_conductor_agent_id is not None and orchestrator_agent_id == effective_conductor_agent_id)
            else "sub_orchestrator"
        )

        if effective_conductor_agent_id is None:
            try:
                updated = await svc.update(
                    run_id=run["id"],
                    tenant_key=tenant_key,
                    conductor_agent_id=orchestrator_agent_id,
                    conductor_label=orchestrator_agent_id[:36],
                )
                effective_conductor_agent_id = updated.get("conductor_agent_id")
                role = "conductor"
                await self._broadcast_sequence_updated(run["id"], tenant_key)
            except Exception as exc:  # noqa: BLE001 (self-registration write is non-fatal to classification)
                logger.warning(
                    "conductor self-registration fallback write failed for run %s "
                    "(treating this agent as conductor anyway): %s",
                    run["id"],
                    exc,
                )
                effective_conductor_agent_id = orchestrator_agent_id
                role = "conductor"

        return ChainContext(
            run_id=run["id"],
            role=role,
            current_index=run.get("current_index", 0),
            resolved_order=resolved_order,
            is_staging=is_staging,
            conductor_agent_id=effective_conductor_agent_id,
            execution_mode=run.get("execution_mode"),
            chain_mission=run.get("chain_mission"),
        )

    async def resolve_for_conductor(
        self,
        session: AsyncSession,
        *,
        conductor_agent_id: str,
        tenant_key: str,
        is_staging: bool = False,
    ) -> ChainContext | None:
        svc = SequenceRunService(
            db_manager=self.db_manager,
            tenant_manager=self.tenant_manager,
            session=session,
        )
        run = await svc.find_active_run_for_conductor(conductor_agent_id=conductor_agent_id, tenant_key=tenant_key)
        if run is None:
            return None
        return ChainContext(
            run_id=run["id"],
            role="conductor",
            current_index=run.get("current_index", 0),
            resolved_order=run.get("resolved_order") or [],
            is_staging=is_staging,
            conductor_agent_id=run.get("conductor_agent_id"),
            execution_mode=run.get("execution_mode"),
            chain_mission=run.get("chain_mission"),
        )

    async def _broadcast_sequence_updated(self, run_id: str, tenant_key: str) -> None:
        if self._websocket_manager is None:
            return
        try:
            event = {"type": "sequence:updated", "data": {"run_id": run_id}}
            await self._websocket_manager.broadcast_event_to_tenant(tenant_key, event)
        except Exception as exc:  # noqa: BLE001 — WS broadcast is a best-effort side-effect
            logger.warning("sequence:updated broadcast failed for run %s: %s", run_id, exc)

    async def advance_index_if_committed(
        self,
        *,
        run_id: str,
        project_id: str,
        tenant_key: str,
        next_index: int,
    ) -> bool:
        async with self._get_session(tenant_key) as session:
            proj_result = await session.execute(
                select(Project).where(
                    Project.id == project_id,
                    Project.tenant_key == tenant_key,
                )
            )
            project = proj_result.scalar_one_or_none()
            if project is None or project.closeout_executed_at is None:
                return False

            svc = SequenceRunService(
                db_manager=self.db_manager,
                tenant_manager=self.tenant_manager,
                session=session,
                websocket_manager=self._websocket_manager,
            )
            await svc.update(run_id=run_id, tenant_key=tenant_key, current_index=next_index)
            return True

    async def mark_stalled_if_past_deadline(
        self,
        *,
        run_id: str,
        tenant_key: str,
        deadline_iso_or_dt: str | datetime,
        now: datetime | None = None,
    ) -> bool:
        effective_now = now if now is not None else datetime.now(UTC)
        deadline = (
            datetime.fromisoformat(deadline_iso_or_dt) if isinstance(deadline_iso_or_dt, str) else deadline_iso_or_dt
        )

        if not (effective_now > deadline):
            return False

        async with self._get_session(tenant_key) as session:
            svc = SequenceRunService(
                db_manager=self.db_manager,
                tenant_manager=self.tenant_manager,
                session=session,
                websocket_manager=self._websocket_manager,
            )
            await svc.update(run_id=run_id, tenant_key=tenant_key, status="stalled")
            return True


def chain_member_phase(project: Any) -> str:
    launched = getattr(project, "implementation_launched_at", None) is not None
    staging_finished = getattr(project, "staging_status", None) == "staging_complete"
    return "implementation" if (launched and staging_finished) else "staging"


async def resolve_chain_launch_gate(session: Any, *, project_id: str, tenant_key: str) -> tuple[bool, Any | None]:
    run = await active_chain_run(session, project_id, tenant_key)
    if run is None:
        return False, None

    resolved_order: list[str] = run.get("resolved_order") or []
    if project_id not in resolved_order:
        return False, None

    index = resolved_order.index(project_id)
    if index <= run.get("current_index", 0):
        return True, None

    predecessor = (
        await session.execute(
            select(Project).where(
                Project.id == resolved_order[index - 1],
                Project.tenant_key == tenant_key,
            )
        )
    ).scalar_one_or_none()
    if predecessor is None or predecessor.closeout_executed_at is not None:
        return True, None
    return True, predecessor


def chain_predecessor_open_error(project: Any, predecessor: Any) -> Any:
    alias = predecessor.alias or predecessor.name
    return ImplementationNotReadyError(
        reason="chain_predecessor_open",
        message=(
            f"Cannot start this chain member yet: {alias} is still open. Linked projects run "
            "one at a time — the project before this one has to close out "
            "(write_project_closeout) before this one can start."
        ),
        context={
            "project_id": project.id,
            "predecessor_project_id": predecessor.id,
            "predecessor_alias": alias,
        },
    )
