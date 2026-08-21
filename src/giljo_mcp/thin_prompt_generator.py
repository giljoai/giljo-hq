# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Thin Client Prompt Generator (Handover 0088, 0315, 0950g)

Generates thin orchestrator prompts (~600 tokens) with MCP tool references.
Orchestrators fetch context on-demand via MCP tools (context prioritization enabled).

Architecture (Handover 0315):
- User configures priorities (0313) and depth (0314)
- Generator creates thin prompt listing available MCP tools by priority
- Orchestrator fetches context on-demand via MCP tool calls

Platform-specific prompt builders extracted to giljo_mcp.prompts/ (Handover 0950g):
- ClaudePromptBuilder: Claude Code CLI execution prompts
- CodexPromptBuilder: Codex CLI execution prompts
- GeminiPromptBuilder: Gemini CLI execution prompts
- MultiTerminalPromptBuilder: Platform-agnostic multi-terminal orchestrator prompts
- StagingPromptBuilder: Staging-phase prompts and mission regeneration

Author: GiljoAI Development Team
"""

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from giljo_mcp.http.url_resolver import get_public_url
from giljo_mcp.models import Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.prompts.claude_prompt_builder import ClaudePromptBuilder
from giljo_mcp.prompts.codex_prompt_builder import CodexPromptBuilder
from giljo_mcp.prompts.gemini_prompt_builder import GeminiPromptBuilder
from giljo_mcp.prompts.multi_terminal_prompt_builder import MultiTerminalPromptBuilder
from giljo_mcp.prompts.staging_prompt_builder import StagingPromptBuilder
from giljo_mcp.prompts.subagent_prompt_builder import SubagentPromptBuilder
from giljo_mcp.schemas.jsonb_validators import validate_agent_job_metadata
from giljo_mcp.thin_prompt_lifecycle import SUBAGENT_EXECUTION_PROMPT_TYPE, ThinClientLifecycleMixin
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)


def build_continuation_prompt(
    project_id: str,
    agent_id: str,
    job_id: str,
    project_name: str | None = None,
    product_id: str | None = None,
    run_id: str | None = None,
    current_index: int | None = None,
    resolved_order: list[str] | None = None,
    overarching_mission: str | None = None,
) -> str:
    """Build a continuation prompt for orchestrator session refresh.

    Canonical prompt builder for all handover paths (REST endpoint, slash command,
    ThinClientPromptGenerator). Reads the MCP URL via
    giljo_mcp.http.url_resolver.get_public_url (BE-9442) — GILJO_PUBLIC_URL
    (INF-5012b), trailing slash stripped, with http://localhost:7272 as the
    CE-localhost fallback.

    Args:
        project_id: Project UUID
        agent_id: Agent execution ID (WHO - executor ID for MCP calls)
        job_id: Job ID (WHAT - work order ID)
        project_name: Optional project display name (for human readability)
        product_id: Optional product UUID (for get_context call)

    Returns:
        Continuation prompt string
    """
    # INF-5012b: prefer GILJO_PUBLIC_URL (demo/cloud deploys) over reading
    # the server's bind address from config, which produces ":7272" URLs
    # when the server is fronted by a reverse proxy.
    # BE-9442: normalisation moved into the accessor; behaviour here is unchanged.
    public_base = get_public_url()
    mcp_url = f"{public_base}/mcp"

    project_display = f' "{project_name}"' if project_name else ""
    product_param = product_id if product_id else "<fetch from project>"

    base_prompt = f"""I am Orchestrator for Project{project_display} (CONTINUATION SESSION).

A previous session ran out of context. I am continuing the work.

YOUR IDENTITY (use these in all MCP calls):
  YOUR Agent ID: {agent_id}
  YOUR Job ID: {job_id}
  THE Project ID: {project_id}

MCP Server: {mcp_url}
Note: tenant_key is auto-injected by server from your API key session
Tool names below are bare; your MCP client may expose them under a prefix
(e.g. `mcp__<server>__<tool>`) — call them by the names your harness lists.

FIRST ACTIONS (DO NOT RE-STAGE):

