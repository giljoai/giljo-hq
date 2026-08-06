# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Protocol Builder - Compositor for orchestrator protocol chapters.

Handover 0750e2: Extracted from orchestration_service.py.
Handover 0950j: Section builders moved to protocol_sections/ subpackage.
This module retains the compositor function and re-exports for backward compatibility.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from giljo_mcp.platform_registry import Platform, get_platform
from giljo_mcp.services.protocol_sections.agent_lifecycle import (
    _generate_orchestrator_protocol,
)
from giljo_mcp.services.protocol_sections.agent_protocol import (
    _generate_agent_protocol,
)
from giljo_mcp.services.protocol_sections.chapters_chain import (
    _build_ch_capability,
    _build_ch_chain_drive,
    _build_ch_chain_staging,
    _build_ch_sub_orchestrator,
)
from giljo_mcp.services.protocol_sections.chapters_coordination import (
    _build_ch_orchestrator_authority,
)
from giljo_mcp.services.protocol_sections.chapters_reference import (
    _build_ch3_spawning_rules,
    _build_ch4_error_handling,
    _build_ch5_reference,
    _build_ch6_auto_checkin,
)
from giljo_mcp.services.protocol_sections.chapters_startup import (
    _build_ch1_mission,
    _build_ch2_startup,
)
from giljo_mcp.services.protocol_sections.team_context import (
    _generate_team_context_header,
)
from giljo_mcp.services.protocol_sections.user_config import (
    DEFAULT_DEPTH_CONFIG,
    DEFAULT_FIELD_PRIORITIES,
    _get_user_config,
    _normalize_field_toggles,
)


if TYPE_CHECKING:
    from giljo_mcp.services.sequence_chain_context import ChainContext


logger = logging.getLogger(__name__)

# Re-export all section functions for backward compatibility
__all__ = [
    "DEFAULT_DEPTH_CONFIG",
    "DEFAULT_FIELD_PRIORITIES",
    "_build_ch1_mission",
    "_build_ch2_startup",
    "_build_ch3_spawning_rules",
    "_build_ch4_error_handling",
    "_build_ch5_reference",
    "_build_ch6_auto_checkin",
    "_build_ch_capability",
    "_build_ch_chain_drive",
    "_build_ch_chain_staging",
    "_build_orchestrator_protocol",
    "_generate_agent_protocol",
    "_generate_orchestrator_protocol",
    "_generate_team_context_header",
    "_get_user_config",
    "_normalize_field_toggles",
]


