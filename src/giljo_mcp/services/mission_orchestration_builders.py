# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from typing import Any

from giljo_mcp.platform_registry import (
    GENERIC_SUBAGENT_SPAWN_SYNTAX,
    SUBAGENT_EXECUTION_MODES,
    get_harness,
)
from giljo_mcp.services.protocol_builder import _build_orchestrator_protocol
from giljo_mcp.services.vision_hash import (
    compute_vision_inputs_hash,
    vision_inputs_hash_matches_consolidated,
)
from giljo_mcp.system_prompts.identity_provenance import append_identity_source, format_identity_source
from giljo_mcp.system_prompts.service import SCOPE_DEFAULT


logger = logging.getLogger(__name__)


STAGING_FILTER_NOTE = (
    "Filtered to deliverable agents only because you are in the staging phase. "
    "Verification agents (tester, reviewer) become available in the implementation phase, "
    "after deliverable agents complete and produce real artifacts to verify."
)

NO_AGENTS_ASSIGNED_NOTE = (
    "No agents assigned for this product, use your harness default. "
    "Assign agents to this product on the Agents screen to spawn them by name."
)


def build_execution_mode_fields(
    execution_mode: str,
    templates: list,
    job_id: str,
    resolved_harness: str | None = None,
) -> dict[str, Any]:
    fields: dict[str, Any] = {}

    if execution_mode in SUBAGENT_EXECUTION_MODES:
        allowed_agent_names = [t.name for t in templates]

        example_agents = allowed_agent_names[:2] if len(allowed_agent_names) >= 2 else allowed_agent_names
        example_str = ", ".join(f"'{n}'" for n in example_agents) if example_agents else "'implementer'"

        harness = get_harness(resolved_harness)
        task_tool_mapping = harness.spawn_syntax if harness is not None else GENERIC_SUBAGENT_SPAWN_SYNTAX

        fields["cli_mode_rules"] = {
            "agent_name_usage": (
                "SINGLE SOURCE OF TRUTH - binds the DB record to the spawning tool. "
                f"MUST match the agent_name returned by spawn_job exactly (e.g., {example_str})."
            ),
            "agent_display_name_usage": (
                "Dashboard label - what humans see in UI. "
                "MUST be unique per agent instance when spawning multiple agents of same template."
            ),
            "multi_agent_example": {
                "scenario": "Spawning 2 implementers for different domains",
                "agent_1": {"agent_name": "implementer", "agent_display_name": "api-implementer"},
                "agent_2": {"agent_name": "implementer", "agent_display_name": "ui-implementer"},
            },
            "task_tool_mapping": task_tool_mapping,
            "validation": "soft",
        }

        logger.info(
            f"[CLI_MODE_RULES] Added CLI mode rules for orchestrator {job_id}",
            extra={
                "job_id": job_id,
                "execution_mode": execution_mode,
                "allowed_names": allowed_agent_names,
            },
        )
    else:
        fields["phase_assignment_instructions"] = (
            "## Execution Phase Assignment (Multi-Terminal Mode)\n\n"
            "When creating agent jobs with spawn_job, assign a `phase` number to each agent:\n"
            "- Phase 1: Agents that should run first (no dependencies). Usually: analyzer, researcher.\n"
            "- Phase 2: Agents that depend on Phase 1 completion. Usually: implementer, designer.\n"
            "- Phase 3: Agents that depend on Phase 2 completion. Usually: tester, reviewer.\n"
            "- Phase 4+: Final agents. Usually: documenter.\n\n"
            "Agents in the SAME phase can run in parallel (user opens multiple terminals).\n"
            "Higher phases should wait until lower phases complete.\n\n"
            "Use your judgment based on the actual agent team and project requirements."
        )

    return fields


async def build_category_metadata(
    session: Any,
    product: Any | None,
    tenant_key: str,
    repo: Any,
) -> dict[str, dict]:
    metadata: dict[str, dict] = {}
    if not product:
        return metadata

    product_updated = getattr(product, "updated_at", None)
    if product_updated:
        ts = product_updated.strftime("%Y-%m-%dT%H:%M")
        for cat in ("product_core", "vision_documents", "tech_stack", "architecture", "testing"):
            metadata[cat] = {"modified": ts}

    entry_count, max_created = await repo.get_category_metadata(session, tenant_key, product.id)
    if entry_count > 0 and max_created:
        metadata["memory_360"] = {
            "modified": max_created.strftime("%Y-%m-%dT%H:%M"),
            "entries": entry_count,
        }


    return metadata


def maybe_build_ctx_self_close_directive(ctx: dict[str, Any]) -> dict[str, Any] | None:
    if ctx.get("project_type_abbreviation") != "CTX":
        return None
    product = ctx.get("product")
    if product is None:
        return None

    vision_inputs_hash = compute_vision_inputs_hash(getattr(product, "vision_documents", None))
    if not vision_inputs_hash_matches_consolidated(
        vision_inputs_hash, getattr(product, "consolidated_vision_hash", None)
    ):
        return None

    return {
        "action": "SELF_CLOSE",
        "status": "completed",
        "closeout_note": "hash already fresh at project launch",
        "vision_inputs_hash": vision_inputs_hash,
        "consolidated_vision_hash": getattr(product, "consolidated_vision_hash", None),
    }


