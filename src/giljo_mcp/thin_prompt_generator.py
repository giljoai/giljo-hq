# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.http.url_resolver import get_public_url
from giljo_mcp.models import Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.prompts.claude_prompt_builder import ClaudePromptBuilder
from giljo_mcp.prompts.codex_prompt_builder import CodexPromptBuilder
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
   -> Background on the product; the session handover itself is a TASK, read next.

3b. Read the handover your predecessor left:
   list_tasks(product_id="{product_param}", task_type="HND")
   -> Take the most recent one. It carries previous progress, current status and
      next steps, under three headings: what to verify before trusting it, what it
      is waiting on the operator for, and what it could not testify to.
   -> VERIFY ITS CLAIMS BEFORE ACTING ON THEM. Each claim in "Verify before
      trusting" is written next to the command that checks it -- run those. If a
      claim turns out to be false, set that task to Blocked and say which claim.
      Mark it Completed once you have verified it, not once you have read it.

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
- Read the HND handover task for context from the previous session, and verify its claims
- You are CONTINUING work, not starting from scratch
- Agents were NOT terminated during handover — they kept working. Expect them to be in the same or
  more advanced state than described in the handover. Check workflow_status for current truth.
"""

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


class ThinClientPromptGenerator(ThinClientLifecycleMixin):

    def __init__(self, db: AsyncSession, tenant_key: str):
        self.db = db
        self.tenant_key = tenant_key
        self._claude_builder = ClaudePromptBuilder()
        self._codex_builder = CodexPromptBuilder()
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
        project_stmt = select(Project).where(and_(Project.id == project_id, Project.tenant_key == self.tenant_key))
        project_result = await self.db.execute(project_stmt)
        project = project_result.scalar_one_or_none()

        if not project:
            raise ValueError(f"Project {project_id} not found")

        product = await self._fetch_product(project)

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
            "product_id": str(product.id) if product else None,
        }

    async def _resolve_user_config(
        self,
        user_id: str | None,
        field_toggles: dict[str, bool | None] | None,
        depth_config: dict[str, Any | None] | None,
    ) -> tuple[dict | None, dict]:
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

    async def _fetch_product(self, project: Any) -> Any | None:
        from sqlalchemy.orm import selectinload

        from giljo_mcp.models.products import Product

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
        from giljo_mcp.models.projects import Project as ProjectModel

        project_stmt = select(ProjectModel).where(
            and_(ProjectModel.id == project_id, ProjectModel.tenant_key == self.tenant_key)
        )
        project_result = await self.db.execute(project_stmt)
        return project_result.scalar_one_or_none()

    def _get_public_base_url(self) -> str:
        return get_public_url()

    async def generate_staging_prompt(
        self,
        orchestrator_id: str,
        project_id: str,
        agent_id: str = None,
        tool: str = "universal",
    ) -> str:
        project = await self._fetch_project(project_id)
        product = await self._fetch_product(project) if project else None

        if not project or not product:
            raise ValueError(f"Project {project_id} or its product not found")

        if not agent_id:
            exec_stmt = (
                select(AgentExecution)
                .join(AgentJob, AgentExecution.job_id == AgentJob.job_id)
                .where(
                    AgentJob.job_id == orchestrator_id,
                    AgentExecution.tenant_key == self.tenant_key,
                )
            )
            execution = (await self.db.execute(exec_stmt)).scalars().first()
            if execution is None:
                raise ResourceNotFoundError(
                    message=f"Orchestrator job {orchestrator_id} has no execution to address the staging prompt to",
                    context={"orchestrator_id": orchestrator_id, "project_id": project_id},
                )
            agent_id = execution.agent_id

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
        builders = {
            "multi_terminal_orchestrator": self._multi_terminal_builder,
            "claude_code_execution": self._claude_builder,
            "codex_execution": self._codex_builder,
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
        return build_continuation_prompt(
            project_id=project_id,
            agent_id=agent_id,
            job_id=orchestrator_id,
            project_name=project_name,
            product_id=product_id,
        )
