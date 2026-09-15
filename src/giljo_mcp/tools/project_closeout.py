# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import BaseGiljoError, ProjectStateError, ValidationError
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.schemas.jsonb_validators import GitCommitTitleRequiredError, validate_git_commits
from giljo_mcp.schemas.service_responses import AgentStatusChangeEvent
from giljo_mcp.services.closeout_ws_broadcast import broadcast_agent_status_events
from giljo_mcp.services.dto import MemoryEntryCreateParams
from giljo_mcp.services.product_memory_service import (
    ProductMemoryService,
    validate_memory_entry_write,
)
from giljo_mcp.services.project_closeout_readiness import shape_readiness_blockers
from giljo_mcp.services.project_closeout_service import ProjectCloseoutService
from giljo_mcp.services.protocol_sections.closeout_sequence import build_required_sequence
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools._closeout_finalize import _finalize_chain_member_closeout
from giljo_mcp.tools._closeout_metrics import (
    build_metrics,
    calculate_significance,
    derive_priority,
    estimate_tokens,
)
from giljo_mcp.tools._memory_helpers import (
    _fetch_project_and_product,
    build_git_commit_title_required_rejection,
    emit_websocket_event,
    provided_session,
    refuse_if_superseded,
)
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = {"waiting", "working", "blocked", "silent"}


async def _handle_force_close(
    session: AsyncSession,
    project_id: str,
    tenant_key: str,
    force: bool,
    blockers: list,
    closeout_service: ProjectCloseoutService,
) -> list[AgentStatusChangeEvent]:
    if not blockers or not force:
        return []

    orch_stmt = (
        select(AgentExecution)
        .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
        .where(
            and_(
                AgentJob.project_id == project_id,
                AgentExecution.tenant_key == tenant_key,
                AgentExecution.agent_display_name == "orchestrator",
                AgentExecution.status.in_(_ACTIVE_STATUSES),
            )
        )
    )
    orch_result = await session.execute(orch_stmt)
    active_orchestrator = orch_result.scalar_one_or_none()

    orchestrator_is_idle_leftover = False
    if active_orchestrator is not None and active_orchestrator.status == "waiting":
        from giljo_mcp.repositories.mission_repository import MissionRepository

        _total, in_flight = await MissionRepository().count_non_orchestrator_agents_by_liveness(
            session, tenant_key, project_id
        )
        orchestrator_is_idle_leftover = in_flight == 0

    if active_orchestrator and not orchestrator_is_idle_leftover:
        raise ProjectStateError(
            "Cannot force-close: orchestrator is still active and would be decommissioned",
            context={
                "status": "ORCHESTRATOR_SELF_DECOMMISSION_BLOCKED",
                "message": (
                    "force=true will decommission ALL active agents including the orchestrator. "
                    "Complete your own job first, then the project will close cleanly."
                ),
                "required_sequence": build_required_sequence(active_orchestrator.job_id),
                "hint": (
                    "write_memory_entry() does not stamp the closeout record archiving requires -- "
                    "only write_project_closeout() does. Complete your own job first, then "
                    "write_project_closeout(); a solo project is then archived with "
                    "update_project(status='completed') from here, or from the dashboard."
                ),
            },
        )

    decommissioned, status_events = await closeout_service.decommission_project_agents(
        session=session, project_id=project_id, tenant_key=tenant_key
    )
    if decommissioned:
        logger.warning(
            "Force-closed project %s: auto-decommissioned %d agent(s): %s",
            sanitize(project_id),
            len(decommissioned),
            ", ".join(decommissioned),
        )
    return status_events


