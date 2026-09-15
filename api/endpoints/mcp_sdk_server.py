# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from contextvars import ContextVar

from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import CallToolResult, TextContent
from pydantic import ValidationError as PydanticValidationError
from starlette.requests import Request as StarletteRequest

import api.endpoints.mcp_tools  # noqa: F401  (import for registration side effect)

from api.endpoints.mcp_absorption_diagnosis import describe_absorbed_argument

from api.endpoints.mcp_auth_middleware import (  # noqa: F401  (re-export surface)
    MCPAuthMiddleware,
    McpPostAuthGate,
    clear_mcp_post_auth_gate,
    register_mcp_post_auth_gate,
)
from api.endpoints.mcp_tools import (  # noqa: F401  (re-export surface)
    _HITL_FENCED_TOOLS,
    _LAUNCH_GATE_TOOLS,
    _ORCHESTRATOR_PROFILE_TOOLS,
    PROFILE_CORE,
    PROFILE_FULL,
    PROFILE_STANDARD,
    SCOPE_AGENT,
    SCOPE_READ,
    SCOPE_WRITE,
    TOOL_PROFILES,
    TOOL_SCOPES,
    _call_tool,
    _get_tenant_manager,
    _get_tool_accessor,
    _parse_iso_datetime_param,
    _profile_toolset_from_request,
    _profile_toolset_from_state,
    _resolve_tenant,
    _resolve_user_id,
    _scopes_from_request,
    _set_tenant_context,
    logger,
    mcp,
)
from api.endpoints.mcp_tools._base import pydantic_validation_rejection

from api.endpoints.mcp_tools._chain_tools import (  # noqa: F401  (re-export surface)
    link_projects,
    unlink_projects,
)
from api.endpoints.mcp_tools._context_tools import (  # noqa: F401  (re-export surface)
    get_context,
    get_vision_document,
    search_memory,
    update_product_context,
)
from api.endpoints.mcp_tools._job_tools import (  # noqa: F401  (re-export surface)
    _PLACEHOLDER_JOB_IDS,
    complete_job,
    finalize_job,
    get_agent_result,
    get_job_mission,
    get_staging_instructions,
    get_workflow_status,
    report_progress,
    set_agent_status,
    spawn_job,
    update_job_mission,
)
from api.endpoints.mcp_tools._memory_tools import (  # noqa: F401  (re-export surface)
    write_memory_entry,
    write_project_closeout,
)
from api.endpoints.mcp_tools._message_tools import request_approval  # noqa: F401  (re-export surface)
from api.endpoints.mcp_tools._project_tools import (  # noqa: F401  (re-export surface)
    create_project,
    list_projects,
    update_project,
    update_project_mission,
)
from api.endpoints.mcp_tools._setup_tools import (  # noqa: F401  (re-export surface)
    apply_context_tuning,
    get_giljo_guide,
    giljo_setup,
    health_check,
)
from api.endpoints.mcp_tools._task_tools import (  # noqa: F401  (re-export surface)
    create_task,
    list_tasks,
    update_task,
)

from api.endpoints.mcp_transport import (  # noqa: F401  (re-export surface)
    _MAX_MCP_BODY_BYTES,
    _BodyTooLargeError,
    _build_www_authenticate_header,
    _not_found_response,
    _peek_jsonrpc_client_info,
    _peek_jsonrpc_method,
    _read_full_body,
    _replay_receive,
    _send_method_not_allowed,
    _send_raw_status,
    _stamp_declared_profile,
    _stamp_resolved_harness,
    _stamp_url_profile,
    _subscription_required_response,
    _unauthenticated_response,
    _unsupported_version_response,
    _validate_protocol_version,
    _wrap_send_with_session_id,
)

from giljo_mcp.auth.jwt_manager import JWTAudienceMismatchError, JWTManager  # noqa: F401  (re-export surface)



_current_request: ContextVar[StarletteRequest | None] = ContextVar("giljo_mcp_current_request", default=None)


def _request_from_context() -> StarletteRequest | None:
    return _current_request.get()


_orig_list_tools = mcp.list_tools




