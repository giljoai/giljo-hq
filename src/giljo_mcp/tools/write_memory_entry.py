# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Write 360 Memory Tool (Handover 0412, updated 0390c, 0431)

Allows agents to write 360 memory entries during handovers or project completion.
Similar to write_project_closeout but more flexible for agent usage.

Phase 2 (0390c): Updated to write to product_memory_entries table instead of JSONB array.

Handover 0431: Added pre-closeout verification protocol.
- Blocks closeout when agents have unfinished work
- Checks: status, unread messages, incomplete todos
- Returns CLOSEOUT_BLOCKED with actionable blocker details
"""

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.agent_identity import AgentExecution
from giljo_mcp.repositories.agent_completion_repository import AgentCompletionRepository
from giljo_mcp.schemas.jsonb_validators import GitCommitTitleRequiredError, validate_git_commits
from giljo_mcp.services.dto import MemoryEntryCreateParams
from giljo_mcp.services.product_memory_service import (
    ProductMemoryService,
    validate_memory_entry_write,
)
from giljo_mcp.services.project_closeout_service import ProjectCloseoutService
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools._memory_helpers import (
    _fetch_project_and_product as _resolve_project_and_product,
)
from giljo_mcp.tools._memory_helpers import (
    build_git_commit_title_required_rejection,
    emit_websocket_event,
    provided_session,
    refuse_if_superseded,
)
from giljo_mcp.tools._prelaunch_workproduct_detector import check_and_emit_prelaunch_workproduct


logger = logging.getLogger(__name__)

# BE-5028 Fix B: Per-entry-type authorization matrix.
# Workers may only write background/discovery-style entries when explicitly
# assigned. Closeout-shaped entries (project_completion, session_handover)
# are ORCHESTRATOR-ONLY because they document team-wide state that only the
# orchestrator can attest to.
WORKER_ALLOWED_ENTRY_TYPES = frozenset({"baseline", "decision", "architecture", "discovery"})
ORCHESTRATOR_ONLY_ENTRY_TYPES = frozenset({"project_completion", "session_handover"})

# BE-6211d (C-3.2): entry types that represent a closeout call. Only on these does
# the broader CLOSEOUT_INTENT_PATTERN apply (mirroring complete_job's is_closeout_phase),
# so a closeout-intent TODO is auto-acked only when this write IS the closeout.
CLOSEOUT_FAMILY_ENTRY_TYPES = frozenset({"project_completion", "handover_closeout"})


async def _ack_closeout_todos(
    session: AsyncSession,
    tenant_key: str,
    author_job_id: str,
    *,
    apply_intent_pattern: bool = False,
    apply_chain_drive_pattern: bool = False,
) -> int:
    """Auto-complete the author's self-referential closeout TODOs (BE-6208a).

    Mirrors the SAME bypass complete_job uses (job_completion_service): any
    incomplete TODO on ``author_job_id`` whose content matches
    ``CLOSEOUT_TODO_PATTERN`` (e.g. "Closeout the project", "self-complete") is
    marked completed BEFORE the closeout-readiness gate evaluates, resolving the
    chicken-and-egg where the conductor's own series-summary TODO blocks the
    write_memory_entry that satisfies it. Non-closeout TODOs are untouched and
    still block. Returns the number of TODOs auto-completed.

    BE-6211d (C-3.2): on the GENUINE closeout call (``apply_intent_pattern``), also
    apply the BROADER ``CLOSEOUT_INTENT_PATTERN`` that complete_job uses on its own
    closeout-phase path — so write_memory_entry and complete_job auto-ack identically
    (e.g. the conductor's real TODO "Write series summary on head project + complete
    conductor job", which the narrow pattern misses). The broad matcher still targets
    closeout-INTENT wording only, never generic remaining work ("Fix the failing test").
    """
    # BE-9012b: the three closeout/chain-drive patterns relocated to domain.todo_kinds
    # (the completion gate now reads a structural marker; this write_memory closeout
    # gate is a sibling mechanism outside the §6 contract and keeps matching by regex).
    from giljo_mcp.domain.todo_kinds import (
        CHAIN_DRIVE_TODO_PATTERN,
        CLOSEOUT_INTENT_PATTERN,
        CLOSEOUT_TODO_PATTERN,
    )

    def _is_self_closeout_todo(content: str) -> bool:
        if CLOSEOUT_TODO_PATTERN.search(content):
            return True
        if apply_intent_pattern and CLOSEOUT_INTENT_PATTERN.search(content):
            return True
        # BE-6212: the project-less chain conductor's drive TODOs (poll/advance/finale),
        # gated by the caller to the conductor only so solo/sub-orch are unchanged.
        return bool(apply_chain_drive_pattern and CHAIN_DRIVE_TODO_PATTERN.search(content))

    repo = AgentCompletionRepository()
    incomplete = await repo.get_incomplete_todos(session, tenant_key, author_job_id)
    matched = [t for t in incomplete if _is_self_closeout_todo(t.content or "")]
    if matched:
        now = datetime.now(UTC)
        for todo in matched:
            todo.status = "completed"
            todo.updated_at = now
        await session.flush()
        logger.info(
            "Auto-completed %d closeout TODO(s) on acknowledged write_memory_entry for job %s",
            len(matched),
            author_job_id,
        )
    return len(matched)


async def _resolve_author_info(
    session: AsyncSession,
    author_job_id: str | None,
    tenant_key: str,
) -> dict[str, Any]:
    """
    Resolve the display name and job type for the agent writing the entry.

    Queries the most-recent AgentExecution for author_job_id, filtered by
    tenant_key. Returns a dict with ``author_name`` and ``author_type`` keys,
    or an empty dict when no author_job_id is provided.
    """
    if not author_job_id:
        return {}

    execution_stmt = (
        select(AgentExecution)
        .options(joinedload(AgentExecution.job))
        .where(
            AgentExecution.job_id == author_job_id,
            AgentExecution.tenant_key == tenant_key,
        )
        .order_by(AgentExecution.started_at.desc())
        .limit(1)
    )
    execution_result = await session.execute(execution_stmt)
    execution = execution_result.scalar_one_or_none()

    if not execution:
        return {"author_name": None, "author_type": None}

    return {
        "author_name": execution.agent_name or execution.agent_display_name,
        "author_type": execution.job.job_type if execution.job else None,
    }


async def _resolve_tenant_user_id(
    session: AsyncSession,
    tenant_key: str,
) -> str | None:
    """Resolve the primary active user_id for a tenant.

    Used by the staleness check when no explicit user_id is supplied by the
    caller. CE solo deployments have a single user per tenant; SaaS callers
    should pass user_id explicitly.
    """
    from giljo_mcp.models.auth import User

    stmt = select(User.id).where(User.tenant_key == tenant_key, User.is_active).limit(1)
    result = await session.execute(stmt)
    user_id = result.scalar_one_or_none()
    return str(user_id) if user_id else None


async def _check_and_emit_tuning_staleness(
    db_manager: DatabaseManager,
    tenant_key: str,
    product: Any,
    user_id: str | None = None,
    websocket_manager: Any = None,
) -> None:
    """
    Check whether the product's context tuning is stale and notify via WebSocket.

    Performs a lightweight integer comparison via ProductTuningService. Emits
    a ``notification:new`` WebSocket event when the product is due for a
    context review. Errors are caught and logged at DEBUG level so they never
    interrupt the calling flow.

    IMP-5037 bug 2 fix: ``user_id`` must be a real user UUID for the
    notification-preferences lookup to succeed. When None, falls back to the
    primary active user for the tenant (CE solo deployments).
    """
    try:
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        if not user_id:
            async with db_manager.get_session_async() as session:
                user_id = await _resolve_tenant_user_id(session, tenant_key)

        if not user_id:
            logger.debug("Tuning staleness check skipped: no active user for tenant %s", tenant_key)
            return

        tuning_service = ProductTuningService(
            db_manager=db_manager,
            tenant_key=tenant_key,
        )
        staleness = await tuning_service.check_tuning_staleness(
            product_id=str(product.id),
            user_id=user_id,
        )
        if staleness.get("is_stale"):
            await emit_websocket_event(
                event_type="notification:new",
                tenant_key=tenant_key,
                product_id=str(product.id),
                data={
                    "type": "context_tuning",
                    "title": "Context Review Suggested",
                    "message": (
                        f"{staleness['projects_since_tune']} projects completed since your last "
                        f"context review. Tune your product context?"
                    ),
                    "severity": "info",
                    "metadata": {"product_id": str(product.id), "product_name": product.name},
                },
            )
    except (RuntimeError, ValueError, KeyError, OSError, TypeError) as staleness_err:
        logger.debug(f"Tuning staleness check skipped: {staleness_err}")


async def _check_closeout_readiness(
    session: AsyncSession,
    project_id: str,
    tenant_key: str,
    orchestrator_job_id: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    """
    Verify all agents are ready for project closeout (Handover 0431).

    Checks:
    1. All agents have status == 'complete' (excluding orchestrator, decommissioned, cancelled)
    2. All agents have zero unread action-required messages (TSK-9268: the live
       ack-based count the mark_read drain writes, not the denormalized
       messages_waiting_count column)
    3. All agents have all AgentTodoItem.status == 'completed'
    4. Orchestrator's own todos are completed (if orchestrator_job_id provided)

    Args:
        session: Active database session
        project_id: Project UUID being closed
        tenant_key: Tenant isolation key
        orchestrator_job_id: Job ID of orchestrator calling closeout (for todo check)

    Returns:
        Tuple of (is_ready, result_data) where:
        - is_ready: True if all checks pass, False if blockers found
        - result_data: Contains blockers list and summary if blocked,
                       or verified dict if ready

    BE-3010c: the readiness GATHERING is unified in
    ``ProjectCloseoutService.evaluate_closeout_readiness`` (shared with
    ``close_project_and_update_memory`` and ``can_close``). This function now only
    SHAPES that report into the per-issue blocker envelope — output unchanged.
    """
    closeout_service = ProjectCloseoutService(None, TenantManager())
    report = await closeout_service.evaluate_closeout_readiness(
        session, project_id, tenant_key, orchestrator_job_id=orchestrator_job_id
    )

    blockers: list[dict[str, Any]] = []
    summary = {
        "agents_checked": report.agents_checked,
        "still_working": 0,
        "agents_with_unread": 0,
        "agents_with_incomplete_todos": 0,
        "orchestrator_incomplete_todos": 0,
    }

    for finding in report.findings:
        # TSK-9268: unread is tallied for EVERY finding so the summary (and the
        # post-write "verified.all_messages_read" derived from it) tells the
        # truth even while agents are still working. Blocker EMISSION below is
        # unchanged: a non-complete agent still surfaces as one still_working
        # blocker (whose suggested_action already includes draining).
        if finding.messages_waiting > 0:
            summary["agents_with_unread"] += 1

        # Check 1: Agent status must be 'complete'
        if finding.status != "complete":
            summary["still_working"] += 1
            blockers.append(
                {
                    "job_id": finding.job_id,
                    "agent_id": finding.agent_id,
                    "agent_name": finding.agent_name,
                    "issue_type": "still_working",
                    "status": finding.status,
                    "suggested_action": (
                        f"Post to the agent's coordination thread asking for status, or drain "
                        f"messages via get_thread_history(as_participant='{finding.agent_id}') "
                        f"and force-complete via complete_job(job_id='{finding.job_id}')"
                    ),
                }
            )
            continue  # Don't check further issues for this agent

        # Check 2: No unread messages (tallied above; blocker emitted here)
        if finding.messages_waiting > 0:
            blockers.append(
                {
                    "job_id": finding.job_id,
                    "agent_id": finding.agent_id,
                    "agent_name": finding.agent_name,
                    "issue_type": "unread_messages",
                    "messages_waiting": finding.messages_waiting,
                    "suggested_action": (
                        f"Agent has {finding.messages_waiting} unread messages. "
                        f"Drain via get_thread_history(as_participant='{finding.agent_id}'), "
                        f"process, then complete_job(job_id='{finding.job_id}')"
                    ),
                }
            )

        # Check 3: All todos completed
        if finding.incomplete_todos:
            summary["agents_with_incomplete_todos"] += 1
            incomplete_names = finding.incomplete_todos
            blockers.append(
                {
                    "job_id": finding.job_id,
                    "agent_id": finding.agent_id,
                    "agent_name": finding.agent_name,
                    "issue_type": "incomplete_todos",
                    "pending_count": finding.incomplete_pending,
                    "in_progress_count": finding.incomplete_in_progress,
                    "incomplete_items": incomplete_names,
                    "suggested_action": (
                        f"Agent has {len(incomplete_names)} incomplete TODO items: "
                        f"{incomplete_names[:5]}. Update via "
                        f"report_progress(job_id='{finding.job_id}', todo_items=[...]) "
                        f"marking as completed, then complete_job(job_id='{finding.job_id}')"
                    ),
                }
            )

    # Check 4: Orchestrator's own todos (if orchestrator_job_id provided)
    if report.orchestrator_incomplete:
        orch_incomplete_names = report.orchestrator_incomplete
        summary["orchestrator_incomplete_todos"] = len(orch_incomplete_names)
        blockers.append(
            {
                "job_id": orchestrator_job_id,
                "issue_type": "orchestrator_incomplete_todos",
                "pending_count": report.orchestrator_pending,
                "in_progress_count": report.orchestrator_in_progress,
                "incomplete_items": orch_incomplete_names,
                "suggested_action": (
                    f"Orchestrator has {len(orch_incomplete_names)} incomplete TODO items: "
                    f"{orch_incomplete_names[:5]}. Update via "
                    f"report_progress(job_id='{orchestrator_job_id}', todo_items=[...]) "
                    f"marking as completed"
                ),
            }
        )

    # Return results
    if blockers:
        return False, {
            "blockers": blockers,
            "summary": summary,
            "message": f"Closeout blocked: {len(blockers)} unresolved blocker(s) found",
            "next_steps": "Resolve all blockers before closeout. Use set_agent_status(status='blocked') if unable to resolve.",
        }

    return True, {
        "verified": {
            "all_complete": True,
            "all_messages_read": True,
            "all_todos_done": True,
            "agents_checked": summary["agents_checked"],
        }
    }


def _derive_verified(verification_result: dict[str, Any]) -> dict[str, Any]:
    """Truthful post-write "verified" block (TSK-9268).

    When blockers exist (ungated entry types like ``session_handover`` still
    write), the readiness envelope carries no ``verified`` key. The former
    hardcoded all-True fallback made this verifier contradict the
    project_completion gate on the identical state (the live 2026-07-22
    "all_messages_read=true while CLOSEOUT_BLOCKED said 3 unread" wedge).
    Derive the truth from the readiness summary instead.
    """
    if "verified" in verification_result:
        return verification_result["verified"]
    check_summary = verification_result.get("summary", {})
    return {
        "all_complete": check_summary.get("still_working", 0) == 0,
        "all_messages_read": check_summary.get("agents_with_unread", 0) == 0,
        "all_todos_done": (
            check_summary.get("agents_with_incomplete_todos", 0) == 0
            and check_summary.get("orchestrator_incomplete_todos", 0) == 0
        ),
        "agents_checked": check_summary.get("agents_checked", 0),
    }


async def write_360_memory(
    project_id: str,
    tenant_key: str,
    summary: str,
    key_outcomes: list[str],
    decisions_made: list[str],
    entry_type: str = "project_completion",
    author_job_id: str | None = None,
    git_commits: list[dict[str, Any]] | None = None,
    tags: list[str] | None = None,
    user_id: str | None = None,
    acknowledge_closeout_todo: bool = False,
    db_manager: DatabaseManager | None = None,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    """
    Write a 360 memory entry for project completion or handover.

    This tool allows agents to create entries in the product_memory_entries table
    during handovers or at project completion.

    Args:
        project_id: UUID of the project
        tenant_key: Tenant isolation key
        summary: 2-3 sentence HEADLINE of what changed and why -- max 1500 chars.
            Detail belongs in commit messages, not here.
        key_outcomes: <= 5 specific achievements, each <= 250 chars.
        decisions_made: <= 5 architectural/design decisions, each <= 250 chars.
        entry_type: Type of entry. Workers may write ``baseline``, ``decision``,
            ``architecture``, ``discovery``. Orchestrator-only types (rejected
            with ``ORCHESTRATOR_ONLY_ENTRY_TYPE`` for workers): ``project_completion``,
            ``session_handover``. ``handover_closeout`` is preserved for back-compat.
        author_job_id: Job ID of agent writing entry (optional)
        git_commits: Agent-supplied commits from local git log (the server is
            passive -- it never fetches commits from a git host itself). Each
            entry must carry a non-empty commit title; a titleless entry is
            rejected with GIT_COMMIT_TITLE_REQUIRED.
        tags: <= 8 tags, each <= 30 chars matching ``^[a-z0-9-]+$``.
        acknowledge_closeout_todo: When True, auto-complete the author's own
            self-referential closeout TODOs (matching CLOSEOUT_TODO_PATTERN)
            before the closeout-readiness gate evaluates -- the SAME bypass
            complete_job uses. Resolves the conductor's series-summary
            chicken-and-egg (the TODO that this very write satisfies). Default
            False; non-closeout TODOs still block.
        db_manager: Database manager (dependency injection)
        session: Optional existing session

    Returns:
        Success/error dictionary with sequence number and entry_id

    Raises:
        MemoryEntryWriteValidationError: structured rejection when caps are
            exceeded -- contains ``error``, ``field``, ``actual_size``,
            ``max_size``, ``guidance``.
    """
    if not project_id:
        raise ValidationError("project_id is required")

    if not summary or not summary.strip():
        raise ValidationError("summary is required")

    if db_manager is None:
        raise ValidationError("db_manager is required")

    key_outcomes = key_outcomes or []
    decisions_made = decisions_made or []

    # INF-WriteShape: single validated write boundary -- shared with
    # write_project_closeout. Caps:
    #   summary <= 1500, key_outcomes <= 5x250, decisions_made <= 5x250,
    #   deliverables <= 10x150, tags <= 8x30 (controlled vocabulary)
    # Raises MemoryEntryWriteValidationError (structured rejection) on failure;
    # the caller-level except clause filters and re-raises so MCP surfaces it.
    validated = validate_memory_entry_write(
        {
            "summary": summary,
            "key_outcomes": key_outcomes,
            "decisions_made": decisions_made,
            "deliverables": [],
            "tags": tags or [],
        }
    )
    summary = validated.summary
    key_outcomes = validated.key_outcomes
    decisions_made = validated.decisions_made
    validated_tags = validated.tags

    # Normalize common aliases to canonical values
    entry_type_aliases = {"project_closeout": "project_completion"}
    entry_type = entry_type_aliases.get(entry_type, entry_type)

    # Validate entry_type
    # BE-5028 Phase 2 Fix D: Extended vocabulary so the orchestrator/worker
    # authorization matrix above is fully exercised. ``handover_closeout`` is
    # preserved for back-compat (existing prod writers in
    # thin_prompt_generator.py and historical entries).
    valid_entry_types = frozenset(
        {
            "project_completion",
            "handover_closeout",
            "session_handover",
            "baseline",
            "decision",
            "architecture",
            "discovery",
        }
    )
    if entry_type not in valid_entry_types:
        raise ValidationError(f"Invalid entry_type '{entry_type}'. Must be one of: {sorted(valid_entry_types)}")

    try:
        owns_session = session is None
        session_ctx = db_manager.get_session_async() if owns_session else provided_session(session)

        async with session_ctx as active_session:
            project, product = await _resolve_project_and_product(
                session=active_session,
                project_id=project_id,
                tenant_key=tenant_key,
            )

            # BE-9157: refuse 360 writes to a superseded project (Tier-2 domain rejection).
            if (rejection := refuse_if_superseded(project)) is not None:
                return rejection

            # BE-5028 Fix B: Per-entry-type authorization gate.
            # Resolve caller's job_type and reject orchestrator-only entry_types
            # written by non-orchestrator agents. This is an authorship gate;
            # the CLOSEOUT_BLOCKED readiness check below is a separate
            # workspace-state gate -- both can fire on the same call.
            # BE-6212: detect the project-less chain conductor (computed from the
            # caller_job loaded just below for the auth gate -- no extra query) so its
            # series-summary drive TODOs auto-ack even without acknowledge_closeout_todo.
            is_conductor_author = False
            if author_job_id and entry_type in ORCHESTRATOR_ONLY_ENTRY_TYPES:
                completion_repo = AgentCompletionRepository()
                caller_job = await completion_repo.get_agent_job_by_job_id(active_session, tenant_key, author_job_id)
                caller_role = caller_job.job_type if caller_job else "unknown"
                is_conductor_author = bool(
                    caller_job is not None
                    and getattr(caller_job, "project_id", None) is None
                    and (getattr(caller_job, "job_metadata", None) or {}).get("chain_conductor")
                )
                if caller_role != "orchestrator":
                    logger.info(
                        "write_360_memory rejected: ORCHESTRATOR_ONLY_ENTRY_TYPE entry_type=%s caller_role=%s author_job_id=%s",
                        entry_type,
                        caller_role,
                        author_job_id,
                    )
                    return {
                        "success": False,
                        "error": "ORCHESTRATOR_ONLY_ENTRY_TYPE",
                        "entry_type": entry_type,
                        "calling_agent_role": caller_role,
                        "message": (
                            f"Only orchestrators write {entry_type} entries. "
                            f"As a worker, you may write: {sorted(WORKER_ALLOWED_ENTRY_TYPES)}. "
                            f"To record {entry_type} content, send a HANDOVER message to your orchestrator "
                            f"with the content and let the orchestrator write it."
                        ),
                        "allowed_for_workers": sorted(WORKER_ALLOWED_ENTRY_TYPES),
                    }

            # BE-6208a: honor acknowledge_closeout_todo BEFORE the readiness gate
            # so the author's own self-referential closeout TODO (the one this
            # very write satisfies) is auto-completed and never blocks. Mirrors
            # complete_job's bypass. Non-closeout TODOs remain and still block.
            # BE-6212: also auto-fire for the project-less chain conductor WITHOUT the flag
            # (its whole TODO list is drive bookkeeping; symmetric with complete_job). A solo
            # project_completion write keeps today's behavior (is_conductor_author is False).
            if author_job_id and (acknowledge_closeout_todo or is_conductor_author):
                await _ack_closeout_todos(
                    active_session,
                    tenant_key,
                    author_job_id,
                    apply_intent_pattern=entry_type in CLOSEOUT_FAMILY_ENTRY_TYPES,
                    apply_chain_drive_pattern=is_conductor_author,
                )

            # Handover 0431: Pre-closeout verification.
            # Only enforce readiness check for project_completion (not handover_closeout).
            # Handovers document incomplete work in 360 memory rather than requiring clean state.
            if author_job_id and entry_type == "project_completion":
                is_ready, verification_result = await _check_closeout_readiness(
                    session=active_session,
                    project_id=project_id,
                    tenant_key=tenant_key,
                    orchestrator_job_id=author_job_id,
                )

                if not is_ready:
                    logger.warning(
                        f"Closeout blocked for project {project_id}: "
                        f"{len(verification_result.get('blockers', []))} blocker(s) found",
                        extra={"project_id": project_id, "tenant_key": tenant_key},
                    )
                    return {
                        "success": False,
                        "error": "CLOSEOUT_BLOCKED",
                        **verification_result,
                    }

            # Hard gate: if git integration is enabled, require commits
            git_integration_enabled = False
            try:
                from giljo_mcp.services.settings_service import SettingsService

                settings_svc = SettingsService(active_session, tenant_key)
                git_settings = await settings_svc.get_setting_value("integrations", "git_integration", {})
                git_integration_enabled = git_settings.get("enabled", False)
            except Exception as _exc:  # noqa: BLE001
                logger.debug("Settings read skipped: %s", _exc)

            # Bug 1: Only enforce the GIT_COMMITS_REQUIRED gate for
            # project_completion entries. Session handovers and handover closeouts
            # document in-flight work and may legitimately have no commits yet.
            if git_integration_enabled and not git_commits and entry_type == "project_completion":
                return {
                    "success": False,
                    "error": "GIT_COMMITS_REQUIRED",
                    "message": "Git integration is enabled. Provide at least one commit before writing 360 memory.",
                    "project_id": project_id,
                }

            # Use agent-supplied commits. The server is passive -- it never
            # fetches commits from a git host itself (host-agnostic).
            if git_commits is not None:
                try:
                    git_commits = validate_git_commits(git_commits)
                except GitCommitTitleRequiredError as exc:
                    # BE-9256 (Tier-2 domain rejection): a supplied commit has no
                    # title. Return the structured dict so it reaches the agent as
                    # normal tool content, not isError.
                    return build_git_commit_title_required_rejection(exc, project_id)
                logger.info(
                    "Using %d agent-supplied git commits for project %s",
                    len(git_commits),
                    project_id,
                )
            else:
                git_commits = []
                logger.info(
                    "No agent-supplied git commits for project %s (server is passive)",
                    project_id,
                )

            memory_service = ProductMemoryService(
                db_manager=db_manager,
                tenant_key=tenant_key,
            )
            sequence_number = await memory_service.get_next_sequence(
                product_id=UUID(product.id),
                session=active_session,
            )

            author_info = await _resolve_author_info(
                session=active_session,
                author_job_id=author_job_id,
                tenant_key=tenant_key,
            )

            params = MemoryEntryCreateParams(
                tenant_key=tenant_key,
                product_id=UUID(product.id),
                project_id=UUID(project_id),
                sequence=sequence_number,
                entry_type=entry_type,
                source="write_360_memory_v1",
                timestamp=datetime.now(UTC),
                project_name=project.name,
                summary=summary,
                key_outcomes=key_outcomes,
                decisions_made=decisions_made,
                git_commits=git_commits,
                tags=validated_tags,
                author_job_id=UUID(author_job_id) if author_job_id else None,
                author_name=author_info.get("author_name"),
                author_type=author_info.get("author_type"),
            )
            entry = await memory_service.create_entry(
                params=params,
                session=active_session,
            )

            # Session commit handled by db_manager.get_session_async() context manager
            # when owns_session=True; flush already done by repo.create_entry()

            logger.info(
                f"Wrote 360 Memory entry {entry.id} for product {product.id} "
                f"(sequence: {sequence_number}, type: {entry_type}, commits: {len(git_commits)})"
            )

            await emit_websocket_event(
                event_type="product:memory:updated",
                tenant_key=tenant_key,
                product_id=str(product.id),
                data={"entry": entry.to_dict()},
            )

            # Handover 0831: Check tuning staleness after memory write.
            # IMP-5037 bug 2: user_id must be a real user UUID, not tenant_key.
            await _check_and_emit_tuning_staleness(
                db_manager=db_manager,
                tenant_key=tenant_key,
                product=product,
                user_id=user_id,
            )

            # BE-9085: closeout-only detector, project_completion only (see
            # _prelaunch_workproduct_detector.py for the fire condition and
            # the fail-open / restage-tradeoff notes).
            if entry_type == "project_completion":
                await check_and_emit_prelaunch_workproduct(
                    db_manager=db_manager,
                    tenant_key=tenant_key,
                    project=project,
                    git_commits=git_commits,
                )

            result = {
                "sequence_number": sequence_number,
                "entry_id": str(entry.id),
                "git_commits_count": len(git_commits),
                "entry_type": entry_type,
                "message": "360 Memory entry written successfully",
            }

            # Include verification details if author_job_id was provided (Handover 0431).
            if author_job_id:
                _, verification_result = await _check_closeout_readiness(
                    session=active_session,
                    project_id=project_id,
                    tenant_key=tenant_key,
                    orchestrator_job_id=author_job_id,
                )
                result["verified"] = _derive_verified(verification_result)

            return result

    except (RuntimeError, ValueError, KeyError) as exc:
        logger.exception("Failed to write 360 memory entry", extra={"error": str(exc)})
        raise