async def _resolve_git_commits(
    *,
    session: AsyncSession,
    project_id: str,
    tenant_key: str,
    git_commits: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], str | None, str | None]:
    git_integration_enabled = False
    try:
        from giljo_mcp.services.settings_service import SettingsService

        settings_svc = SettingsService(session, tenant_key)
        git_settings = await settings_svc.get_setting_value("integrations", "git_integration", {})
        git_integration_enabled = git_settings.get("enabled", False)
    except Exception as _exc:
        logger.debug("Settings read skipped: %s", _exc)

    git_warning: str | None = None
    if git_integration_enabled and not git_commits:
        git_warning = (
            "Git integration is enabled in user settings, but no commits were provided "
            "for this closeout. Project closed without commit history. If the project "
            "directory is a git repo, the agent should have committed and passed git_commits; "
            "if not a git repo, ask the user whether to git init future projects."
        )
        logger.warning(
            "git_commits_missing_with_integration_enabled project_id=%s tenant_key=%s",
            sanitize(project_id),
            tenant_key,
        )

    agent_supplied_commits = git_commits is not None

    if git_commits is not None:
        git_commits = validate_git_commits(git_commits)
        logger.info(
            "Using %d agent-supplied git commits for project %s",
            len(git_commits),
            sanitize(project_id),
        )
    else:
        git_commits = []
        logger.info(
            "No agent-supplied git commits for project %s (server is passive)",
            sanitize(project_id),
        )

    git_unavailable_reason: str | None = None
    if not git_commits and not agent_supplied_commits:
        git_unavailable_reason = "git not available — no agent-supplied commits. Project closed without commit history."
        logger.info(
            "git_unavailable_in_closeout project_id=%s tenant_key=%s",
            sanitize(project_id),
            tenant_key,
        )

    return git_commits, git_warning, git_unavailable_reason


def _validate_closeout_inputs(
    *,
    project_id: str,
    summary: str,
    key_outcomes: list[str] | None,
    decisions_made: list[str] | None,
    tags: list[str] | None,
    db_manager: DatabaseManager | None,
) -> tuple[str, list[str], list[str], list[str]]:
    if not project_id:
        raise ValidationError("project_id is required")

    if not summary or not summary.strip():
        raise ValidationError("summary is required")

    if db_manager is None:
        raise ValidationError("db_manager is required")

    key_outcomes = key_outcomes or []
    decisions_made = decisions_made or []

    validated = validate_memory_entry_write(
        {
            "summary": summary,
            "key_outcomes": key_outcomes,
            "decisions_made": decisions_made,
            "tags": tags or [],
        }
    )
    return (
        validated.summary,
        validated.key_outcomes,
        validated.decisions_made,
        validated.tags,
    )


async def _build_and_persist_memory_entry(
    session: AsyncSession,
    *,
    product: Any,
    project: Any,
    tenant_key: str,
    summary: str,
    key_outcomes: list[str],
    decisions_made: list[str],
    validated_tags: list[str],
    git_commits: list[dict[str, Any]],
    db_manager: DatabaseManager,
) -> tuple[Any, int]:
    memory_service = ProductMemoryService(
        db_manager=db_manager,
        tenant_key=tenant_key,
    )
    sequence_number = await memory_service.get_next_sequence(
        product_id=product.id,
        session=session,
    )

    priority = derive_priority(project, summary, key_outcomes)
    significance_score = calculate_significance(project, key_outcomes, git_commits)
    token_estimate = estimate_tokens(summary, key_outcomes, decisions_made)
    metrics = build_metrics(git_commits)

    params = MemoryEntryCreateParams(
        tenant_key=tenant_key,
        product_id=product.id,
        project_id=project.id,
        sequence=sequence_number,
        entry_type="project_closeout",
        source="closeout_v1",
        timestamp=datetime.now(UTC),
        project_name=project.name,
        summary=summary,
        key_outcomes=key_outcomes,
        decisions_made=decisions_made,
        git_commits=git_commits,
        metrics=metrics,
        priority=priority,
        significance_score=significance_score,
        token_estimate=token_estimate,
        tags=validated_tags,
    )
    entry = await memory_service.create_entry(
        params=params,
        session=session,
    )
    return entry, sequence_number