def _build_orchestrator_protocol(
    cli_mode: bool,
    project_id: str,
    orchestrator_id: str,
    tenant_key: str,
    include_implementation_reference: bool = True,
    field_toggles: dict[str, bool] | None = None,
    depth_config: dict[str, Any] | None = None,
    product_id: str | None = None,
    tool: str = "multi_terminal",
    auto_checkin_enabled: bool = False,
    auto_checkin_interval: int = 10,
    git_integration_enabled: bool = False,
    category_metadata: dict[str, dict] | None = None,
    conductor_agent_id: str | None = None,
    chain_ctx: ChainContext | None = None,
    preset: Platform | None = None,
    detected_harness: str | None = None,
) -> dict:
    """
    Build chapter-based orchestrator protocol.

    Creates 5-6 navigable chapters with clear visual boundaries.
    Solves the "rotation problem" where content gets buried.

    Args:
        cli_mode: True if execution_mode is any CLI subagent mode
        project_id: Project UUID for parameter substitution
        orchestrator_id: Job ID for parameter substitution
        tenant_key: Tenant key for parameter substitution
        include_implementation_reference: Include CH5 (default True)
        field_toggles: Category toggles for inline fetch injection (Handover 0823)
        depth_config: Depth settings per category (Handover 0823)
        product_id: Product UUID for fetch calls (Handover 0823)
        tool: Platform identifier for platform-specific spawning rules (Handover 0838)
        auto_checkin_enabled: Enable CH6 auto check-in protocol (Handover 0904)
        auto_checkin_interval: Check-in interval in minutes (Handover 0904/0960)
        conductor_agent_id: When set, the orchestrator is the conductor of a
            sequential multi-project run (BE-6131c). BE-6215: the addressability +
            user-directive-relay protocol it used to gate (CH_CONDUCTOR) is now folded
            into CH_CHAIN_DRIVE, which derives conductor-ness from chain_ctx.role and
            renders the relay inline; this param is retained for signature stability.
            Omit for single-project orchestrators.
        chain_ctx: BE-6165d -- resolved ChainContext from the sequence driver.
            When non-None AND role=="conductor", injects CH_CAPABILITY (always),
            CH_CHAIN_STAGING (staging phase) or CH_CHAIN_DRIVE (implementation
            phase). chain_ctx=None → byte-identical solo render (Deletion Test
            holds). Sub-orchestrators (role=="sub_orchestrator") also produce no
            chain chapters.

    Returns:
        Dict with chapter keys and navigation_hint
    """
    effective_tool = tool if cli_mode else "multi_terminal"
    ch1 = _build_ch1_mission(effective_tool)
    ch2 = _build_ch2_startup(
        orchestrator_id,
        project_id,
        field_toggles=field_toggles,
        depth_config=depth_config,
        product_id=product_id,
        tenant_key=tenant_key,
        category_metadata=category_metadata,
    )
    # BE-9013: thread the resolved harness preset so the generic_mcp CH3 block can
    # tune its SELF-ADOPT fallback rung (chat harness → planning/PM jobs only). preset
    # is None on every non-generic path → byte-identical render for the other tools.
    ch3 = _build_ch3_spawning_rules(effective_tool, preset=preset)
    # BE-6008: orchestrator authority rule + mode-specific staging mechanics
    # (multi_terminal: create all agents then write jobs; CLI: drain inbox at
    # mission-write time). cli_mode already distinguishes the two flows.
    ch_authority = _build_ch_orchestrator_authority(cli_mode)
    ch4 = _build_ch4_error_handling()
    # CE-0033 Task 7: omit ch5/ch6 entirely when not applicable instead of
    # emitting empty strings. Empty string keys read as "WIP / forgotten" to
    # the orchestrator; omitting them makes the response shape match the
    # active flow.
    ch5 = (
        _build_ch5_reference(project_id, orchestrator_id, effective_tool, git_integration_enabled)
        if include_implementation_reference
        else None
    )
    ch6 = _build_ch6_auto_checkin(auto_checkin_interval) if (auto_checkin_enabled and not cli_mode) else None

    # BE-6215: CH_CONDUCTOR (addressability + directive relay) is FOLDED into
    # CH_CHAIN_DRIVE — both were already phase-gated to the IMPLEMENTATION phase and
    # only ever co-rendered, so the separate chapter was pure overhead. The drive
    # chapter (built below, drive phase only) now renders the relay protocol inline
    # from the conductor_agent_id + job_id it already receives.

    # BE-6165d: chain chapters — only when this orchestrator is the conductor of a
    # sequential multi-project run (chain_ctx non-None AND role=="conductor").
    # chain_ctx=None (solo) or role=="sub_orchestrator" → no chain chapters rendered,
    # preserving byte-identical solo output (Deletion Test holds; all CE).
    is_conductor_chain = chain_ctx is not None and chain_ctx.role == "conductor"
    ch_capability: str | None = None
    ch_chain_staging: str | None = None
    ch_chain_drive: str | None = None
    ch_sub_orchestrator: str | None = None

    # BE-6187: a sub_orchestrator chain member (every project's own orchestrator
    # after BE-6184) gets CH_SUB_ORCHESTRATOR — its chain position, the Hub thread
    # discovery path (get_context(categories=["chain"]) -> hub_thread_id), and the
    # close-out advance signal.
    # Rendered for both staging and runtime; the runtime injector mirrors this for
    # the chain-blind runtime mission path. Solo (chain_ctx=None) renders nothing
    # (Deletion Test holds).
    if chain_ctx is not None and chain_ctx.role == "sub_orchestrator":
        order = chain_ctx.resolved_order or []
        if project_id in order:
            ch_sub_orchestrator = _build_ch_sub_orchestrator(
                run_id=chain_ctx.run_id,
                position=order.index(project_id) + 1,
                n_projects=len(order),
                execution_mode=chain_ctx.execution_mode,
                chain_mission=chain_ctx.chain_mission,  # BE-6196: inline the live contract
            )

    if is_conductor_chain:
        # BE-6177: drive the chain chapters off the RUN's execution_mode
        # (claude_code_cli...), NOT effective_tool (claude-code). get_platform is
        # keyed by execution_mode, so the tool form returned None → can_spawn
        # defaulted wrong; and the chapters need the execution_mode to emit the
        # correct stage_project short `mode` token.
        chain_mode = chain_ctx.execution_mode
        platform = get_platform(chain_mode)
        can_spawn = platform.can_spawn_terminals if platform is not None else True
        # BE-8003f (D2 activation): a resolved harness ``preset`` (shell-less
        # web_sandbox/desktop_app/chat) switches CH_CAPABILITY + CH_CHAIN_DRIVE to their
        # inline-conducting ladder; preset=None keeps today's fresh-terminal bytes (D1).
        ch_capability = _build_ch_capability(
            execution_mode=chain_mode,
            can_spawn_terminals=can_spawn,
            preset=preset,
        )
        if chain_ctx.is_staging:
            ch_chain_staging = _build_ch_chain_staging(
                run_id=chain_ctx.run_id,
                resolved_order=chain_ctx.resolved_order,
                execution_mode=chain_mode,
                job_id=orchestrator_id,
            )
        else:
            ch_chain_drive = _build_ch_chain_drive(
                run_id=chain_ctx.run_id,
                resolved_order=chain_ctx.resolved_order,
                current_index=chain_ctx.current_index,
                execution_mode=chain_mode,
                conductor_agent_id=chain_ctx.conductor_agent_id,
                job_id=orchestrator_id,
                preset=preset,
                detected_harness=detected_harness,  # BE-9092: narrow the multi_terminal spawn matrix
            )

    chapters: dict[str, Any] = {}
    # CH_CAPABILITY first — the "who am I" preamble before any other chain chapters.
    if ch_capability:
        chapters["ch_capability"] = ch_capability
    # CH_CHAIN_STAGING above CH1 per spec.
    if ch_chain_staging:
        chapters["ch_chain_staging"] = ch_chain_staging
    if ch_sub_orchestrator:
        chapters["ch_sub_orchestrator"] = ch_sub_orchestrator
    chapters["ch1_your_mission"] = ch1
    chapters["ch2_startup_sequence"] = ch2
    chapters["ch3_agent_spawning_rules"] = ch3
    chapters["ch_authority"] = ch_authority
    chapters["ch4_error_handling"] = ch4
    if ch_chain_drive:
        chapters["ch_chain_drive"] = ch_chain_drive
    if ch5:
        chapters["ch5_reference"] = ch5
    if ch6:
        chapters["ch6_auto_checkin"] = ch6
    chapters["navigation_hint"] = "Reference chapters by name (e.g., 'see CH4 for error handling')"
    return chapters
