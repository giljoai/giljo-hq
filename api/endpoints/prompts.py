# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from api.dependencies.websocket import WebSocketDependency, get_websocket_dependency
from api.endpoints.chain_prompt_bootstrap import (
    CHAIN_MEMBER_FALLBACK_PREAMBLE,
    _build_conductor_bootstrap,
    _conductor_mcp_url,
    _resolve_conductor_job_id,
)
from api.endpoints.projects.dependencies import get_project_service
from api.schemas.prompt import (
    AgentPromptResponse,
    ChainMemberPromptResponse,
    ChainPromptResponse,
    ImplementationPromptResponse,
    OrchestratorPromptRequest,
    StagingPromptResponse,
    ThinOrchestratorPromptResponse,
)
from giljo_mcp.auth.dependencies import get_current_active_user, get_db_session
from giljo_mcp.exceptions import BaseGiljoError, ProjectStateError, ResourceNotFoundError
from giljo_mcp.models import Project, User
from giljo_mcp.models.agent_identity import AgentExecution
from giljo_mcp.platform_registry import (
    HARNESS_CLAUDE_CODE,
    effective_harness,
    execution_mode_pattern,
    tool_type_pattern,
)
from giljo_mcp.prompts.spawn_prompt import build_agent_prompt, launch_gate_passed
from giljo_mcp.repositories.project_lifecycle_repository import ProjectLifecycleRepository
from giljo_mcp.repositories.template_repository import TemplateRepository
from giljo_mcp.services.execution_mode_gate import effective_execution_mode
from giljo_mcp.services.mission_orchestration_service import MissionOrchestrationService
from giljo_mcp.services.orchestrator_prompt_ws_broadcast import broadcast_orchestrator_prompt_generated
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.services.sequence_chain_context import chain_member_phase, renders_multi_terminal
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager
from giljo_mcp.thin_prompt_generator import ThinClientPromptGenerator
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)
router = APIRouter()

_TOOL_TYPE_PATTERN = tool_type_pattern()
_EXECUTION_MODE_PATTERN = execution_mode_pattern()


@router.post("/prompts/orchestrator-thin", response_model=ThinOrchestratorPromptResponse)
async def generate_orchestrator_prompt_thin(
    request: OrchestratorPromptRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
    ws_dep: WebSocketDependency = Depends(get_websocket_dependency),
) -> ThinOrchestratorPromptResponse:
    """
    Generate a thin orchestrator prompt for GiljoMCP Agent Orchestration.

    Handover 0088: Thin Client Architecture
    - Prompt is only ~300 tokens (down from ~3500)
    - Mission fetched via get_staging_instructions() MCP tool
    - Field priorities applied at MCP tool call time, not prompt generation
    - Context size tracking built into thin client flow

    Handover 0246a (Nov 2025): Further optimizations
    - Staging prompt reduced from ~1600 to 931 tokens (42% reduction)
    - 7-task standardized workflow
    - Clean separation between staging/execution

    Args:
        request: Request containing project_id and tool
        current_user: Currently authenticated user
        db: Database session

    Returns:
        ThinOrchestratorPromptResponse with thin prompt

    Raises:
        HTTPException: If project not found or error occurs
    """
    try:
        project_id = request.project_id
        tool = request.tool or "universal"

        generator = ThinClientPromptGenerator(db, current_user.tenant_key)

        result = await generator.generate(
            project_id=project_id,
            user_id=str(current_user.id),
            tool=tool,
        )

        if ws_dep.is_available():
            await broadcast_orchestrator_prompt_generated(
                ws_dep,
                tenant_key=current_user.tenant_key,
                project_id=project_id,
                orchestrator_id=result["orchestrator_id"],
                execution_id=result.get("execution_id"),
                estimated_tokens=result["estimated_prompt_tokens"],
                timestamp=datetime.now(UTC).isoformat(),
                product_id=result.get("product_id"),
            )

        return ThinOrchestratorPromptResponse(
            success=True,
            orchestrator_id=result["orchestrator_id"],
            prompt=result["thin_prompt"],
            estimated_prompt_tokens=result["estimated_prompt_tokens"],
            thin_client=True,
            status="ready",
        )

    except ValueError as e:
        logger.exception("Validation error generating thin orchestrator prompt")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requested resource not found.") from e
    except Exception as e:
        logger.error("Error generating thin orchestrator prompt: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate orchestrator prompt. Check server logs.",
        ) from e


