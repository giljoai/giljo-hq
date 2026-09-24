# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
from giljo_mcp.schemas.jsonb_validators import (
    GitCommitShaRequiredError,
    GitCommitTitleRequiredError,
    validate_git_commits,
)
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

WORKER_ALLOWED_ENTRY_TYPES = frozenset({"baseline", "decision", "architecture", "discovery"})
ORCHESTRATOR_ONLY_ENTRY_TYPES = frozenset({"project_completion"})

CLOSEOUT_FAMILY_ENTRY_TYPES = frozenset({"project_completion"})

VALID_ENTRY_TYPES = frozenset(
    {
        "project_completion",
        "baseline",
        "decision",
        "architecture",
        "discovery",
    }
)

ENTRY_TYPE_ALIASES = {"project_closeout": "project_completion"}

RETIRED_ENTRY_TYPES = frozenset({"session_handover", "handover_closeout"})


async def _ack_closeout_todos(
    session: AsyncSession,
    tenant_key: str,
    author_job_id: str,
    *,
    apply_intent_pattern: bool = False,
    apply_chain_drive_pattern: bool = False,
) -> int:
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
        if finding.messages_waiting > 0:
            summary["agents_with_unread"] += 1

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
            continue

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
            "deliverables": [],
            "tags": tags or [],
        }
    )
    summary = validated.summary
    key_outcomes = validated.key_outcomes
    decisions_made = validated.decisions_made
    validated_tags = validated.tags

    entry_type = ENTRY_TYPE_ALIASES.get(entry_type, entry_type)

    if entry_type not in VALID_ENTRY_TYPES:
        raise ValidationError(f"Invalid entry_type '{entry_type}'. Must be one of: {sorted(VALID_ENTRY_TYPES)}")

    try:
        owns_session = session is None
        session_ctx = db_manager.get_session_async() if owns_session else provided_session(session)

        async with session_ctx as active_session:
            project, product = await _resolve_project_and_product(
                session=active_session,
                project_id=project_id,
                tenant_key=tenant_key,
            )

            if (rejection := refuse_if_superseded(project)) is not None:
                return rejection

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

            if author_job_id and (acknowledge_closeout_todo or is_conductor_author):
                await _ack_closeout_todos(
                    active_session,
                    tenant_key,
                    author_job_id,
                    apply_intent_pattern=entry_type in CLOSEOUT_FAMILY_ENTRY_TYPES,
                    apply_chain_drive_pattern=is_conductor_author,
                )

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

            git_integration_enabled = False
            try:
                from giljo_mcp.services.settings_service import SettingsService

                settings_svc = SettingsService(active_session, tenant_key)
                git_settings = await settings_svc.get_setting_value("integrations", "git_integration", {})
                git_integration_enabled = git_settings.get("enabled", False)
            except Exception as _exc:  # noqa: BLE001
                logger.debug("Settings read skipped: %s", _exc)

            if git_integration_enabled and not git_commits and entry_type == "project_completion":
                return {
                    "success": False,
                    "error": "GIT_COMMITS_REQUIRED",
                    "message": "Git integration is enabled. Provide at least one commit before writing 360 memory.",
                    "project_id": project_id,
                }

            if git_commits is not None:
                try:
                    git_commits = validate_git_commits(git_commits)
                except GitCommitTitleRequiredError as exc:
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

            await _check_and_emit_tuning_staleness(
                db_manager=db_manager,
                tenant_key=tenant_key,
                product=product,
                user_id=user_id,
            )

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

            if author_job_id:
                _, verification_result = await _check_closeout_readiness(
                    session=active_session,
                    project_id=project_id,
                    tenant_key=tenant_key,
                    orchestrator_job_id=author_job_id,
                )
                result["verified"] = _derive_verified(verification_result)

            return result

    except GitCommitShaRequiredError as exc:
        logger.info("write_360_memory rejected: %s", exc)
        raise
    except (RuntimeError, ValueError, KeyError) as exc:
        logger.exception("Failed to write 360 memory entry", extra={"error": str(exc)})
        raise
