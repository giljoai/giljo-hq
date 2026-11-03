# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from typing import TYPE_CHECKING

from mcp.server.mcpserver import Context
from starlette.requests import Request as StarletteRequest


if TYPE_CHECKING:
    from mcp.types import ClientCapabilities

from giljo_mcp.harness_resolver import hub_participant_harness, hub_surface_from_app_name, preset_from_client_info
from giljo_mcp.platform_registry import GENERIC_HARNESS, harness_from_client_info, select_effective_preset


def _persisted_harness(ctx: Context) -> str | None:
    try:
        request: StarletteRequest = ctx.request_context.request
        value = request.scope.get("state", {}).get("resolved_harness")
        return value if isinstance(value, str) and value else None
    except Exception:  # noqa: BLE001 - detection is a render hint, never raise into the tool
        return None


def _detected_harness(ctx: Context) -> str:
    try:
        client_info = ctx.session.client_params.client_info
        live = harness_from_client_info(getattr(client_info, "name", None), getattr(client_info, "version", None))
    except Exception:  # noqa: BLE001 - detection is a render hint, never raise into the tool
        live = GENERIC_HARNESS
    if live != GENERIC_HARNESS:
        return live
    return _persisted_harness(ctx) or GENERIC_HARNESS


def _hub_harness(ctx: Context) -> str:
    try:
        name = ctx.request_context.request.scope.get("state", {}).get("mcp_client_name")
    except Exception:  # noqa: BLE001 - a display hint, never raise into the tool
        name = None
    return hub_participant_harness(_detected_harness(ctx), name if isinstance(name, str) else None)


async def _hub_harness_for_call(ctx: Context) -> str:
    harness = _hub_harness(ctx)
    if harness != GENERIC_HARNESS:
        return harness
    try:
        state = ctx.request_context.request.scope.get("state", {})
        family_id, tenant_key = state.get("oauth_family_id"), state.get("tenant_key")
        if not (isinstance(family_id, str) and family_id and isinstance(tenant_key, str) and tenant_key):
            return harness
        from api.app_state import state as app_state
        from giljo_mcp.services import oauth_login_service

        async with app_state.db_manager.get_session_async() as db:
            app_name, mcp_name = await oauth_login_service.login_app_names(
                db, tenant_key=tenant_key, family_id=family_id
            )
    except Exception:  # noqa: BLE001 - a display hint, never raise into the tool
        return harness
    by_client = hub_participant_harness(None, mcp_name)
    if by_client != GENERIC_HARNESS:
        return by_client
    return hub_surface_from_app_name(app_name) or harness


def _persisted_preset(ctx: Context) -> str | None:
    try:
        request: StarletteRequest = ctx.request_context.request
        value = request.scope.get("state", {}).get("resolved_preset")
        return value if isinstance(value, str) and value else None
    except Exception:  # noqa: BLE001 - detection is a render hint, never raise into the tool
        return None


def _detected_preset(ctx: Context) -> str | None:
    try:
        client_info = ctx.session.client_params.client_info
        live = preset_from_client_info(getattr(client_info, "name", None), getattr(client_info, "version", None))
    except Exception:  # noqa: BLE001 - detection is a render hint, never raise into the tool
        live = None
    return live or _persisted_preset(ctx)


_TASKS_EXPERIMENTAL_KEY = "io.modelcontextprotocol/tasks"


def _protocol_capabilities(ctx: Context) -> "ClientCapabilities | None":
    from mcp.types import ClientCapabilities

    try:
        declared = ctx.client_capabilities
    except Exception:  # noqa: BLE001 - capability read must never raise into the tool
        return None
    return declared if isinstance(declared, ClientCapabilities) else None


def get_session_capabilities(ctx: Context) -> dict[str, bool | str | None]:
    from mcp.types import ClientCapabilities, ElicitationCapability

    def _probe(cap: ClientCapabilities) -> bool:
        try:
            return bool(ctx.session.check_client_capability(cap))
        except Exception:  # noqa: BLE001 - capability probe must never raise into the tool
            return False

    declared = _protocol_capabilities(ctx)

    def _supports_elicitation() -> bool:
        if declared is not None:
            return declared.elicitation is not None
        return _probe(ClientCapabilities(elicitation=ElicitationCapability()))

    def _supports_tasks() -> bool:
        if declared is not None:
            return declared.tasks is not None or _TASKS_EXPERIMENTAL_KEY in (declared.experimental or {})
        return _probe(ClientCapabilities(experimental={_TASKS_EXPERIMENTAL_KEY: {}}))

    return {
        "elicitation": _supports_elicitation(),
        "tasks": _supports_tasks(),
        "harness": _detected_harness(ctx),
        "preset": _detected_preset(ctx),
    }


_HARNESS_PARAM_DESCRIPTION = "Session type when there is no terminal: web_sandbox | desktop_app | chat. Omit for a CLI."


def _resolve_preset_name(harness: str, ctx: Context) -> str | None:
    capabilities = get_session_capabilities(ctx) if ctx is not None else None
    preset = select_effective_preset(harness, capabilities)
    return preset.execution_mode if preset is not None else None