@router.get("/agent/{agent_id}", response_model=AgentPromptResponse)
async def generate_agent_prompt(
    agent_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Generate thin agent prompt for MCP-based mission bootstrap.

    Returns a lightweight prompt (~50 tokens) that instructs the agent to call
    get_job_mission() via MCP to retrieve its full mission and protocol.
    Matches the same thin prompt pattern used at spawn time by spawn_job().

    Args:
        agent_id: Agent execution ID
        current_user: Authenticated user (from dependency)
        db: Database session (from dependency)

    Returns:
        AgentPromptResponse with thin prompt, agent metadata, and instructions

    Raises:
        404: Agent not found or not accessible
    """
    stmt = (
        select(AgentExecution)
        .options(joinedload(AgentExecution.job))
        .where(AgentExecution.agent_id == agent_id, AgentExecution.tenant_key == current_user.tenant_key)
    )
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent {agent_id} not found or not accessible"
        )

    project_name = "Unknown Project"
    project = None
    if agent.job and agent.job.project_id:
        project_stmt = select(Project).where(
            Project.id == agent.job.project_id, Project.tenant_key == current_user.tenant_key
        )
        project_result = await db.execute(project_stmt)
        project = project_result.scalar_one_or_none()
        if project:
            project_name = project.name

    agent_name = agent.agent_name or agent.agent_display_name
    agent_display_name = agent.agent_display_name
    job_id = agent.job_id
    tool_type = agent.tool_type or "universal"

    mission = (agent.job.mission if agent.job else None) or ""
    mission_preview = mission[:200] + "..." if len(mission) > 200 else mission

    tid = agent.job.template_id if agent.job else None
    template = await TemplateRepository().get_by_id(db, tid, current_user.tenant_key) if tid else None
    multi_terminal = await renders_multi_terminal(
        db,
        project=project,
        project_id=(agent.job.project_id if agent.job else ""),
        tenant_key=current_user.tenant_key,
    )
    prompt = build_agent_prompt(
        agent_name,
        agent_display_name,
        project_name,
        job_id,
        template,
        multi_terminal=multi_terminal,
        launched=launch_gate_passed(project),
    )

    instructions = (
        "Paste this prompt into an agent session (terminal, desktop, or web tab) with MCP "
        "configured. Agent will call get_job_mission() to bootstrap."
    )

    return AgentPromptResponse(
        prompt=prompt,
        agent_id=agent.agent_id,
        agent_name=agent_name,
        agent_display_name=agent_display_name,
        tool_type=tool_type,
        instructions=instructions,
        mission_preview=mission_preview,
    )


@router.get("/staging/{project_id}", response_model=StagingPromptResponse)
async def generate_staging_prompt(
    project_id: str,
    tool: str = Query("claude-code", pattern=_TOOL_TYPE_PATTERN),
    execution_mode: str | None = Query(
        None,
        pattern=_EXECUTION_MODE_PATTERN,
        description=(
            "Execution mode: 'multi_terminal' or 'subagent' (legacy per-CLI tokens are tolerated). "
            "NULL-state: omit when the user has not chosen a mode — staging is then rejected with 409."
        ),
    ),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
    ws_dep: WebSocketDependency = Depends(get_websocket_dependency),
    project_service: ProjectService = Depends(get_project_service),
):
    """
    Generate thin client orchestrator staging prompt (Handover 0088).

    UPDATED FOR THIN CLIENT ARCHITECTURE:
    - OLD (Handover 0079): Returns 2000-3000 line fat prompt with embedded mission
    - NEW (Handover 0088): Returns ~10 line thin prompt with MCP tool reference

    THE HEART OF GILJOAI - Generates intelligent, token-efficient orchestrator
    prompts that enable AI agents to discover context via MCP, create condensed
    missions, and coordinate multi-agent workflows.

    Process:
    1. Validates project exists and belongs to tenant
    2. Creates orchestrator job in database
    3. Stores condensed mission with user's field priorities
    4. Generates thin prompt with orchestrator_id
    5. Returns ready-to-paste thin prompt (~10 lines)

    Features:
    - Thin client architecture (context prioritization and orchestration ACTIVE)
    - MCP-only data access (remote-safe, no local file reads)
    - Dynamic field priority integration (user-configured)
    - Professional UX (copy 10 lines, not 3000)
    - Multi-tool support (Claude Code, Codex, opencode, generic)

    Args:
        project_id: Project UUID to generate prompt for
        tool: Target AI tool (claude-code, codex, opencode, or generic)
        current_user: Authenticated user (ensures tenant isolation)
        db: Database session

    Returns:
        StagingPromptResponse: Staging prompt response with:
            - orchestrator_id: Created orchestrator job ID
            - agent_id: Executor agent ID for MCP tool calls
            - prompt: Staging prompt for orchestrator
            - estimated_prompt_tokens: Token estimate for the staging prompt

    Raises:
        HTTPException 404: Project not found or not accessible
        HTTPException 400: Invalid tool parameter
        HTTPException 500: Prompt generation error
    """
    from sqlalchemy import and_ as _and

    from giljo_mcp.services.comm_thread_enrolment import project_thread_ref
    from giljo_mcp.thin_prompt_generator import ThinClientPromptGenerator

    proj_result = await db.execute(
        select(Project).where(_and(Project.id == project_id, Project.tenant_key == current_user.tenant_key))
    )
    project = proj_result.scalar_one_or_none()
    if project and project.staging_status in ("staged", "staging"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Staging already in progress. Use Unstage to reset first.",
        )

    effective_execution_mode = (execution_mode or (project.execution_mode if project else None) or "").strip()
    if project is not None and not effective_execution_mode:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=("No execution mode selected. Choose an execution mode (Multi-Terminal / Subagent) before staging."),
        )

    try:
        generator = ThinClientPromptGenerator(db, current_user.tenant_key)

        result = await generator.generate(
            project_id=project_id,
            user_id=str(current_user.id),
            tool=tool,
        )

        staging_prompt = await generator.generate_staging_prompt(
            orchestrator_id=result["orchestrator_id"],
            project_id=project_id,
            agent_id=result.get("agent_id"),
            tool=tool,
        )

        staging_tokens = len(staging_prompt) // 4

        if ws_dep.is_available():
            await broadcast_orchestrator_prompt_generated(
                ws_dep,
                tenant_key=current_user.tenant_key,
                project_id=project_id,
                orchestrator_id=result["orchestrator_id"],
                agent_id=result.get("agent_id"),
                execution_id=result.get("execution_id"),
                tool=tool,
                product_id=result.get("product_id"),
            )
            logger.info(
                "[STAGING PROMPT THIN] WebSocket broadcast sent for orchestrator %s",
                sanitize(str(result["orchestrator_id"])),
            )

        logger.info(
            "[STAGING PROMPT THIN] Generated for project=%s, tool=%s, tokens=%s, user=%s",
            sanitize(project_id),
            sanitize(tool),
            result["estimated_prompt_tokens"],
            sanitize(current_user.username),
        )

        thread_ref = await project_thread_ref(db, current_user.tenant_key, project_id)
        if project:
            await project_service.lifecycle.mark_staged(
                project_id, effective_execution_mode, tenant_key=current_user.tenant_key, db_session=db
            )

        return StagingPromptResponse(
            orchestrator_id=result["orchestrator_id"],
            agent_id=result.get("agent_id"),
            prompt=staging_prompt,
            estimated_prompt_tokens=staging_tokens,
            **thread_ref,
        )

    except ValueError as e:
        logger.warning(
            "[STAGING PROMPT THIN] Validation error for project=%s: %s", sanitize(project_id), sanitize(str(e))
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requested resource not found.") from e

    except Exception as e:
        logger.exception("[STAGING PROMPT THIN] Generation failed for project=%s", sanitize(project_id))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate staging prompt. Check server logs.",
        ) from e


@router.get("/implementation/{project_id}", response_model=ImplementationPromptResponse)
async def get_implementation_prompt(
    project_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Generate implementation prompt for CLI mode projects (Handover 0337 - Task 1).

    This endpoint generates the implementation phase prompt for Claude Code CLI mode.
    After staging (where orchestrator plans and spawns agent jobs), the user pastes
    this implementation prompt to have the orchestrator spawn agents via Task tool.

    Requirements:
    - Project must exist and be in CLI mode (execution_mode = 'claude_code_cli')
    - Active orchestrator job must exist (status = 'working')
    - At least one spawned agent job must exist (status in ['waiting', 'working'])
    - Multi-tenant isolation enforced

    Process:
    1. Validate project exists and belongs to tenant
    2. Validate CLI mode execution
    3. Fetch active orchestrator job
    4. Fetch spawned agent jobs
    5. Generate implementation prompt via ThinClientPromptGenerator
    6. Return prompt with metadata

    Args:
        project_id: Project UUID to generate implementation prompt for
        current_user: Authenticated user (ensures tenant isolation)
        db: Database session

    Returns:
        dict: Implementation prompt response with:
            - prompt: Implementation prompt for orchestrator to spawn agents
            - orchestrator_job_id: Orchestrator job UUID
            - agent_count: Number of spawned agents ready to execute

    Raises:
        HTTPException 404: Project not found or no active orchestrator
        HTTPException 400: Not CLI mode or no spawned agents
        HTTPException 403: Tenant isolation violation
        HTTPException 500: Prompt generation error
    """
    generator = ThinClientPromptGenerator(db, current_user.tenant_key)
    try:
        payload = await generator.implement(project_id=project_id, user_id=str(current_user.id))
    except BaseGiljoError as e:
        raise HTTPException(status_code=e.default_status_code, detail=e.message) from e

    logger.info(
        "[IMPLEMENTATION PROMPT] Generated for project=%s, orchestrator=%s, agents=%d, user=%s",
        sanitize(project_id),
        sanitize(str(payload["orchestrator_job_id"])),
        payload["agent_count"],
        sanitize(current_user.username),
    )

    return ImplementationPromptResponse.model_validate(payload)


@router.get("/chain-staging/{run_id}", response_model=ChainPromptResponse)
async def get_chain_staging_prompt(
    run_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
    project_service: ProjectService = Depends(get_project_service),
) -> ChainPromptResponse:
    """Return the chain STAGING prompt for the dedicated, project-less conductor.

    BE-6191: Resolves the run's DEDICATED, project-less conductor (minted at
    run-create; run['conductor_agent_id']), NOT the head project's orchestrator, and
    returns a THIN bootstrap. The conductor's full chain protocol (CH_CAPABILITY +
    CH_CHAIN_STAGING) is fetched by the conductor itself via get_staging_instructions
    on its OWN project-less job (which resolves the conductor branch, BE-6186); the
    endpoint no longer fat-pastes the chapter bodies or a dangling agent_templates
    appendix.

    Still propagates the run's execution_mode down to every member project so the
    per-project boundary gates don't 409.

    Raises 404 when the run is not found; 409 when the run has no resolved_order or no
    dedicated conductor (legacy pre-BE-6184 run).
    """
    svc_run = SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=db)
    try:
        run = await svc_run.get(run_id=run_id, tenant_key=current_user.tenant_key)
    except ResourceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sequence run {run_id} not found or not accessible.",
        ) from exc

    resolved_order: list[str] = run.get("resolved_order") or []
    if not resolved_order:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Sequence run {run_id} has no resolved_order — cannot identify head project.",
        )
    head_pid = resolved_order[0]

    run_mode = (run.get("execution_mode") or "").strip()
    if run_mode:
        for member_pid in resolved_order:
            try:
                await project_service.update_project(member_pid, {"execution_mode": run_mode})
            except ProjectStateError:
                continue
            except ResourceNotFoundError:
                continue

    conductor_job_id = await _resolve_conductor_job_id(run, current_user.tenant_key, db)

    svc = MissionOrchestrationService(db_manager=None, tenant_manager=None, test_session=db)
    try:
        result = await svc.get_staging_instructions(job_id=conductor_job_id, tenant_key=current_user.tenant_key)
    except BaseGiljoError as exc:
        raise HTTPException(status_code=exc.default_status_code, detail=exc.message) from exc

    harness_is_claude = effective_harness(run_mode) == HARNESS_CLAUDE_CODE or run_mode == "multi_terminal"
    prompt_text = _build_conductor_bootstrap(
        identity=result["identity"],
        mcp_url=_conductor_mcp_url(),
        phase="staging",
        harness_is_claude=harness_is_claude,
    )

    logger.info(
        "[CHAIN STAGING PROMPT] Generated for run=%s, head_project=%s, job=%s, user=%s",
        sanitize(run_id),
        sanitize(head_pid),
        sanitize(conductor_job_id),
        sanitize(current_user.username),
    )

    return ChainPromptResponse(
        run_id=run_id,
        head_project_id=head_pid,
        orchestrator_job_id=conductor_job_id,
        prompt=prompt_text,
    )


