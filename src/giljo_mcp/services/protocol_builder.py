# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    ch3 = _build_ch3_spawning_rules(effective_tool, preset=preset)
    ch_authority = _build_ch_orchestrator_authority(cli_mode)
    ch4 = _build_ch4_error_handling()
    ch5 = (
        _build_ch5_reference(project_id, orchestrator_id, effective_tool, git_integration_enabled)
        if include_implementation_reference
        else None
    )
    ch6 = (
        _build_ch6_auto_checkin(auto_checkin_interval) if (include_implementation_reference and not cli_mode) else None
    )


    is_conductor_chain = chain_ctx is not None and chain_ctx.role == "conductor"
    ch_capability: str | None = None
    ch_chain_staging: str | None = None
    ch_chain_drive: str | None = None
    ch_sub_orchestrator: str | None = None

    if chain_ctx is not None and chain_ctx.role == "sub_orchestrator":
        order = chain_ctx.resolved_order or []
        if project_id in order:
            ch_sub_orchestrator = _build_ch_sub_orchestrator(
                run_id=chain_ctx.run_id,
                position=order.index(project_id) + 1,
                n_projects=len(order),
                execution_mode=chain_ctx.execution_mode,
                chain_mission=chain_ctx.chain_mission,
            )

    if is_conductor_chain:
        chain_mode = chain_ctx.execution_mode
        platform = get_platform(chain_mode)
        can_spawn = platform.can_spawn_terminals if platform is not None else True
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
                detected_harness=detected_harness,
            )

    chapters: dict[str, Any] = {}
    if ch_capability:
        chapters["ch_capability"] = ch_capability
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
