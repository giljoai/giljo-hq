# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Project Closeout MCP Tool (Handover 013B - Refactored)

Handles project completion and updates product memory with sequential history entries.
"""

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
from giljo_mcp.services.project_closeout_service import ProjectCloseoutService
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

# Statuses considered "active" — agents not yet finished (used by the force-close
# orchestrator-self-decommission guard). BE-3010c: the closeout SKIP-status set moved
# to ProjectCloseoutService._CLOSEOUT_SKIP_STATUSES (the unified readiness gathering).
_ACTIVE_STATUSES = {"waiting", "working", "blocked", "silent"}


async def _handle_force_close(
    session: AsyncSession,
    project_id: str,
    tenant_key: str,
    force: bool,
    blockers: list,
    closeout_service: ProjectCloseoutService,
) -> list[AgentStatusChangeEvent]:
    """
    Handle force-close path: guard against orchestrator self-decommission, then decommission agents.

    When force=True and agents are still active, checks that the calling orchestrator
    is not among them (raising ProjectStateError if so), then delegates to
    ProjectCloseoutService.decommission_project_agents to set all remaining active
    agents to 'decommissioned'. Does nothing when force=False or when all agents
    are already ready.

    Args:
        session: Active database session.
        project_id: Project UUID being closed.
        tenant_key: Tenant isolation key.
        force: Whether force-close was requested by the caller.
        blockers: List of blocker dicts from _check_agent_readiness; empty means no action needed.
        closeout_service: ProjectCloseoutService instance for agent status transitions.

    Returns:
        One AgentStatusChangeEvent per decommissioned agent (empty when force=False
        or nothing needed decommissioning). BE-9246: the caller must broadcast these
        POST-COMMIT -- this function only flushes, it never commits.
    """
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

    # BE-9165: a 'waiting' orchestrator with zero in-flight specialists is not a
    # live calling session — it is the auto-created (never staged) or
    # staging-parked row of a project whose work happened outside a staged
    # implementation session. force=true may decommission it, which is exactly
    # what the CLOSEOUT_BLOCKED hint promises. A 'working' orchestrator or any
    # in-flight specialist still trips the self-decommission guard below.
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
                "required_sequence": [
                    f"1. complete_job(job_id='{active_orchestrator.job_id}') -- complete yourself first",
                    "2. write_memory_entry(...) -- write memory entry (if not already written)",
                    "3. write_project_closeout(force=false) -- should now pass since all agents are complete",
                ],
                "hint": "Or use write_memory_entry() + complete_job() and let the frontend handle project archival.",
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
    """Resolve git commits from agent input, or an empty default.

    Validates agent-supplied commits; the server itself is passive and never
    fetches commits from a git host on the agent's behalf (host-agnostic —
    the agent's local git remote may point anywhere).

    When git integration is enabled but the agent supplies no commits, the
    closeout still succeeds — a warning is logged and returned for surfacing
    in the response. This preserves the user's git preference as a strong
    recommendation while letting agents close projects in non-git directories
    after asking the user (per ch5 protocol guidance).

    Wave 1 IMP-0019 Item 5: when the resolved commit list is empty AND the
    agent did not supply commits (the demo-server scenario where `git` is not
    installed and the agent's `git log` subprocess fails), surface a separate
    `git_unavailable_reason` so callers can distinguish "git was not available
    or not collected" from "git was available but produced no commits in
    range." The closeout itself must still succeed.

    Raises:
        GitCommitTitleRequiredError: BE-9256 — a supplied commit entry has no
            title (SHA alone, or empty message/subject). The caller catches
            this and returns the BE-6081 Tier-2 structured rejection.

    Returns:
        (commits, warning, git_unavailable_reason) — commits is always a
        validated list (possibly empty); warning is a human-readable string
        when git was enabled but no commits were provided, otherwise None;
        git_unavailable_reason is a short text marker when the final commit
        list is empty AND no agent-supplied commits arrived (otherwise None).
    """
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

    # Track whether the agent supplied commits — used to detect the
    # git-unavailable case below (empty result + no agent input).
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
        # Demo-server / non-git-repo / git-binary-missing scenario. The agent
        # could not run `git log` (FileNotFoundError on missing binary, or the
        # project directory is not a git repo), so it sent git_commits=None.
        # The closeout succeeds; we just surface the signal so callers know
        # commit history was not collected.
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
    """Validate required closeout args and run the shared INF-WriteShape boundary.

    Returns the normalised ``(summary, key_outcomes, decisions_made, validated_tags)``
    tuple. Raises ``ValidationError`` for missing required args and propagates the
    structured ``MemoryEntryWriteValidationError`` from ``validate_memory_entry_write``
    untouched.
    """
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
    """Allocate sequence number, build params, persist the closeout memory entry.

    Returns ``(entry, sequence_number)``. Session lifecycle stays with the caller.
    """
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
    """Say what actually happened to the PROJECT ROW, not a fixed sentence.

    A chain member's row genuinely IS flipped to a terminal status by
    ``_finalize_chain_member_closeout`` (mirroring the solo archive path), so the
    message may say "closed". A solo project's is deliberately left alone --
    BUG #7 kept that behaviour so the user's Archive press stays meaningful -- so
    claiming it "closed" is false, and it was the false claim that led a caller to
    believe a solo project had been closed when it had not.

    The remedy named is the endpoint the dashboard's Archive button actually calls
    (``archive_project`` in ``api/endpoints/projects/lifecycle.py``), which flips the
    row from any status -- never ``update_project(status=...)``, which is not the
    supported completion path.
    """
    if is_chain_member:
        return "Project closed: this chain member's status was updated and 360 Memory was updated successfully."
    return (
        "360 Memory updated successfully. This project's own status was NOT changed -- "
        "closeout does not complete a solo project; that is left for the Archive action. "
        f"To mark it completed, call POST /api/v1/projects/{project_id}/archive "
        "(the same endpoint the dashboard's Archive button uses)."
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
    """Log success, emit the WebSocket event, and build the response dict."""
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
        # Wave 1 IMP-0019 Item 5: explicit signal when git history was
        # not collected (demo server / non-git repo / git binary
        # missing). Closeout still succeeds; this just tells callers.
        response["git_unavailable"] = True
        response["git_unavailable_reason"] = git_unavailable_reason
    return response


def _build_closeout_blocked_rejection(project_id: str, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    """BE-9016 (Sentry GILJOAI-BACKEND-5) / size-budget extraction: an EXPECTED,
    agent-actionable domain rejection (the caller can resolve the blockers or
    pass force=true), not an internal error -- the BE-6081 Tier-2 structured
    shape, so it reaches the agent as normal content (not isError) and never
    logs as a Sentry error event. Mirrors write_memory_entry's sibling
    CLOSEOUT_BLOCKED gate, which already returns rather than raises.
    """
    return {
        "success": False,
        "error": "CLOSEOUT_BLOCKED",
        "project_id": project_id,
        "blockers": blockers,
        "hint": "Resolve all blockers or pass force=true to auto-decommission remaining agents.",
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
    """
    Close project and update product memory with history entry.

    Adds a rich entry to the product_memory_entries table.

    When force=False (default), verifies all agents are complete before
    proceeding. Returns CLOSEOUT_BLOCKED with blocker details if any agents
    are still active, have unread messages, or have incomplete TODOs.

    When force=True, auto-decommissions any remaining active agents before
    closing, and logs a warning with the affected agents.

    Caps (INF-WriteShape, shared with write_memory_entry):
        summary <= 1500 chars (2-3 sentence headline of what changed and why)
        key_outcomes <= 5 items, each <= 250 chars
        decisions_made <= 5 items, each <= 250 chars
        tags <= 8 items, each from the 16-tag CONTROLLED_TAG_VOCABULARY in
            MemoryEntryWriteSchema. Invalid tags trigger a structured MemoryEntryWriteValidationError
            carrying the offending tag and the full allowed enum.

    Args:
        tags: Orchestrator-supplied controlled-vocabulary tags for the
            closeout entry. Pick 1-3 from the change-type axis
            (feature/bug-fix/refactor/perf/security/docs/test/chore) AND
            1-3 from the domain axis (frontend/backend/database/api/
            infrastructure/ui-ux/integration). Use ``migration`` for schema
            changes. ``None`` or ``[]`` produce an entry with empty tags
            (no auto-extraction from prose).
        git_commits: Agent-supplied commits from local git log (the server is
            passive -- it never fetches commits from a git host itself). Each
            entry must carry a non-empty commit title; a titleless entry is
            rejected with GIT_COMMIT_TITLE_REQUIRED.
        decommission_events_out: BE-9273 out-param, see the assignment below.

    Raises:
        MemoryEntryWriteValidationError: structured rejection when caps are
            exceeded or any supplied tag is outside the controlled vocabulary
            (single shared validator with write_memory_entry).
    """
    # INF-WriteShape: shared validated write boundary (same as write_memory_entry).
    # BE-5032: tags are now an agent-supplied parameter, validated against
    # CONTROLLED_TAG_VOCABULARY here. The previous behaviour word-split the
    # summary into junk tokens; that path is gone.
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

            # BE-9157: refuse closeout writes to a superseded project (Tier-2 domain rejection).
            if (rejection := refuse_if_superseded(project)) is not None:
                return rejection

            # Closeout readiness gate: verify all agents are finished
            is_ready, blockers = await _check_agent_readiness(active_session, project_id, tenant_key)

            if not is_ready and not force:
                return _build_closeout_blocked_rejection(project_id, blockers)

            # Build a lightweight service for agent status transitions
            # (session-in pattern: service methods accept the active session)
            closeout_service = ProjectCloseoutService(
                db_manager=db_manager,
                tenant_manager=TenantManager(),
            )

            # Handover 0824: force-close guard + agent decommission
            decommission_events = await _handle_force_close(
                session=active_session,
                project_id=project_id,
                tenant_key=tenant_key,
                force=force,
                blockers=blockers,
                closeout_service=closeout_service,
            )

            # BE-9273: hand owns_session=False callers the raw events (no broadcast below for them).
            if decommission_events_out is not None:
                decommission_events_out.extend(decommission_events)

            # Handover 0435b: agent 'complete' → 'closed' moved to archive endpoint
            # (user action, not orchestrator MCP call). Agents stay 'complete' here.

            try:
                git_commits, git_warning, git_unavailable_reason = await _resolve_git_commits(
                    session=active_session,
                    project_id=project_id,
                    tenant_key=tenant_key,
                    git_commits=git_commits,
                )
            except GitCommitTitleRequiredError as exc:
                # BE-9256 (Tier-2 domain rejection): a supplied commit has no title.
                # Return the structured dict so it reaches the agent as normal tool
                # content, not isError -- mirrors refuse_if_superseded above.
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

            # BE-6198 / BUG #7: stamp chain-advance signals + finalize a chain-member
            # project row (see helper docstring). Returns the WS manager threaded into
            # the post-commit agent:status_changed emit below, plus whether this project
            # is a chain member (the response message text depends on which case).
            ws, is_chain_member = await _finalize_chain_member_closeout(
                session=active_session,
                project=project,
                project_id=project_id,
                tenant_key=tenant_key,
                db_manager=db_manager,
                websocket_manager=websocket_manager,
            )

            # Session commit handled by db_manager.get_session_async() context manager
            # when owns_session=True; flush already done by repo.create_entry()

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

        # BE-9246 POST-COMMIT emit -- runs only AFTER `async with session_ctx`
        # committed above. owns_session=False passes no events (see the
        # broadcast_agent_status_events docstring for why that path stays silent).
        await broadcast_agent_status_events(
            ws,
            tenant_key=tenant_key,
            project_id=project_id,
            events=decommission_events if owns_session else (),
        )

        return response

    except BaseGiljoError as exc:
        # A domain rejection (<500) is correct behaviour surfaced to the caller, not a
        # server fault — log it at info so it does not register as a Sentry error event
        # (avoids false "billing/closeout error" alerts). Genuine 5xx still go to
        # logger.exception below. The re-raise is unchanged in both cases.
        if exc.default_status_code < 500:
            logger.info("close_project rejected: %s — %s", exc.error_code, exc.message)
            raise
        logger.exception("Failed to close project and update memory", extra={"error": str(exc)})
        raise
    except Exception as exc:  # Broad catch: tool boundary, logs and re-raises
        logger.exception("Failed to close project and update memory", extra={"error": str(exc)})
        raise


async def _check_agent_readiness(
    session: AsyncSession,
    project_id: str,
    tenant_key: str,
) -> tuple[bool, list[dict[str, Any]]]:
    """
    Check whether all agents in the project are ready for closeout.

    Returns (is_ready, blockers) where blockers is a list of dicts
    describing each non-complete agent with issue_type, todo details,
    suggested_action, and a trailing summary entry.

    BE-3010c: the readiness GATHERING is unified in
    ``ProjectCloseoutService.evaluate_closeout_readiness`` (the one source of
    truth shared with ``write_360_memory`` and ``can_close``). This function now
    only SHAPES that report into the merged-per-agent blocker list + trailing
    ``_summary`` the closeout gate expects — output is unchanged.
    """
    closeout_service = ProjectCloseoutService(None, TenantManager())
    report = await closeout_service.evaluate_closeout_readiness(session, project_id, tenant_key)

    blockers: list[dict[str, Any]] = []
    summary = {
        "agents_checked": report.agents_checked,
        "still_working": 0,
        "with_unread_messages": 0,
        "with_incomplete_todos": 0,
        "awaiting_user_approval": 0,
    }

    for finding in report.findings:
        if finding.status == "complete":
            continue

        if finding.awaiting_user:
            blockers.append(
                {
                    "agent_id": finding.agent_id,
                    "agent_name": finding.agent_name,
                    "status": "awaiting_user",
                    "job_id": finding.job_id,
                    "issue_type": "awaiting_user_approval",
                    "approval_id": finding.approval_id,
                    "suggested_action": (
                        f"Resolve approval {finding.approval_id} via POST /api/approvals/{finding.approval_id}/decide."
                    ),
                }
            )
            summary["awaiting_user_approval"] += 1
            continue

        summary["still_working"] += 1
        messages_waiting = finding.messages_waiting
        if messages_waiting > 0:
            summary["with_unread_messages"] += 1

        incomplete_count = len(finding.incomplete_todos)
        incomplete_names = finding.incomplete_todos[:5]
        if incomplete_count > 0:
            summary["with_incomplete_todos"] += 1

        # Build suggested_action with all relevant remediation steps
        steps = []
        if messages_waiting > 0:
            steps.append(
                f"Drain {messages_waiting} unread messages via get_thread_history(as_participant='{finding.agent_id}')"
            )
        if incomplete_count > 0:
            steps.append(
                f"Update {incomplete_count} incomplete TODOs via "
                f"report_progress(job_id='{finding.job_id}', todo_items=[...]) "
                f"marking as completed/skipped"
            )
        steps.append(f"Force-complete via complete_job(job_id='{finding.job_id}')")
        suggested_action = ". ".join(steps) + "."

        blockers.append(
            {
                "agent_id": finding.agent_id,
                "agent_name": finding.agent_name,
                "status": finding.status,
                "job_id": finding.job_id,
                "issue_type": "still_working",
                "messages_waiting": messages_waiting,
                "incomplete_todo_count": incomplete_count,
                "incomplete_todo_names": incomplete_names,
                "suggested_action": suggested_action,
            }
        )

    if blockers:
        blockers.append({"_summary": summary})

    return (len(blockers) == 0, blockers)


async def _force_decommission_agents(
    session: AsyncSession,
    project_id: str,
    tenant_key: str,
) -> list[str]:
    """
    Decommission all active agents for project closeout.

    Delegates to ProjectCloseoutService.decommission_project_agents (session-in pattern).
    Returns list of agent display names that were decommissioned.
    """
    # Session-in methods don't use db_manager or tenant_manager; safe to pass None
    svc = ProjectCloseoutService(
        db_manager=None,  # type: ignore[arg-type]
        tenant_manager=TenantManager(),
    )
    decommissioned_names, _status_events = await svc.decommission_project_agents(
        session=session, project_id=project_id, tenant_key=tenant_key
    )
    return decommissioned_names