@router.get("/chain-implementation/{run_id}", response_model=ChainPromptResponse)
async def get_chain_implementation_prompt(
    run_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
) -> ChainPromptResponse:
    """Return the chain IMPLEMENTATION prompt for the dedicated, project-less conductor.

    BE-6191: Resolves the run's DEDICATED, project-less conductor (minted at
    run-create; run['conductor_agent_id']), NOT the head project's orchestrator, and
    returns a THIN drive bootstrap. The conductor's full chain-drive protocol
    (CH_CHAIN_DRIVE) is fetched by the conductor itself via get_job_mission on its
    OWN project-less job; the endpoint does not fat-paste it.

    The prompt is the single master prompt the user pastes to drive the entire chain:
    one paste, one conductor, drives all N projects sequentially.

    Raises 404 when the run is not found; 409 when the run has no resolved_order or no
    dedicated conductor (legacy pre-BE-6184 run).
    """
    tenant_key = current_user.tenant_key
    svc_run = SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=db)
    try:
        run = await svc_run.get(run_id=run_id, tenant_key=tenant_key)
    except ResourceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sequence run {run_id} not found or not accessible.",
        ) from exc

    resolved_order: list[str] = run.get("resolved_order") or []
    if not resolved_order:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Sequence run {run_id} has no resolved_order — cannot identify head project.",
        )
    head_pid = resolved_order[0]

    conductor_job_id = await _resolve_conductor_job_id(run, tenant_key, db)

    run_mode = (run.get("execution_mode") or "").strip()
    harness_is_claude = effective_harness(run_mode) == HARNESS_CLAUDE_CODE or run_mode == "multi_terminal"
    identity = {
        "agent_id": run.get("conductor_agent_id"),
        "job_id": conductor_job_id,
        "run_id": run_id,
        "project_id": None,
    }
    prompt_text = _build_conductor_bootstrap(
        identity=identity,
        mcp_url=_conductor_mcp_url(),
        phase="implementation",
        harness_is_claude=harness_is_claude,
    )

    logger.info(
        "[CHAIN IMPL PROMPT] Generated for run=%s, head_project=%s, job=%s, user=%s",
        sanitize(run_id),
        sanitize(head_pid),
        sanitize(conductor_job_id),
        sanitize(current_user.username),
    )

    return ChainPromptResponse(
        run_id=run_id,
        head_project_id=head_pid,
        orchestrator_job_id=conductor_job_id,
        prompt=prompt_text,
    )


