# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Setup & Misc Tools -- @mcp.tool wrappers (BE-6042d split of mcp_sdk_server.py).

Mechanically extracted verbatim from the pre-split ``mcp_sdk_server.py``. Each
wrapper registers against the shared ``mcp`` instance from ``_base`` as a decorator
side effect at import time. Behavior, signatures, names, and descriptions unchanged.
"""

from typing import Annotated, Any, Literal

from mcp.server.fastmcp import Context
from pydantic import BaseModel, Field, field_validator

from api.endpoints.mcp_tools import _base
from api.endpoints.mcp_tools._base import (
    _HARNESS_PARAM_DESCRIPTION,
    MCP_ID_MAX,
    MCP_SHORT_TEXT_MAX,
    _call_tool,
    _resolve_preset_name,
    logger,
    mcp,
)
from api.endpoints.mcp_tools._tool_annotations import _tool_hints
from giljo_mcp import branding
from giljo_mcp.platform_registry import (
    EXPORT_GENERIC,
    EXPORT_PLATFORMS,
    WORKSPACE_NONE,
    WORKSPACE_SHARED_WORKING_TREE,
    get_preset,
)


@mcp.tool(
    title="Health Check",
    description=f"Check MCP server health status. {branding.TWO_HUB_DISAMBIGUATION}",
    annotations=_tool_hints("health_check"),
)
async def health_check(ctx: Context = None) -> dict[str, Any]:
    # BE-3010b: call the OrchestrationService static directly. health_check is
    # tenant-independent and never went through _call_tool; routing it past the
    # ToolAccessor shim removes the last non-dispatch accessor caller.
    from giljo_mcp.services.orchestration_service import OrchestrationService

    return await OrchestrationService.health_check()


@mcp.tool(
    title="Get GiljoAI Guide",
    description=(
        "Return the GiljoAI cross-tool guide: the routing/judgment layer for the project/task "
        "tools (chain convention, Edition Scope, read-vs-write routing, the staging -> human-gate "
        "-> implement lifecycle). No arguments. Call once, early, to become competent before "
        "creating or reading projects and tasks."
    ),
    annotations=_tool_hints("get_giljo_guide"),
)
async def get_giljo_guide(ctx: Context = None) -> dict[str, Any]:
    # Static, tenant-independent content -- no _call_tool / accessor dispatch needed.
    from giljo_mcp.tools.giljo_guide import build_giljo_guide

    return build_giljo_guide()


@mcp.tool(
    title="Set Up GiljoAI",
    description=(
        "First-time setup: installs the /giljo command/skill and agent templates. Run once after "
        "connecting; re-run with the 'Agents only' scope to refresh templates later. Pass platform "
        "identifying your CLI tool ('claude_code'|'gemini_cli'|'codex_cli'|'antigravity_cli'). On a "
        "session with no home directory (web sandbox / pure chat), pass harness to get templates "
        "and guidance returned inline instead of file-install instructions."
    ),
    annotations=_tool_hints("giljo_setup"),
)
async def giljo_setup(
    # BE-9035a: derived from the registry's EXPORT_PLATFORMS (was a hand-copied
    # literal that would silently drift if a new export platform were added).
    platform: Literal[EXPORT_PLATFORMS] = "claude_code",
    harness: Annotated[str, Field(max_length=MCP_ID_MAX, description=_HARNESS_PARAM_DESCRIPTION)] = "",
    ctx: Context = None,
) -> dict[str, Any]:
    logger.info("giljo_setup called with platform=%s harness=%s", platform, harness)

    # HO 1028: pass authenticated user_id so the staging layer can stamp the
    # installed skills version through UserService (single write path).
    # BE-6042d: resolve through the _base module so the in-memory-transport
    # monkeypatch (which targets _base) reaches these direct calls too.
    user_id = _base._resolve_user_id(ctx)

    # BE-8003g: a session whose resolved harness preset has no real home directory
    # (web_sandbox, chat) cannot execute any of build_setup_instructions' filesystem
    # writes. desktop_app stays on the normal path -- its workspace_model IS
    # shared_working_tree (a real home dir), same as every CLI.
    preset = get_preset(_resolve_preset_name(harness, ctx))
    if preset is not None and preset.workspace_model != WORKSPACE_SHARED_WORKING_TREE:
        from giljo_mcp.tools.setup_instructions import build_inline_primer_note

        # BE-9327: request the PLATFORM-NEUTRAL renderer, ignoring the caller's
        # file-install platform. ``platform`` defaults to claude_code and was forwarded
        # unchanged, so a chat client correctly asking for inline templates received
        # Claude Code markdown -- YAML frontmatter, a ``color`` field, and a per-agent
        # ``filename`` for a file it has nowhere to write. The override is
        # unconditional inside this branch because the branch condition IS "this
        # session has no filesystem", which no declared platform can change.
        result = await _call_tool(ctx, "list_agent_templates", {"platform": EXPORT_GENERIC})
        result.pop("install_paths", None)
        # AUDIT-9327 F1: strip the per-agent ``filename`` only for a session with NO
        # filesystem at all. This branch is entered by web_sandbox too, but that preset
        # carries WORKSPACE_ISOLATED_PR -- an isolated PR checkout it CAN write to -- so
        # it keeps the suggested name. Only WORKSPACE_NONE (pure chat) has nowhere to put
        # a file and would be handed a name it cannot use. The renderer override above
        # stays unconditional: neither preset wants claude_code frontmatter.
        if preset.workspace_model == WORKSPACE_NONE:
            for agent in result.get("agents", []):
                if isinstance(agent, dict):
                    agent.pop("filename", None)
        result["mode"] = "inline"
        result["message"] = (
            f"This session ({preset.display_label}) has no home directory to install into, so "
            "GiljoAI setup runs fully inline: there is no slash-command/skill install step here. "
            "The agent templates below are returned directly in this response instead of files "
            "written to a local path. For ongoing project/task routing guidance (the equivalent of "
            "the /giljo command), call get_giljo_guide on demand."
        )
        # BE-9067: teach the connecting agent the platform mental model durably --
        # this session has no file to write, so route to memory or keep in-context.
        result["primer"] = build_inline_primer_note()
    else:
        result = await _call_tool(ctx, "bootstrap_setup", {"platform": platform, "user_id": user_id})

    # IMP-6038: record THIS tenant's acknowledgement of the bundled
    # SKILLS_VERSION through the tenant-scoped service (single validated write
    # path; tenant_key filter enforced by the guard). This is the banner's
    # clear-path: one tenant re-running /giljo_setup resolves only its own
    # skills-drift banner on the next emit cycle.
    try:
        from api.app_state import state as app_state
        from giljo_mcp.services.settings_service import TenantSkillsAckService
        from giljo_mcp.tools.slash_command_templates import SKILLS_VERSION

        tenant_key = _base._resolve_tenant(ctx)
        async with app_state.db_manager.get_session_async() as session:
            ack_service = TenantSkillsAckService(session, tenant_key)
            await ack_service.acknowledge(SKILLS_VERSION)
    except (OSError, RuntimeError, ValueError, TypeError, AttributeError, ImportError, KeyError) as e:
        logger.warning("giljo_setup skills ack write failed: %s: %s", type(e).__name__, e)

    # Emit setup:bootstrap_complete WebSocket event
    try:
        from api.app_state import state as app_state

        ws_manager = getattr(app_state, "websocket_manager", None)
        tenant_key = _base._resolve_tenant(ctx)
        if ws_manager and tenant_key:
            from giljo_mcp.events.schemas import EventFactory

            event = EventFactory.tenant_envelope(
                event_type="setup:bootstrap_complete",
                tenant_key=tenant_key,
                data={"platform": platform},
            )
            await ws_manager.broadcast_event_to_tenant(tenant_key=tenant_key, event=event)
    except (OSError, RuntimeError, ValueError, TypeError, AttributeError, ImportError, KeyError) as e:
        logger.warning(f"setup:bootstrap_complete emission failed: {type(e).__name__}: {e}")

    return result


# INF-6111b: the generate_download_token @mcp.tool wrapper was RETIRED (the one
# proven dead cut: no live MCP callers; install/agent flows route through
# giljo_setup). The REST route POST /api/download/generate-token
# (api/endpoints/downloads.py) is KEPT.
#
# BE-6225a: the list_agent_templates @mcp.tool wrapper was RETIRED (no live agent
# caller — giljo_setup "Agents only" scope installs templates and
# get_context(categories=['agent_templates']) reads their content). The
# ToolAccessor.list_agent_templates accessor leg + the REST download path are KEPT
# for the non-tool callers (e.g. claude_export.py). BE-8003g: giljo_setup's
# no-filesystem inline branch above is now one of those non-tool callers too, via
# _call_tool's dispatch (not a new @mcp.tool registration).


# BE-9118: preserve the pre-typed submit_tuning_review proposed_value string cap.
_TUNING_PROPOSED_VALUE_MAX = 10_000


class _TuningProposal(BaseModel):
    """One reviewed context-tuning proposal (BE-9118 typed-boundary model).

    Replaces the former ``list[dict]`` proposals param. Structural + type validation
    (required section/drift_detected, proposed_value type + length cap, confidence
    enum) now happens at the FastMCP arg-validation boundary as a clean 422-style
    ToolError, instead of the service's aggregated ValueError string. The service's
    ``_validate_proposals`` stays as defense-in-depth for the non-MCP caller and for
    semantics the boundary intentionally leaves to it (section membership +
    target_platforms item types). ``extra="allow"`` tolerates the informational keys
    the served tuning prompt includes so the model need not enumerate every one.
    """

    model_config = {"extra": "allow"}

    section: str
    drift_detected: bool
    proposed_value: str | dict | list | None = None
    confidence: Literal["high", "medium", "low"] | None = None
    current_summary: str | None = None
    evidence: str | None = None
    reasoning: str | None = None

    @field_validator("proposed_value")
    @classmethod
    def _cap_proposed_value(cls, v: Any) -> Any:
        if isinstance(v, str) and len(v) > _TUNING_PROPOSED_VALUE_MAX:
            raise ValueError(
                f"proposed_value string exceeds {_TUNING_PROPOSED_VALUE_MAX} character limit ({len(v)} chars)"
            )
        return v


@mcp.tool(
    title="Apply Context Tuning",
    description=(
        "Apply reviewed product context tuning directly to product fields, comparing current "
        "context against recent project history. Approved proposals are written immediately -- no "
        "separate dashboard review step. See the proposals param for its exact per-item shape."
    ),
    annotations=_tool_hints("apply_context_tuning"),
)
async def apply_context_tuning(
    product_id: Annotated[str, Field(max_length=MCP_ID_MAX)],
    proposals: Annotated[
        list[_TuningProposal],
        Field(
            description=(
                "Per-section proposals. Each item: {section: str (e.g. "
                "'tech_stack.backend_frameworks', 'architecture.api_style', 'core_features' -- an "
                "unknown value is rejected with the full allowed list), drift_detected: bool "
                "(required), proposed_value: str|dict|list (required when drift_detected=True; str "
                "<=10000 chars, list[str] for target_platforms), confidence: 'high'|'medium'|'low' "
                "(optional)}."
            )
        ),
    ],
    overall_summary: Annotated[str, Field(max_length=MCP_SHORT_TEXT_MAX)] = "",
    force: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "product_id": product_id,
        "proposals": [p.model_dump() for p in proposals],
    }
    if overall_summary:
        kwargs["overall_summary"] = overall_summary
    if force:
        kwargs["force"] = True
    return await _call_tool(ctx, "apply_context_tuning", kwargs)