async def is_chain_member(
    session: Any, project_id: str, tenant_key: str, *, db_manager: Any, tenant_manager: Any
) -> bool:
    try:
        from giljo_mcp.services.sequence_run_service import SequenceRunService

        svc = SequenceRunService(
            db_manager=db_manager,
            tenant_manager=tenant_manager,
            session=session,
        )
        run = await svc.find_active_run_for_project(project_id=str(project_id), tenant_key=tenant_key)
        return run is not None
    except Exception:  # noqa: BLE001 - best-effort chain detection; never break staging
        logger.warning("[BE-6198] chain-member check failed (non-fatal); falling back to solo staging redirect")
        return False


def check_staging_redirect(project: Any, job_id: str, *, is_chain_member: bool = False) -> dict[str, Any] | None:
    if project.staging_status == "staging_complete":
        identity = {
            "job_id": job_id,
            "project_id": str(project.id),
            "project_name": project.name,
        }
        if project.implementation_launched_at is not None:
            return {
                "staging_complete": True,
                "redirect": "get_job_mission",
                "identity": identity,
                "message": (
                    "Implementation is already launched. Your operating protocol and live team "
                    "state are in get_job_mission. "
                    f"Call get_job_mission(job_id='{job_id}') to receive your current team "
                    "state and coordination protocol."
                ),
                "thin_client": True,
            }
        if is_chain_member:
            return {
                "staging_complete": True,
                "redirect": "get_job_mission",
                "identity": identity,
                "message": (
                    "Staging is complete. You are a chain sub-orchestrator -- there is NO "
                    "gate to wait behind. Call get_job_mission now; it returns your "
                    "implementation protocol immediately, then continue implementing -- "
                    "do NOT wait for a human and do NOT return to the dashboard."
                ),
                "thin_client": True,
            }
        return {
            "staging_complete": True,
            "redirect": None,
            "identity": identity,
            "message": (
                "Staging is complete. Return to the dashboard and click Implement to launch "
                "the implementation phase. Then start (or paste) the orchestrator implementation "
                "prompt in your agent session (terminal, desktop, or web tab)."
            ),
            "thin_client": True,
        }
    return None


def build_identity_source_line(ctx: dict[str, Any]) -> str:
    override = ctx.get("orchestrator_override")
    product = ctx.get("product")
    return format_identity_source(
        getattr(override, "scope", None) or SCOPE_DEFAULT,
        updated_at=getattr(override, "updated_at", None),
        product_name=getattr(product, "name", None) if product is not None else None,
    )


def build_orchestrator_identity_block(ctx: dict[str, Any], *, job_id: str, tenant_key: str) -> dict[str, Any]:
    project = ctx["project"]
    product = ctx.get("product")
    return {
        "job_id": job_id,
        "agent_id": ctx["execution"].agent_id,
        "project_id": str(project.id),
        "project_name": project.name,
        "product_id": str(product.id) if product is not None else None,
        "product_name": getattr(product, "name", None) if product is not None else None,
        "identity_source": build_identity_source_line(ctx),
        "tenant_key": tenant_key,
        "id_glossary": {
            "job_id": "Use for: report_progress, complete_job, set_agent_status",
            "agent_id": "Use for: post_to_thread(from_agent), get_thread_history(as_participant)",
            "project_id": "Use for: update_project_mission, spawn_job, get_workflow_status, write_project_closeout",
            "product_id": "Use for: get_context (REQUIRED — product-scoped context)",
        },
    }


def attach_protocol_and_identity(
    response: dict[str, Any],
    *,
    ctx: dict[str, Any],
    protocol_tool: str,
    chain_ctx: Any,
    build_kwargs: dict[str, Any],
) -> None:
    is_chain_suborch = chain_ctx is not None and getattr(chain_ctx, "role", None) == "sub_orchestrator"
    if is_chain_suborch:
        response["protocol_unchanged"] = True
        response["protocol_source"] = "get_job_mission"
        response["protocol_note"] = (
            "Chain sub-orchestrator: your orchestrator identity + full protocol were "
            "delivered at boot by get_job_mission and are unchanged here. Reuse that copy "
            "(re-fetch via get_job_mission(job_id) if not cached). This staging call returns "
            "only the delta: agent_templates, identity IDs, project description, and toggles."
        )
        return

    from giljo_mcp.template_seeder import compose_orchestrator_identity

    response["orchestrator_protocol"] = _build_orchestrator_protocol(**build_kwargs)
    override_content = ctx.get("orchestrator_prompt_override")
    response["orchestrator_identity"] = append_identity_source(
        compose_orchestrator_identity(override_content, tool=protocol_tool),
        build_identity_source_line(ctx),
    )