1. Verify MCP: health_check()
   -> Expected: {{"status": "healthy"}}

2. Signal you are alive:
   report_progress(
       job_id="{job_id}",
       todo_items=[{{"content": "Continuation startup", "status": "in_progress"}}]
   )

3. Read 360 Memory for session context:
   get_context(
       product_id="{product_param}",
       categories=["memory_360"],
       depth_config={{"memory_360": {{"shape": "full"}}}}
   )
   -> Look for the most recent "handover_closeout" entry (authored by job {job_id})
   -> Contains: previous progress, current status, next steps
   -> "full" shape required: handover bodies are needed in full, not headlines.

4. Check messages + retrieve execution plan (can run in parallel):
   get_thread_history(as_participant="{agent_id}", unread_only=true, mark_read=true) on your coordination thread
   get_job_mission(job_id="{job_id}")
   -> Mission contains: team roster with agent_id UUIDs, execution strategy, completion criteria

5. Check workflow status:
   get_workflow_status(project_id="{project_id}")

AFTER CONTEXT GATHERING — decide next action based on workflow status:
- If agents still working: resume coordination loop — poll get_thread_history() on your coordination
  thread, react to agent updates, post DEPENDENCY_MET or other coordination messages as needed via
  post_to_thread(). The agents do not know you restarted.
- If agents blocked: post to their coordination thread to resolve blockers
- If all agents completed: proceed to closeout (update your own todos to completed via report_progress,
  then complete_job, then write_project_closeout)
- If agents failed: assess and re-spawn if needed

CRITICAL RULES:
- Do NOT call get_staging_instructions() to re-stage
- Do NOT re-write the project mission
- Read 360 Memory handover_closeout for context from previous session
- You are CONTINUING work, not starting from scratch
- Agents were NOT terminated during handover — they kept working. Expect them to be in the same or
  more advanced state than described in the handover. Check workflow_status for current truth.
"""

    # BE-6165e: chain continuation brief. Appended ONLY when this continuation is
    # driving a SequenceRun (handover/resume of a chain conductor). Absent => the
    # prompt is byte-identical to a solo continuation (Deletion Test holds).
    if run_id is None:
        return base_prompt

    idx = current_index if current_index is not None else 0
    order_str = " -> ".join(resolved_order) if resolved_order else "<read from the run record>"
    mission_line = (
        overarching_mission.strip()
        if overarching_mission and overarching_mission.strip()
        else "(read it from the HEAD project's mission field)"
    )
    chain_block = f"""

