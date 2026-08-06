# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""SequenceChainContextResolver — the sequential-runner sequence driver (BE-6165c).

Extracted out of MissionOrchestrationService (file-size guardrail) so the chain
driver lives in one small, reusable home that steps d/e also call. Owns:

- ``resolve``: find the active SequenceRun containing a project and decide this
  orchestrator's role BY AGENT IDENTITY (conductor iff the calling agent is the
  run's ``conductor_agent_id``). BE-6184: the conductor is a DEDICATED, project-less
  orchestrator minted at run-create, so every project's orchestrator (head included)
  is a symmetric ``sub_orchestrator``. ``conductor_project_id`` is no longer
  stamped (legacy values are read-tolerated). A non-fatal safety fallback stamps
  ``conductor_agent_id`` only when a run somehow lacks one.
- ``advance_index_if_committed`` / ``mark_stalled_if_past_deadline``: the
  advance-precondition + bounded-wait seams the step-d CH_CHAIN_DRIVE prose drives.

``resolve`` returns None for the common solo path (no active run contains the
project) ⇒ the orchestrator protocol renders byte-identical to solo (Deletion
Test holds; all CE). All writes go through SequenceRunService (the owning service).

Edition Scope: CE.
"""

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.models.projects import Project
from giljo_mcp.services.execution_mode_gate import effective_execution_mode
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChainContext:
    """Resolved role of this orchestrator in a sequential multi-project run.

    Produced by SequenceChainContextResolver.resolve and stored on
    ctx["chain_ctx"]. A None chain_ctx means solo project (byte-identical solo
    protocol, Deletion Test holds).
    """

    run_id: str
    role: str  # "conductor" | "sub_orchestrator"
    current_index: int
    resolved_order: list[str]
    is_staging: bool
    conductor_agent_id: str | None
    # BE-6177: the run's chosen execution mode (projects.execution_mode vocabulary,
    # e.g. "claude_code_cli"). The conductor chapters map this to the stage_project
    # short `mode` token and to the correct can_spawn_terminals platform lookup.
    execution_mode: str | None = None
    # BE-6193: the run's live chain mission (sequence_runs.chain_mission, BE-6185).
    # Injected into a sub-orchestrator's runtime protocol so it reads the conductor's
    # cross-project plan live (no stale snapshot). None for solo (no run).
    chain_mission: str | None = None


async def chain_execution_mode_for_project(session: AsyncSession, *, project_id: str, tenant_key: str) -> str | None:
    """Return the ACTIVE run's execution_mode for a chain member, else None (BE-9335).

    The read half of the chain-member mode rule, for the boundaries that resolve a
    project's mode WITHOUT already holding a ChainContext (``spawn_job`` and the
    chain double-spawn reuse path). Callers pair it with
    ``execution_mode_gate.effective_execution_mode``.

    Takes the caller's ``session`` and an explicit ``tenant_key``, which is all
    SequenceRunService needs to scope the read: it consults its db_manager only
    when no session was injected, and its tenant_manager only when tenant_key is
    empty. Neither applies here, so neither is threaded through.

    Best-effort by design, matching the sibling chain lookups: a failure returns
    None so the caller falls back to the project column and a chain-detection
    problem can never break spawning. None is also the common solo answer.
    """
    try:
        svc = SequenceRunService(db_manager=None, tenant_manager=None, session=session)
        run = await svc.find_active_run_for_project(project_id=project_id, tenant_key=tenant_key)
        return run.get("execution_mode") if run else None
    except Exception:  # noqa: BLE001 - best-effort; never break the spawn path
        logger.warning("[BE-9335] chain execution-mode lookup failed (non-fatal); using the project's own mode")
        return None


async def renders_multi_terminal(session: AsyncSession, *, project: Any, project_id: str, tenant_key: str) -> bool:
    """True when a spawned agent's bootstrap is the multi_terminal dashboard pointer.

    BE-9335: for a member of an active chain the CHAIN's mode decides, so a chain
    never hands its members the spawn syntax of whatever mode they happened to be
    staged with individually. Solo (no active run) resolves to the project column,
    so the non-chain bootstrap is unchanged.
    """
    mode = effective_execution_mode(
        getattr(project, "execution_mode", "multi_terminal"),
        await chain_execution_mode_for_project(session, project_id=project_id, tenant_key=tenant_key),
    )
    return (mode or "multi_terminal") == "multi_terminal"


class SequenceChainContextResolver:
    """Resolves chain role + self-registers the conductor. Session-scoped."""

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
        """Yield a session, preferring an injected test session (test isolation)."""
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
        """Find the active sequence run containing this project and resolve role.

        Returns None for solo projects (common path; protocol rendered unchanged).
        Returns a ChainContext for conductor or sub_orchestrator roles.

        BE-6184 (dedicated conductor): role classification is now BY AGENT IDENTITY,
        i.e. ``role == "conductor"`` iff ``orchestrator_agent_id == run.conductor_agent_id``.
        The conductor is a DEDICATED, project-less orchestrator minted at run-create
        (SequenceRunService.create), so EVERY project's orchestrator (including the
        head project's) is now a symmetric ``sub_orchestrator``. ``conductor_project_id``
        is NO LONGER stamped here; it stays NULL going forward.

        Tolerance (no data surgery): an in-flight alpha run may carry
        ``conductor_project_id`` set to the head pid. That legacy value is read-tolerated
        (the conductor still resolves correctly by ``conductor_agent_id``) and is
        never rewritten.

        Self-registration is now a non-fatal SAFETY fallback only: the conductor's
        ``conductor_agent_id`` is stamped at run-create, so a normal resolve() finds it
        already set and writes nothing. If it is somehow NULL (a legacy/out-of-band run),
        and this caller's agent is not contradicting an existing conductor, we stamp it
        best-effort; a write failure NEVER demotes classification (BE-6181 determinism).
        """
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

        # BE-6184: classify by agent identity, not by head-project position.
        role = (
            "conductor"
            if (effective_conductor_agent_id is not None and orchestrator_agent_id == effective_conductor_agent_id)
            else "sub_orchestrator"
        )

        # Non-fatal safety fallback: stamp conductor_agent_id ONLY when the run has
        # none (legacy/out-of-band). A normal run already has it stamped at create,
        # so this no-ops. We do NOT stamp conductor_project_id (it stays NULL).
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
                # Determinism: a write failure must not demote this first-touch agent
                # to sub_orchestrator. It is the conductor-of-record for this resolve;
                # the stamp retries on the next resolve.
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
        """Resolve a ChainContext for a DEDICATED, project-less conductor (BE-6184).

        The dedicated conductor owns no project, so it cannot be found by project_id;
        it is found by its ``conductor_agent_id`` on the active run. Returns a
        ``role="conductor"`` ChainContext, or None when this agent is not the live
        conductor of any active run (the run is found via
        ``find_active_run_for_conductor``, which filters to active statuses, so that
        active-run check IS the run-phase gate for the project-less conductor). No
        write occurs here: the conductor identity was stamped at run-create.
        """
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
        """Fire sequence:updated WS event; failure never breaks instruction delivery.

        Awaited directly (not fire-and-forget): the only caller is the async
        resolve(), and a bare ensure_future task whose reference is dropped can be
        GC'd before it runs ("Task was destroyed but it is pending"), silently
        losing the broadcast. The try/except keeps a WS failure from ever breaking
        instruction delivery.
        """
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
        """Bump current_index to next_index only if project_id has a recorded closeout.

        The commit-SHA signal used here is project.closeout_executed_at IS NOT NULL —
        set by write_project_closeout (the orchestrator's final mandatory step). This
        is the authoritative "work was committed and closed" signal: the closeout tool
        stamps it in the same transaction that writes the memory entry + git_commits.
        Returns True and bumps the index; returns False (no DB write) if not closed out.
        """
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
        """Flip run status to stalled when now > deadline.

        Returns True and updates status; returns False (no write) if not past deadline.
        """
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