def _build_closeout_message(*, project_id: str, is_chain_member: bool) -> str:
    if is_chain_member:
        return "Project closed: this chain member's status was updated and 360 Memory was updated successfully."
    return (
        "360 Memory updated successfully. This project's own status was NOT changed -- "
        "closeout does not complete a solo project. "
        f"To complete it, call update_project(project_id='{project_id}', status='completed'), "
        "which runs the full archive lifecycle (the same one the dashboard's Archive button uses): "
        "it deactivates the project, stamps the completion date, and closes any spawned agents "
        "still sitting at 'complete'."
    )


async def _finalize_closeout_response(
    entry: Any,
    sequence_number: int,
    git_commits: list[dict[str, Any]],
    git_warning: str | None,
    git_unavailable_reason: str | None,
    tenant_key: str,
    product_id: Any,
    project_id: str,
    is_chain_member: bool,
) -> dict[str, Any]:
    logger.info(
        f"Updated 360 Memory for product {product_id} "
        f"(entry: {entry.id}, sequence: {sequence_number}, commits: {len(git_commits) if git_commits else 0})"
    )

    await emit_websocket_event(
        event_type="product:memory:updated",
        tenant_key=tenant_key,
        product_id=str(product_id),
        data={"entry": entry.to_dict()},
    )

    response: dict[str, Any] = {
        "entry_id": str(entry.id),
        "sequence_number": sequence_number,
        "git_commits_count": len(git_commits),
        "message": _build_closeout_message(project_id=project_id, is_chain_member=is_chain_member),
    }
    if git_warning:
        response["git_warning"] = git_warning
    if git_unavailable_reason:
        response["git_unavailable"] = True
        response["git_unavailable_reason"] = git_unavailable_reason
    return response


def _build_closeout_blocked_rejection(project_id: str, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "success": False,
        "error": "CLOSEOUT_BLOCKED",
        "project_id": project_id,
        "blockers": blockers,
        "hint": (
            "Resolve the blockers above, then retry. If an agent stalled but you ACCEPTED its "
            "work, complete_job(job_id, result={...}) then finalize_job(job_id) -- that reaches "
            "closed from any state. force=true is the deliberate ABANDON path: it decommissions "
            "remaining agents, recording their work as failed. Do not use it to retire work you "
            "accepted."
        ),
    }


async def close_project_and_update_memory(
    project_id: str,
    summary: str,
    key_outcomes: list[str],
    decisions_made: list[str],
    *,
    tags: list[str] | None = None,
    tenant_key: str,
    db_manager: DatabaseManager | None = None,
    session: AsyncSession | None = None,
    force: bool = False,
    git_commits: list[dict[str, Any]] | None = None,
    websocket_manager: Any | None = None,
    decommission_events_out: list[AgentStatusChangeEvent] | None = None,
) -> dict[str, Any]:
    summary, key_outcomes, decisions_made, validated_tags = _validate_closeout_inputs(
        project_id=project_id,
        summary=summary,
        key_outcomes=key_outcomes,
        decisions_made=decisions_made,
        tags=tags,
        db_manager=db_manager,
    )

    try:
        owns_session = session is None
        session_ctx = db_manager.get_session_async() if owns_session else provided_session(session)

        async with session_ctx as active_session:
            project, product = await _fetch_project_and_product(
                session=active_session,
                project_id=project_id,
                tenant_key=tenant_key,
            )

            if (rejection := refuse_if_superseded(project)) is not None:
                return rejection

            is_ready, blockers = await _check_agent_readiness(active_session, project_id, tenant_key)

            if not is_ready and not force:
                return _build_closeout_blocked_rejection(project_id, blockers)

            closeout_service = ProjectCloseoutService(
                db_manager=db_manager,
                tenant_manager=TenantManager(),
            )

            decommission_events = await _handle_force_close(
                session=active_session,
                project_id=project_id,
                tenant_key=tenant_key,
                force=force,
                blockers=blockers,
                closeout_service=closeout_service,
            )

            if decommission_events_out is not None:
                decommission_events_out.extend(decommission_events)


            repeat = await _idempotent_closeout_response(
                active_session, project_id, tenant_key, summary, key_outcomes, decisions_made, db_manager
            )
            if repeat is not None:
                return repeat

            try:
                git_commits, git_warning, git_unavailable_reason = await _resolve_git_commits(
                    session=active_session,
                    project_id=project_id,
                    tenant_key=tenant_key,
                    git_commits=git_commits,
                )
            except GitCommitTitleRequiredError as exc:
                return build_git_commit_title_required_rejection(exc, project_id)

            entry, sequence_number = await _build_and_persist_memory_entry(
                active_session,
                product=product,
                project=project,
                tenant_key=tenant_key,
                summary=summary,
                key_outcomes=key_outcomes,
                decisions_made=decisions_made,
                validated_tags=validated_tags,
                git_commits=git_commits,
                db_manager=db_manager,
            )

            ws, is_chain_member = await _finalize_chain_member_closeout(
                session=active_session,
                project=project,
                project_id=project_id,
                tenant_key=tenant_key,
                db_manager=db_manager,
                websocket_manager=websocket_manager,
            )


            response = await _finalize_closeout_response(
                entry=entry,
                sequence_number=sequence_number,
                git_commits=git_commits,
                git_warning=git_warning,
                git_unavailable_reason=git_unavailable_reason,
                tenant_key=tenant_key,
                product_id=product.id,
                project_id=project_id,
                is_chain_member=is_chain_member,
            )

        await broadcast_agent_status_events(
            ws,
            tenant_key=tenant_key,
            project_id=project_id,
            product_id=str(product.id),
            events=decommission_events if owns_session else (),
        )

        return response

    except BaseGiljoError as exc:
        if exc.default_status_code < 500:
            logger.info("close_project rejected: %s — %s", exc.error_code, exc.message)
            raise
        logger.exception("Failed to close project and update memory", extra={"error": str(exc)})
        raise
    except Exception as exc:
        logger.exception("Failed to close project and update memory", extra={"error": str(exc)})
        raise


