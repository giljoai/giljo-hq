# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context
from pydantic import BaseModel, Field, model_validator

from api.endpoints.mcp_tools import _base
from api.endpoints.mcp_tools._base import (
    _HARNESS_PARAM_DESCRIPTION,
    MCP_ID_MAX,
    MCP_SHORT_TEXT_MAX,
    _call_tool,
    _resolve_preset_name,
    logger,
    mcp,
    validation_rejection,
)
from api.endpoints.mcp_tools._tool_annotations import _tool_hints
from giljo_mcp.platform_registry import (
    EXPORT_PLATFORMS,
    WORKSPACE_SHARED_WORKING_TREE,
    get_preset,
)
from giljo_mcp.services.product_tuning_service import (
    SECTION_FIELD_MAP,
    STRUCTURED_TUNING_SECTIONS,
    TUNING_PROPOSED_VALUE_MAX,
)
from giljo_mcp.utils.log_sanitizer import sanitize


@mcp.tool(
    title="Health Check",
    description="Check MCP server health status.",
    annotations=_tool_hints("health_check"),
)
async def health_check(ctx: Context = None) -> dict[str, Any]:
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
    from giljo_mcp.tools.giljo_guide import build_giljo_guide

    return build_giljo_guide()


@mcp.tool(
    title="Set Up GiljoAI",
    description=(
        "First-time setup: installs the /giljo command/skill and writes the Giljo HQ marker "
        "block (primer + product binding) into your harness file (CLAUDE.md / AGENTS.md). Run "
        "once after connecting; re-run whenever the skills are outdated. It no longer installs "
        "agent templates and has no agent-install scope: every spawned agent receives "
        "its full profile from the server in get_job_mission's agent_profile, so nothing needs "
        "to live in your agents directory (a profile can still be downloaded as Markdown from "
        "the Template Manager). Pass platform identifying your CLI tool "
        "('claude_code'|'codex_cli'|'opencode'|'generic'). NAME YOUR OWN TOOL rather than "
        "accepting the default: the wrong platform installs that platform's skill format into "
        "its directories, which your tool never reads, and nothing errors. On a session with no "
        "home directory (web sandbox / pure chat), pass harness to get the primer and guidance "
        "returned inline instead of file-install instructions. Pass product_id to bind this "
        "repository to a Giljo HQ product: the returned instructions include writing a per-repo "
        "marker block into CLAUDE.md and AGENTS.md so future calls never hit a PRODUCT_AMBIGUOUS "
        "rejection for this repo again. Omit it on a tenant with zero or multiple products -- the "
        "response tells you what to do next (re-run once a product exists, or confirm with the "
        "user which of several to bind). Every tool response carries `_meta.skills_version` (the "
        "server's current bundle). When it is ahead of what was installed here, TELL the user "
        "their Giljo skills are outdated and OFFER to re-run this tool -- NEVER rewrite their "
        "local skill files without that ask; this call only ever installs on an explicit, "
        "deliberate invocation."
    ),
    annotations=_tool_hints("giljo_setup"),
)
async def giljo_setup(
    platform: Literal[EXPORT_PLATFORMS] = "claude_code",
    harness: Annotated[str, Field(max_length=MCP_ID_MAX, description=_HARNESS_PARAM_DESCRIPTION)] = "",
    product_id: Annotated[
        str,
        Field(
            max_length=MCP_ID_MAX,
            description=(
                "Optional Giljo HQ product UUID to bind this repository to. Omit on a "
                "tenant with zero or multiple products -- never guess which one to bind."
            ),
        ),
    ] = "",
    scope: Annotated[
        str,
        Field(
            max_length=32,
            description=(
                "RETIRED. giljo_setup no longer takes an install scope (agents / both / commands "
                "only); any value is refused with a structured rejection. Omit it."
            ),
        ),
    ] = "",
    ctx: Context = None,
) -> dict[str, Any]:
    if scope.strip():
        return validation_rejection(
            field="scope",
            constraint="retired",
            message=(
                "giljo_setup no longer installs or refreshes agent templates, so there is no "
                "agent-install scope: every spawned agent receives its full profile from the "
                "server in get_job_mission's agent_profile. To hand a profile to your own harness "
                "agent, use the Template Manager's per-agent menu -> Download profile (.md). "
                "Re-run giljo_setup without scope to refresh the skills and the marker block."
            ),
        )

    logger.info(
        "giljo_setup called with platform=%s harness=%s product_id=%s",
        sanitize(platform),
        sanitize(harness),
        sanitize(product_id),
    )

    user_id = _base._resolve_user_id(ctx)

    preset = get_preset(_resolve_preset_name(harness, ctx))
    if preset is not None and preset.workspace_model != WORKSPACE_SHARED_WORKING_TREE:
        from giljo_mcp.tools.setup_instructions import build_inline_primer_note

        result: dict[str, Any] = {
            "mode": "inline",
            "message": (
                f"This session ({preset.display_label}) has no home directory to install into, so "
                "GiljoAI setup runs fully inline: there is no slash-command/skill install step here. "
                "Agent templates are not installed anywhere any more -- every spawned agent receives "
                "its full profile from the server in get_job_mission's agent_profile. For ongoing "
                "project/task routing guidance (the equivalent of the /giljo command), call "
                "get_giljo_guide on demand. There is no repo to write a product binding block into "
                "either: this session's product identity comes from passing product_id on every "
                "giljo_hq call, and from the active session, not from a file."
            ),
            "primer": build_inline_primer_note(),
        }
    else:
        result = await _call_tool(
            ctx,
            "bootstrap_setup",
            {
                "platform": platform,
                "user_id": user_id,
                "harness": _resolve_preset_name(harness, ctx),
                "product_id": product_id,
            },
        )

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