async def _headless_launch_allowed(tenant_key: str) -> bool:
    from api.app_state import state as app_state
    from giljo_mcp.services.settings_service import SettingsService

    try:
        async with app_state.db_manager.get_session_async() as db:
            svc = SettingsService(db, tenant_key)
            return bool(await svc.get_setting_value("security", "allow_headless_launch", default=True))
    except Exception:  # noqa: BLE001 — resolve conservatively
        logger.warning("BE-9084: headless-toggle lookup failed; defaulting to HITL (blocked)", exc_info=True)
        return False


async def _launch_gate_blocked(request: StarletteRequest | None) -> bool:
    if request is None:
        return False
    state = request.scope.get("state", {}) if hasattr(request, "scope") else {}
    if state.get("auth_method") != "jwt":
        return False
    tenant_key = state.get("tenant_key")
    if not tenant_key:
        return True
    return not await _headless_launch_allowed(tenant_key)


async def _orchestrator_toggle_admits_launch(
    request: StarletteRequest | None, profile_toolset: frozenset[str] | None
) -> bool:
    if request is None or profile_toolset != _ORCHESTRATOR_PROFILE_TOOLS:
        return False
    return not await _launch_gate_blocked(request)


async def _scope_filtered_list_tools():
    tools = await _orig_list_tools()
    tools = [t for t in tools if t.name in TOOL_SCOPES]
    request = _request_from_context()
    scopes = _scopes_from_request(request)
    if scopes is not None:
        tools = [t for t in tools if TOOL_SCOPES.get(t.name) in scopes]
    profile_toolset = _profile_toolset_from_request(request)
    launch_blocked: bool | None = None
    if profile_toolset is not None:
        removed_launch_tools = [t for t in tools if t.name in _LAUNCH_GATE_TOOLS and t.name not in profile_toolset]
        tools = [t for t in tools if t.name in profile_toolset]
        if removed_launch_tools and await _orchestrator_toggle_admits_launch(request, profile_toolset):
            launch_blocked = False
            tools.extend(removed_launch_tools)
    if any(t.name in _HITL_FENCED_TOOLS for t in tools):
        if launch_blocked is None:
            launch_blocked = await _launch_gate_blocked(request)
        if launch_blocked:
            tools = [t for t in tools if t.name not in _HITL_FENCED_TOOLS]
    return tools


async def _dispatch_refusal_reason(name, arguments) -> str | None:
    if name in {t.name for t in mcp._tool_manager.list_tools()} and name not in TOOL_SCOPES:
        return f"Tool '{name}' has no authorization scope mapping; dispatch refused (fail-closed)"

    request = _request_from_context()
    scopes = _scopes_from_request(request)
    if scopes is not None:
        tool_scope = TOOL_SCOPES.get(name)
        if tool_scope not in scopes:
            return f"Tool '{name}' not authorized for this token's scope"
    profile_toolset = _profile_toolset_from_request(request)
    defers_to_fence = (
        name in _LAUNCH_GATE_TOOLS and profile_toolset == _ORCHESTRATOR_PROFILE_TOOLS and request is not None
    )
    if profile_toolset is not None and name not in profile_toolset and not defers_to_fence:
        return f"Tool '{name}' not available in this session's tool profile"
    if name in _HITL_FENCED_TOOLS and await _launch_gate_blocked(request):
        if name == "decide_approval":
            return (
                f"Tool '{name}' is gated by the human Implement step (HITL mode). "
                "Enable Headless mode in Settings to let a CLI agent answer approvals from the harness."
            )
        return (
            f"Tool '{name}' is gated by the human Implement step (HITL mode). "
            "Enable Headless mode in Settings to let a CLI agent self-advance staging to implementation."
        )
    return _describe_absorbed_argument_for(name, arguments)


def _describe_absorbed_argument_for(name: str, arguments) -> str | None:
    if not isinstance(arguments, dict):
        return None
    tool = mcp._tool_manager.get_tool(name)
    if tool is None:
        return None
    try:
        schema = tool.parameters
    except Exception:  # noqa: BLE001 - an odd tool object keeps the SDK's own error path
        return None
    if not isinstance(schema, dict):
        return None
    return describe_absorbed_argument(
        tool_name=name,
        arguments=arguments,
        required=list(schema.get("required") or []),
        parameter_names=list((schema.get("properties") or {}).keys()),
    )