async def _idempotent_closeout_response(
    session: AsyncSession,
    project_id: str,
    tenant_key: str,
    summary: str,
    key_outcomes: list[str],
    decisions_made: list[str],
    db_manager: DatabaseManager,
) -> dict[str, Any] | None:
    memory_service = ProductMemoryService(db_manager=db_manager, tenant_key=tenant_key)
    existing = await memory_service.get_closeout_entry_for_project(project_id, session=session)
    if existing is None:
        return None
    same_payload = (
        (existing.summary or "") == summary
        and list(existing.key_outcomes or []) == list(key_outcomes)
        and list(existing.decisions_made or []) == list(decisions_made)
    )
    if not same_payload:
        return None
    logger.info("close_project idempotent: project %s already has closeout entry %s", sanitize(project_id), existing.id)
    return _build_idempotent_closeout_response(existing, project_id=project_id)


def _build_idempotent_closeout_response(entry: Any, *, project_id: str) -> dict[str, Any]:
    commits = entry.git_commits or []
    return {
        "success": True,
        "idempotent": True,
        "entry_id": str(entry.id),
        "sequence_number": entry.sequence,
        "git_commits_count": len(commits),
        "message": (
            f"Project {project_id} already has its closeout entry (sequence {entry.sequence}); "
            "nothing was written. The recorded summary/outcomes/decisions are kept as first written."
        ),
    }


async def _check_agent_readiness(
    session: AsyncSession,
    project_id: str,
    tenant_key: str,
) -> tuple[bool, list[dict[str, Any]]]:
    closeout_service = ProjectCloseoutService(None, TenantManager())
    report = await closeout_service.evaluate_closeout_readiness(session, project_id, tenant_key)
    blockers = shape_readiness_blockers(report)
    return (len(blockers) == 0, blockers)


async def _force_decommission_agents(
    session: AsyncSession,
    project_id: str,
    tenant_key: str,
) -> list[str]:
    svc = ProjectCloseoutService(
        db_manager=None,  # type: ignore[arg-type]
        tenant_manager=TenantManager(),
    )
    decommissioned_names, _status_events = await svc.decommission_project_agents(
        session=session, project_id=project_id, tenant_key=tenant_key
    )
    return decommissioned_names