class _TuningProposal(BaseModel):
    """One reviewed context-tuning proposal (BE-9118 typed-boundary model).

    Replaces the former ``list[dict]`` proposals param. Structural + type validation
    (required section/drift_detected, proposed_value shape + per-string length cap,
    confidence enum) happens at the FastMCP arg-validation boundary as a clean
    422-style ToolError, instead of the aggregated ValueError string raised by
    ``giljo_mcp.tools.submit_tuning_review._validate_proposals``.
    BE-9473: ``_validate_shape_and_size`` below also checks section MEMBERSHIP at
    the boundary now (an unknown section is rejected here, not passed through to
    that function). ``submit_tuning_review._validate_proposals`` -- a TOOL-layer
    function, not a service method -- stays as defense-in-depth for the non-MCP
    caller, and still owns ``target_platforms`` item-type checking -- that
    symmetry is NOT assumed, it is simply unchanged by this project.
    ``extra="allow"`` tolerates the informational keys the served tuning prompt
    includes so the model need not enumerate every one.

    BE-9473 (F2): the length cap used to be a per-field validator that fired on
    ``proposed_value`` alone, with no visibility into ``section`` -- so a
    STRUCTURED section (tech_stack/architecture: multiple fields) sent as one
    oversized flat string was rejected for its length, and the real problem (wrong
    shape -- address it by sub-key) stayed hidden behind however many resubmits it
    took to shrink the string under the cap. ``_validate_shape_and_size`` runs
    AFTER the whole model is built (``mode="after"``), so it sees ``section`` and
    ``proposed_value`` together and reports the SHAPE problem on the first
    rejection, before size is even considered.

    Shape wins over size for a stronger reason than redundancy: the cap is PER
    SUB-KEY, and a flat string sent for a structured section has no sub-keys, so
    there is no cap it is actually violating. Reporting "exceeds 10000 characters"
    against it would be a precise-looking number measured against a rule that does
    not apply to what was sent -- a confident, wrong answer, the defect class this
    validation exists to prevent. The test that settles it: shortening the blob
    still fails (wrong shape, still no sub-keys);
    fixing the shape lets the call proceed, and each corrected sub-value is then
    capped against the rule that genuinely governs it, below. Shape's remedy works;
    size's does not -- that is why shape is reported and size is not.
    """

    model_config = {"extra": "allow"}

    section: str
    drift_detected: bool
    proposed_value: str | dict | list | None = None
    confidence: Literal["high", "medium", "low"] | None = None
    current_summary: str | None = None
    evidence: str | None = None
    reasoning: str | None = None

    @model_validator(mode="after")
    def _validate_shape_and_size(self) -> "_TuningProposal":
        if self.section not in SECTION_FIELD_MAP:
            raise ValueError(f"unknown section {self.section!r}, must be one of {sorted(SECTION_FIELD_MAP)}")

        v = self.proposed_value
        if v is None:
            if self.drift_detected:
                raise ValueError(
                    "drift_detected=True requires a non-null proposed_value "
                    "(pass drift_detected=false if nothing needs to change)."
                )
            return self

        if self.section in STRUCTURED_TUNING_SECTIONS:
            known_fields = SECTION_FIELD_MAP[self.section].get("fields", {})
            if isinstance(v, str):
                subkeys = sorted(f"{self.section}.{f}" for f in known_fields)
                raise ValueError(
                    f"'{self.section}' is a structured, multi-field section -- a single string "
                    f"is not a valid proposed_value for it. Address ONE field via a dotted "
                    f"sub-key ({subkeys}), or pass proposed_value as a dict keyed by field name "
                    f"to update several fields in one proposal."
                )
            if isinstance(v, dict):
                problems = []
                for key, sub_value in v.items():
                    if key not in known_fields:
                        problems.append(f"unknown sub-key '{key}', must be one of {sorted(known_fields)}")
                    elif isinstance(sub_value, str) and len(sub_value) > TUNING_PROPOSED_VALUE_MAX:
                        problems.append(
                            f"sub-key '{key}' exceeds {TUNING_PROPOSED_VALUE_MAX} character "
                            f"limit ({len(sub_value)} chars)"
                        )
                if problems:
                    raise ValueError("; ".join(problems))
            return self

        if isinstance(v, str) and len(v) > TUNING_PROPOSED_VALUE_MAX:
            raise ValueError(f"proposed_value exceeds {TUNING_PROPOSED_VALUE_MAX} character limit ({len(v)} chars)")
        return self


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
                "Per-section proposals. Each item: {section: str, drift_detected: bool "
                "(required), proposed_value: str|dict|list (required when drift_detected=True), "
                "confidence: 'high'|'medium'|'low' (optional)}. FLAT sections take a plain "
                "string (list[str] for target_platforms): 'description', 'core_features', "
                "'brand_guidelines', 'quality_standards', 'target_platforms'. STRUCTURED "
                "sections -- 'tech_stack', 'architecture' -- hold multiple fields, so a plain "
                "string is REJECTED for them: address one field per proposal via a dotted "
                "sub-key ('tech_stack.infrastructure', 'architecture.primary_pattern', ...), or "
                "pass proposed_value as a dict keyed by field name to update several fields at "
                "once. An unknown section is rejected with the full allowed list. "
                f"proposed_value is capped at {TUNING_PROPOSED_VALUE_MAX} chars PER STRING (per "
                "sub-key inside a dict, not the whole submission). Every problem across every "
                "proposal is reported together in one rejection. Updating a field that already "
                "holds a value needs force=true -- see the force param."
            )
        ),
    ],
    overall_summary: Annotated[str, Field(max_length=MCP_SHORT_TEXT_MAX)] = "",
    force: Annotated[
        bool,
        Field(
            description=(
                "Updating a product field that is already populated is rejected with 'Fields "
                "already populated: <detail>' unless force=True. Reviewing an existing product "
                "is the COMMON case, so most calls that touch tech_stack, architecture, or "
                "quality_standards on a product that already has values need force=True."
            )
        ),
    ] = False,
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