def _argument_validation_result(name: str, arguments) -> CallToolResult | None:
    if not isinstance(arguments, dict):
        return None
    tool = mcp._tool_manager.get_tool(name)
    if tool is None:
        return None
    try:
        tool.fn_metadata.validate_arguments(arguments)
    except PydanticValidationError as exc:
        rejection = pydantic_validation_rejection(exc)
        logger.info("MCP tool '%s' refused invalid arguments: %s", name, rejection.get("field"))
        return tool.fn_metadata.convert_result(rejection)
    except Exception:  # noqa: BLE001 - anything else keeps the SDK's own error path
        return None
    return None


def _tool_name(tool) -> str | None:
    return tool.get("name") if isinstance(tool, dict) else getattr(tool, "name", None)


def _filter_advertised_tools(result, allowed: set[str]):
    if isinstance(result, dict):
        tools = result.get("tools")
        if not isinstance(tools, list):
            return result
        filtered = dict(result)
        filtered["tools"] = [t for t in tools if _tool_name(t) in allowed]
        return filtered
    tools = getattr(result, "tools", None)
    if tools is None:
        return result
    return result.model_copy(update={"tools": [t for t in tools if _tool_name(t) in allowed]})


async def _scope_gate(ctx, call_next):
    token = _current_request.set(getattr(ctx, "request", None))
    try:
        if ctx.method == "tools/call":
            params = ctx.params or {}
            reason = await _dispatch_refusal_reason(params.get("name"), params.get("arguments") or {})
            if reason is not None:
                return CallToolResult(content=[TextContent(type="text", text=reason)], isError=True)
            rejected = _argument_validation_result(params.get("name"), params.get("arguments") or {})
            if rejected is not None:
                return rejected
            return await call_next(ctx)

        result = await call_next(ctx)
        if ctx.method == "tools/list":
            allowed = {t.name for t in await _scope_filtered_list_tools()}
            result = _filter_advertised_tools(result, allowed)
        return result
    finally:
        _current_request.reset(token)


mcp.middleware.append(_scope_gate)

_chain_without_otel = [m for m in mcp.middleware if type(m).__name__ != "OpenTelemetryMiddleware"]
if len(_chain_without_otel) == len(mcp.middleware):
    raise RuntimeError(
        "INF-9371: expected the SDK's OpenTelemetryMiddleware in the default middleware chain "
        f"so it could be explicitly opted out; found {[type(m).__name__ for m in mcp.middleware]}. "
        "Re-check the SDK's default chain before assuming OTel is off."
    )
mcp.middleware[:] = _chain_without_otel


def _assert_tool_scope_completeness() -> None:
    registered = {t.name for t in mcp._tool_manager.list_tools()}
    mapped = set(TOOL_SCOPES)
    missing = registered - mapped
    orphaned = mapped - registered
    if missing or orphaned:
        raise RuntimeError(
            "SEC-9126 fail-closed invariant violated: MCP tool authorization registry is incomplete. "
            f"registered-but-unmapped={sorted(missing)}; mapped-but-unregistered={sorted(orphaned)}"
        )


_assert_tool_scope_completeness()




_STREAMABLE_HTTP_KWARGS = {
    "streamable_http_path": "/",
    "json_response": True,
    "stateless_http": True,
    "transport_security": TransportSecuritySettings(enable_dns_rebinding_protection=False),
}

_streamable_app_built = False


def _ensure_streamable_app() -> None:
    global _streamable_app_built  # noqa: PLW0603
    if _streamable_app_built:
        return
    mcp.streamable_http_app(**_STREAMABLE_HTTP_KWARGS)
    _streamable_app_built = True


def get_mcp_asgi_app():
    _ensure_streamable_app()

    from mcp.server.streamable_http_manager import StreamableHTTPASGIApp

    asgi_handler = StreamableHTTPASGIApp(mcp.session_manager)

    return MCPAuthMiddleware(asgi_handler)



_session_manager_cm = None


async def start_mcp_session_manager():
    global _session_manager_cm  # noqa: PLW0603
    _ensure_streamable_app()
    _session_manager_cm = mcp.session_manager.run()
    await _session_manager_cm.__aenter__()
    logger.info("MCP SDK session manager started")


async def stop_mcp_session_manager():
    global _session_manager_cm  # noqa: PLW0603
    if _session_manager_cm:
        await _session_manager_cm.__aexit__(None, None, None)
        _session_manager_cm = None
        logger.info("MCP SDK session manager stopped")