============================================================
CHAIN CONTINUATION — you are the CONDUCTOR of a sequential multi-project run
============================================================
This is NOT a solo project. You are driving SequenceRun {run_id}.
  Run ID: {run_id}
  Resume at index: {idx} (0-based) within resolved_order
  Resolved order: {order_str}
  Overarching mission (the chain deliverable; lives on the HEAD project's mission field):
    {mission_line}

DO NOT re-elect or re-stage the chain. Read true run state first
(GET /api/v1/sequence-runs/{run_id}), then resume the drive loop AT current_index:
cross the per-project implement gate ONE project at a time
(launch_implementation per project — never batch-unlock the tail), advancing only
on a recorded commit. Your conductor identity is re-stamped to your agent_id on
your first staging/mission call.
"""
    return base_prompt + chain_block


def build_retirement_prompt(
    project_id: str,
    agent_id: str,
    job_id: str,
    project_name: str | None = None,
    git_enabled: bool = False,
    project_taxonomy: str = "",
) -> str:
    """Build a retirement prompt for the old orchestrator terminal session.

    This prompt instructs the orchestrator to write rich session context to 360 Memory
    before the terminal session ends.

    Args:
        project_id: Project UUID
        agent_id: Agent execution ID (WHO - executor ID)
        job_id: Job ID (WHAT - work order ID)
        project_name: Optional project display name
        git_enabled: Whether git integration is enabled for this product
        project_taxonomy: Project taxonomy alias (e.g. "BE-0042a")

    Returns:
        Retirement prompt string for the old orchestrator
    """
    project_display = f' "{project_name}"' if project_name else ""

    git_closeout_section = ""
    if git_enabled:
        tag = project_taxonomy or project_name or project_id[:8]
        display_name = project_name or "this project"
        git_closeout_section = f"""
BETWEEN STEP 5 and STEP 6, create a git closeout commit to preserve project history:

git commit --allow-empty -m "closeout({tag}): {display_name}

Completed: <today's date YYYY-MM-DD>
Key outcomes:
- <list each concrete outcome from this session>"

This commit makes project history searchable via git log --grep="closeout" or git log --grep="{tag}".
"""

    return f"""ORCHESTRATOR SESSION RETIREMENT{project_display}

Your agent session is ending due to context exhaustion. You are handing off to a continuation
orchestrator that will pick up where you left off. Other agents are NOT affected — leave them alone.
Tool names below are bare; your MCP client may expose them under a prefix
(e.g. `mcp__<server>__<tool>`) — call them by the names your harness lists.

YOUR IDENTITY:
  Agent ID: {agent_id}
  Job ID: {job_id}
  Project ID: {project_id}

IMPORTANT: Do NOT touch other agents. Do NOT drain their messages, modify their todos, or force-complete
their jobs. They are running independently and will continue working after you exit. The continuation
orchestrator will resume coordination with them seamlessly using the same agent_id and job_id.

STEP 1 — Snapshot team state (READ-ONLY, do NOT modify anything)

get_workflow_status(project_id="{project_id}")

Record the current state of each agent for your handover summary:
- Agent name, job_id, status, messages_waiting, todo progress
- Any agents that are blocked and what they are blocked on

STEP 2 — Drain YOUR OWN message queue

get_thread_history(as_participant="{agent_id}", unread_only=true, mark_read=true) on your coordination thread

Record any important messages for your handover summary.

STEP 3 — Report your own progress

report_progress(
    job_id="{job_id}",
    todo_items=[...mark your own items appropriately...]
)

STEP 4 — Write 360 Memory handover (append-only, previous entries are preserved)

The server enforces hard caps. Compose your handover to fit:
- summary: max 1500 chars (2-3 sentence headline of the session and the handoff context)
- key_outcomes: max 5 items, each max 250 chars
- decisions_made: max 5 items, each max 250 chars
- tags: max 8, from controlled vocabulary (see below). Over-cap fields are REJECTED with
  a structured error pointing to the limit — do NOT retry with the same payload, re-trim.

Distribute content across fields rather than packing everything into summary. Use
key_outcomes for COMPLETED WORK items, decisions_made for COORDINATION CONTEXT and
NEXT-STEPS items. If you have more team-state detail than fits, send a separate message
to the continuation orchestrator with the overflow rather than busting the cap.

Controlled tag vocabulary (16, pick ≤ 8): feature, bug-fix, refactor, perf, security,
docs, test, chore, frontend, backend, database, api, infrastructure, ui-ux, integration,
migration. Use 'chore' if nothing else fits.

write_memory_entry(
    project_id="{project_id}",
    entry_type="handover_closeout",
    author_job_id="{job_id}",
    summary="<2-3 sentence headline: what session covered, why handoff is happening,
              and the most critical thing the continuation orchestrator must know first.
              Max 500 chars.>",
    key_outcomes=[
      "<concrete completed outcome 1, max 250 chars>",
      "<concrete completed outcome 2>",
      "<in-progress work + where you stopped>",
      "<team state highlights — name agents, statuses, pending work>",
      "<known blockers if any>"
    ],
    decisions_made=[
      "<architectural/design decision + rationale, max 250 chars>",
      "<next coordination action the continuation orchestrator should take>",
      "<messages you were expecting from agents>",
      "<decisions you were about to make>"
    ],
    tags=["<pick from the 16-tag vocab above, ≤ 8 total>"]
)
{git_closeout_section}
STEP 5 — Confirm to user

Print: "Session context saved to 360 Memory. You may now end this session and start the continuation prompt in a new agent session (terminal, desktop, or web tab). Other agents are unaffected and will continue working."

CRITICAL: Do NOT skip the memory write. The continuation session depends on this context.
CRITICAL: Do NOT call complete_job() on YOUR OWN job. You are NOT done — your work continues in a new agent session.
CRITICAL: Do NOT modify other agents in any way — no force-complete, no message draining, no todo changes.
"""


class ThinClientPromptGenerator(ThinClientLifecycleMixin):
    """Generates thin client prompts for orchestrators.

    Architecture:
    - Prompt contains only identity (~10 lines, 50 tokens)
    - Mission fetched via get_staging_instructions() MCP tool
    - Field priorities applied at fetch time, not embed time

    Platform-specific prompt builders are in giljo_mcp.prompts/ (0950g):
    - ClaudePromptBuilder: Claude Code CLI mode
    - CodexPromptBuilder: Codex CLI mode
    - GeminiPromptBuilder: Gemini CLI mode
    - MultiTerminalPromptBuilder: Platform-agnostic multi-terminal mode
    - StagingPromptBuilder: Staging and mission regeneration
    """

    def __init__(self, db: AsyncSession, tenant_key: str):
        self.db = db
        self.tenant_key = tenant_key
        self._claude_builder = ClaudePromptBuilder()
        self._codex_builder = CodexPromptBuilder()
        self._gemini_builder = GeminiPromptBuilder()
        self._multi_terminal_builder = MultiTerminalPromptBuilder()
        self._staging_builder = StagingPromptBuilder()

    async def generate(
        self,
        project_id: str,
        user_id: str | None = None,
        tool: str = "universal",
        field_toggles: dict[str, bool | None] = None,
        depth_config: dict[str, Any | None] = None,
        continuation_mode: bool = False,
    ) -> dict[str, Any]:
        """Generate a thin orchestrator prompt for a specified project.

        Args:
            project_id: Project UUID
            user_id: Optional user ID for tracking and fetching toggle/depth config
            tool: AI coding agent (claude-code, codex, gemini, universal)
            field_toggles: Optional field toggle config (True=enabled, False=disabled)
            depth_config: Optional depth configuration (v2.0 depth settings)
            continuation_mode: If True, generate continuation prompt (reads 360 Memory)

        Returns:
            Dict with orchestrator_id and thin_prompt
        """
        # BE-5058: ``Project.taxonomy_alias`` is now a SELECT-time
        # column_property, so no eager-load of ``project_type`` is required
        # for sync consumers to read the alias.
        project_stmt = select(Project).where(and_(Project.id == project_id, Project.tenant_key == self.tenant_key))
        project_result = await self.db.execute(project_stmt)
        project = project_result.scalar_one_or_none()

        if not project:
            raise ValueError(f"Project {project_id} not found")

        product = await self._fetch_product(project_id)

        field_toggles, depth_config = await self._resolve_user_config(user_id, field_toggles, depth_config)

        orchestrator_id, agent_id, execution_id = await self._find_or_create_orchestrator(
            project_id, project, field_toggles, depth_config, user_id, tool
        )

        if continuation_mode:
            thin_prompt = self._generate_continuation_prompt(
                project_name=project.name,
                agent_id=agent_id,
                orchestrator_id=orchestrator_id,
                project_id=project_id,
                product_id=str(product.id) if product else None,
                mcp_url="",
            )
        else:
            thin_prompt = self._staging_builder.build_thin_prompt(
                orchestrator_id=orchestrator_id,
                agent_id=agent_id,
                project_id=project_id,
                project=project,
                product=product,
                tool=tool,
                field_toggles=field_toggles or {},
                depth_config=depth_config,
                user_id=user_id,
            )

        estimated_tokens = len(thin_prompt) // 4

        logger.info(
            "[ThinPromptGenerator] Generated thin prompt for %s: ~%d tokens (target: 600, reduction from fat: ~%d)",
            sanitize(str(orchestrator_id)),
            estimated_tokens,
            3500 - estimated_tokens,
        )

        regenerated_mission = self._staging_builder.regenerate_mission(
            product=product, project=project, field_toggles=field_toggles or {}, user_id=user_id
        )

        estimated_mission_tokens = len(regenerated_mission) // 4 if regenerated_mission else 0

        if regenerated_mission:
            logger.info(
                "[ThinPromptGenerator] Regenerated orchestrator instructions for %s: ~%d tokens (reflects current toggle config)",
                sanitize(str(orchestrator_id)),
                estimated_mission_tokens,
            )
        else:
            logger.warning(
                "[ThinPromptGenerator] Mission regeneration returned empty for %s", sanitize(str(orchestrator_id))
            )

        return {
            "orchestrator_id": orchestrator_id,
            "agent_id": agent_id,
            "execution_id": execution_id,
            "thin_prompt": thin_prompt,
            "estimated_prompt_tokens": estimated_tokens,
            "mission": regenerated_mission,
            "estimated_mission_tokens": estimated_mission_tokens,
        }

    async def _resolve_user_config(
        self,
        user_id: str | None,
        field_toggles: dict[str, bool | None] | None,
        depth_config: dict[str, Any | None] | None,
    ) -> tuple[dict | None, dict]:
        """Resolve field toggles and depth config from user preferences if not provided."""
        if user_id and (not field_toggles or not depth_config):
            from giljo_mcp.models.auth import User, UserFieldPriority

            user_stmt = select(User).where(and_(User.id == user_id, User.tenant_key == self.tenant_key))
            user_result = await self.db.execute(user_stmt)
            user = user_result.scalar_one_or_none()

            if user:
                if not field_toggles:
                    prio_result = await self.db.execute(
                        select(UserFieldPriority).where(
                            and_(UserFieldPriority.user_id == user_id, UserFieldPriority.tenant_key == self.tenant_key)
                        )
                    )
                    rows = prio_result.scalars().all()
                    if rows:
                        from giljo_mcp.config.defaults import DEFAULT_CATEGORY_TOGGLES

                        field_toggles = dict(DEFAULT_CATEGORY_TOGGLES)
                        for row in rows:
                            field_toggles[row.category] = row.enabled
                        field_toggles["product_core"] = True
                        field_toggles["project_description"] = True

                if not depth_config:
                    depth_config = {
                        "vision_documents": user.depth_vision_documents,
                        "memory_last_n_projects": user.depth_memory_last_n,
                        "git_commits": user.depth_git_commits,
                        "agent_templates": user.depth_agent_templates,
                        "tech_stack_sections": user.depth_tech_stack_sections,
                        "architecture_depth": user.depth_architecture,
                    }

        if not depth_config:
            depth_config = {
                "vision_documents": "medium",
                "memory_last_n_projects": 3,
                "git_commits": 25,
                "agent_templates": "basic",
                "tech_stack_sections": "all",
                "architecture_depth": "overview",
            }

        return field_toggles, depth_config

    async def _find_or_create_orchestrator(
        self,
        project_id: str,
        project: Project,
        field_toggles: dict | None,
        depth_config: dict,
        user_id: str | None,
        tool: str,
    ) -> tuple[str, str, int]:
        """Find existing orchestrator or create a new one.

        Returns:
            Tuple of (orchestrator_id, agent_id, execution_id)
        """
        existing_exec_stmt = (
            select(AgentExecution)
            .options(joinedload(AgentExecution.job))
            .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
            .where(
                AgentJob.project_id == project_id,
                AgentExecution.agent_display_name == "orchestrator",
                AgentExecution.tenant_key == self.tenant_key,
                ~AgentExecution.status.in_(["decommissioned"]),
            )
            .order_by(AgentExecution.started_at.desc())
        )

        existing_exec_result = await self.db.execute(existing_exec_stmt)
        existing_execution = existing_exec_result.scalars().first()

        if existing_execution:
            orchestrator_id = existing_execution.job_id
            agent_id = existing_execution.agent_id
            execution_id = existing_execution.id

            if existing_execution.job:
                existing_execution.job.job_metadata = validate_agent_job_metadata(
                    {
                        "field_toggles": field_toggles or {},
                        "depth_config": depth_config,
                        "user_id": user_id,
                        "tool": tool,
                        "created_via": "thin_client_generator",
                        "reused_at": str(datetime.now(UTC)),
                    }
                )
                await self.db.commit()

            logger.info(
                f"[ThinPromptGenerator] Reusing existing orchestrator {sanitize(orchestrator_id)} "
                f"for project {sanitize(project_id)} - metadata updated"
            )
        else:
            logger.info(
                f"[ThinPromptGenerator] Creating NEW orchestrator for project {sanitize(project_id)} "
                f"(no active orchestrator found)"
            )

            placeholder_mission = project.mission or f"Orchestrator mission for project: {project.name}"
            orchestrator_id = str(uuid4())
            agent_id = str(uuid4())

            agent_job = AgentJob(
                job_id=orchestrator_id,
                tenant_key=self.tenant_key,
                project_id=project_id,
                mission=placeholder_mission,
                job_type="orchestrator",
                status="active",
                job_metadata=validate_agent_job_metadata(
                    {
                        "field_toggles": field_toggles or {},
                        "depth_config": depth_config,
                        "user_id": user_id,
                        "tool": tool,
                        "created_via": "thin_client_generator",
                    }
                ),
            )
            self.db.add(agent_job)

            # CE-0026: thin_client_generator creation path is the staging
            # session — it also flips project.staging_status to 'staging'
            # below. Mark the execution with project_phase='staging'.
            agent_execution = AgentExecution(
                agent_id=agent_id,
                job_id=orchestrator_id,
                tenant_key=self.tenant_key,
                agent_display_name="orchestrator",
                agent_name="orchestrator",
                status="waiting",
                progress=0,
                tool_type=tool,
                project_phase="staging",
            )
            self.db.add(agent_execution)

            project.staging_status = "staging"
            project.updated_at = datetime.now(UTC)

            await self.db.commit()
            await self.db.refresh(agent_job)
            await self.db.refresh(agent_execution)
            await self.db.refresh(project)

            execution_id = agent_execution.id

            logger.info(
                f"[ThinPromptGenerator] Created orchestrator {orchestrator_id}, project staging_status='staged'"
            )

        return orchestrator_id, agent_id, execution_id

    async def _fetch_product(self, project_id: str) -> Any | None:
        """Fetch product for a given project.

        Args:
            project_id: Project UUID

        Returns:
            Product model or None if not found
        """
        from giljo_mcp.models.products import Product
        from giljo_mcp.models.projects import Project as ProjectModel

        project_stmt = select(ProjectModel).where(
            and_(ProjectModel.id == project_id, ProjectModel.tenant_key == self.tenant_key)
        )
        project_result = await self.db.execute(project_stmt)
        project = project_result.scalar_one_or_none()

        if not project:
            return None

        from sqlalchemy.orm import selectinload

        product_stmt = (
            select(Product)
            .options(
                selectinload(Product.tech_stack),
                selectinload(Product.architecture),
                selectinload(Product.vision_documents),
            )
            .where(and_(Product.id == project.product_id, Product.tenant_key == self.tenant_key))
        )
        product_result = await self.db.execute(product_stmt)
        return product_result.scalar_one_or_none()

    async def _fetch_project(self, project_id: str) -> Any | None:
        """Fetch project by ID."""
        from giljo_mcp.models.projects import Project as ProjectModel

        project_stmt = select(ProjectModel).where(
            and_(ProjectModel.id == project_id, ProjectModel.tenant_key == self.tenant_key)
        )
        project_result = await self.db.execute(project_stmt)
        return project_result.scalar_one_or_none()

    def _get_public_base_url(self) -> str:
        """Get the public MCP server base URL (INF-5012b).

        Prefers GILJO_PUBLIC_URL (set on demo/cloud deployments where the
        server is fronted by a reverse proxy such as Cloudflare Tunnel).
        Falls back to http://localhost:7272 for vanilla CE installs.

        Note: this is used from MCP tool call context where no FastAPI
        Request is available; when a Request is in scope, callers should
        use giljo_mcp.http.url_resolver.get_public_base_url(request)
        instead (honors X-Forwarded-* headers per request).

        BE-9442: thin wrapper over the one accessor; behaviour unchanged.
        """
        return get_public_url()

    async def generate_staging_prompt(
        self,
        orchestrator_id: str,
        project_id: str,
        agent_id: str = None,
        tool: str = "universal",
    ) -> str:
        """Generate thin-client orchestrator staging prompt (Handover 0415).

        Args:
            orchestrator_id: Job ID (WHAT - work order UUID)
            project_id: Project UUID
            agent_id: Agent execution ID (WHO - executor UUID for MCP tool calls)
            tool: AI coding agent harness (claude-code, codex, gemini, universal).
                CE-0035: plumbed through so Claude Code orchestrator spawn prompts
                receive the ToolSearch bootstrap that lets the first MCP call
                succeed without an InputValidationError round-trip.

        Returns:
            Thin staging prompt (~113 tokens) OR continuation prompt for successors

        Raises:
            ValueError: If project or product not found
        """
        project = await self._fetch_project(project_id)
        product = await self._fetch_product(project_id)

        if not project or not product:
            raise ValueError(f"Project {project_id} or its product not found")

        execution = None
        if not agent_id:
            exec_stmt = (
                select(AgentExecution)
                .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
                .where(
                    AgentJob.job_id == orchestrator_id,
                    AgentExecution.tenant_key == self.tenant_key,
                )
            )
            exec_result = await self.db.execute(exec_stmt)
            execution = exec_result.scalars().first()
            if execution:
                agent_id = execution.agent_id
            else:
                agent_id = orchestrator_id  # Fallback (legacy)
        else:
            exec_stmt = select(AgentExecution).where(
                AgentExecution.agent_id == agent_id,
                AgentExecution.tenant_key == self.tenant_key,
            )
            await self.db.execute(exec_stmt)

        mcp_url = self._get_public_base_url()

        return self._staging_builder.build_staging_prompt(
            project=project,
            product=product,
            orchestrator_id=orchestrator_id,
            project_id=project_id,
            agent_id=agent_id,
            mcp_url=mcp_url,
            tool=tool,
        )

    def generate_implementation_prompt(self, prompt_type: str, *, resolved_harness: str | None = None, **kwargs) -> str:
        """Generate an implementation prompt by type.

        Args:
            prompt_type: One of 'multi_terminal_orchestrator', 'claude_code_execution',
                         'codex_execution', 'gemini_execution', 'subagent_execution'
            resolved_harness: BE-9099 — the effective harness token (generic / opencode /
                         ...) that seeds the harness-neutral SubagentPromptBuilder's
                         registry-sourced spawn prose; ignored by the CLI builders.
            **kwargs: Parameters passed to the underlying builder

        Returns:
            The generated prompt string

        Raises:
            ValueError: If prompt_type is unknown
        """
        builders = {
            "multi_terminal_orchestrator": self._multi_terminal_builder,
            "claude_code_execution": self._claude_builder,
            "codex_execution": self._codex_builder,
            "gemini_execution": self._gemini_builder,
            # BE-9099: harness-neutral subagent builder, seeded per-call with the
            # resolved harness so opencode renders its own spawn_syntax and the generic
            # floor renders the universal subagent prose (both from the registry).
            SUBAGENT_EXECUTION_PROMPT_TYPE: SubagentPromptBuilder(resolved_harness),
        }
        builder = builders.get(prompt_type)
        if builder is None:
            raise ValueError(f"Unknown prompt type: {prompt_type}. Valid types: {list(builders.keys())}")
        return builder.build_execution_prompt(**kwargs)

    def _generate_continuation_prompt(
        self,
        project_name: str,
        agent_id: str,
        orchestrator_id: str,
        project_id: str,
        product_id: str | None,
        mcp_url: str,
    ) -> str:
        """Generate continuation prompt. Delegates to module-level build_continuation_prompt()."""
        return build_continuation_prompt(
            project_id=project_id,
            agent_id=agent_id,
            job_id=orchestrator_id,
            project_name=project_name,
            product_id=product_id,
        )