@router.get("/chain-member/{project_id}", response_model=ChainMemberPromptResponse)
async def get_chain_member_prompt(
    project_id: str,
    fallback: bool = Query(
        default=False,
        description=(
            "Return the fallback form: the same prompt, opened by a line telling the session "
            "it runs this project only and the conductor decides the next step."
        ),
    ),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
) -> ChainMemberPromptResponse:
    """Return the orchestrator prompt for ONE project in a linked chain.

    A chain runs one project at a time, so each member starts from its own play
    button exactly the way a single project does. This is the prompt that button
    copies: the member's own orchestrator identity on the shared thin bootstrap,
    which stages this project, implements it, and stops at close-out. The next
    member's button unlocks once this one has closed out.

    With ``fallback=true`` the prompt is opened by a fixed line saying it is a
    fallback for this project only; the conductor still decides the next step.

    Raises 404 when the project is not found, is not a member of an active chain,
    or has no orchestrator of its own yet.
    """
    tenant_key = current_user.tenant_key

    project = (
        await db.execute(select(Project).where(Project.id == project_id, Project.tenant_key == tenant_key))
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found or not accessible.",
        )

    run = await SequenceRunService(
        db_manager=None, tenant_manager=TenantManager(), session=db
    ).find_active_run_for_project(project_id=project_id, tenant_key=tenant_key)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This project is not a member of an active chain. Use the project's own staging prompt.",
        )

    execution = await ProjectLifecycleRepository().find_existing_orchestrator(db, tenant_key, project_id)
    if execution is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This chain member has no orchestrator yet. Stage the chain first.",
        )

    run_mode = effective_execution_mode(project.execution_mode, run.get("execution_mode"))
    harness_is_claude = effective_harness(run_mode) == HARNESS_CLAUDE_CODE or run_mode == "multi_terminal"

    prompt_text = _build_conductor_bootstrap(
        identity={
            "agent_id": str(execution.agent_id),
            "job_id": str(execution.job_id),
            "run_id": run["id"],
            "project_id": project_id,
        },
        mcp_url=_conductor_mcp_url(),
        phase=chain_member_phase(project),
        harness_is_claude=harness_is_claude,
    )
    if fallback:
        prompt_text = f"{CHAIN_MEMBER_FALLBACK_PREAMBLE}\n\n{prompt_text}"

    logger.info(
        "[CHAIN MEMBER PROMPT] Generated for project=%s, run=%s, job=%s, user=%s",
        sanitize(project_id),
        sanitize(run["id"]),
        sanitize(str(execution.job_id)),
        sanitize(current_user.username),
    )

    return ChainMemberPromptResponse(
        run_id=run["id"],
        project_id=project_id,
        orchestrator_job_id=str(execution.job_id),
        prompt=prompt_text,
    )
