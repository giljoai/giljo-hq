# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
MCP SDK Server -- Streamable HTTP transport using official Anthropic MCP Python SDK.

Standard MCP protocol transport using official Anthropic MCP Python SDK (FastMCP).
transport. All tools delegate to the existing ToolAccessor methods. Auth and tenant
isolation are handled by ASGI middleware applied to the Starlette sub-app.

Handover: 0846a (transport replacement), 0846b (security integration)

BE-6042d: the @mcp.tool wrappers and the shared dispatch helpers were split out
of this module into the ``api.endpoints.mcp_tools`` subpackage (the live registered
count is roster-locked by ``tests/unit/test_be6042d_mcp_tool_registry_surface.py``,
not restated here to avoid re-drifting on the next roster change). Importing that
package below triggers the @mcp.tool decorator side effects (tool registration on
the shared ``mcp`` instance) and re-exports the public surface other code imports
straight from ``mcp_sdk_server`` (``mcp``, ``TOOL_SCOPES``, ``_call_tool``,
``_parse_iso_datetime_param``, ``giljo_setup``, ...).

BE-9060 (item 1): this module was the hottest file in the repo (six concerns mixed
at the MCP auth boundary). Two more seams were extracted:
  - :mod:`api.endpoints.mcp_transport` -- the wire-level transport helpers
    (body buffer/replay, raw-ASGI status emitters, JSON-RPC peeking,
    protocol-version validation, the session-id send wrapper, response builders,
    and the session "stamp" helpers).
  - :mod:`api.endpoints.mcp_auth_middleware` -- :class:`MCPAuthMiddleware` and the
    CE post-auth-gate extension point.
This module now retains only the app-factory / lifecycle layer
(``get_mcp_asgi_app``, ``start_mcp_session_manager`` / ``stop_mcp_session_manager``)
and the scope-aware tools/list + tools/call re-registration (which reads the
``_scopes_from_request`` / ``_profile_toolset_from_request`` resolvers out of THIS
module's namespace -- tests monkeypatch them here, so the re-registration stays
here). Every extracted name is re-exported below so importers of ``mcp_sdk_server``
keep working. Behavior is unchanged throughout.
"""

from starlette.requests import Request as StarletteRequest

# Importing the wrapper subpackage registers all @mcp.tool wrappers (count
# roster-locked by tests/unit/test_be6042d_mcp_tool_registry_surface.py) on the
# shared ``mcp`` instance (decorator side effect at import time). The names below
# are re-exported so existing importers of ``mcp_sdk_server`` keep working.
import api.endpoints.mcp_tools  # noqa: F401  (import for registration side effect)

# BE-9060 (item 1): auth middleware + post-auth gate re-export surface. Existing
# code and tests import MCPAuthMiddleware / register_mcp_post_auth_gate /
# clear_mcp_post_auth_gate straight from ``mcp_sdk_server``; the implementations
# moved into ``mcp_auth_middleware`` so re-export them here.
from api.endpoints.mcp_auth_middleware import (  # noqa: F401  (re-export surface)
    MCPAuthMiddleware,
    McpPostAuthGate,
    clear_mcp_post_auth_gate,
    register_mcp_post_auth_gate,
)
from api.endpoints.mcp_tools import (  # noqa: F401  (re-export surface)
    _LAUNCH_GATE_TOOLS,
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

# Re-export every @mcp.tool wrapper function (and the _PLACEHOLDER_JOB_IDS
# constant) by name. Existing code imports these straight from mcp_sdk_server
# (``from api.endpoints.mcp_sdk_server import spawn_job`` /
# ``mcp_sdk_server.report_progress`` / ``_PLACEHOLDER_JOB_IDS``); the wrappers
# moved into the mcp_tools subpackage in BE-6042d, so re-export to preserve the
# import surface.
from api.endpoints.mcp_tools._chain_tools import (  # noqa: F401  (re-export surface)
    start_chain_run,
)
from api.endpoints.mcp_tools._context_tools import (  # noqa: F401  (re-export surface)
    get_context,
    get_vision_doc,
    search_memory,
    update_product_context,
)
from api.endpoints.mcp_tools._job_tools import (  # noqa: F401  (re-export surface)
    _PLACEHOLDER_JOB_IDS,
    close_job,
    complete_job,
    get_agent_result,
    get_job_mission,
    get_staging_instructions,
    get_workflow_status,
    report_progress,
    resolve_reactivation,
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

# BE-9060 (item 1): transport-helper re-export surface. External code + tests
# reach some of these straight off ``mcp_sdk_server`` (e.g. ``_stamp_declared_profile``);
# re-export the full set the pre-split module exposed so no importer breaks.
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
    describe_absorbed_argument,
)

# Re-export JWT symbols external tests patch/reference off this module
# (``mcp_sdk_server.JWTManager`` / ``mcp_sdk_server.JWTAudienceMismatchError``).
from giljo_mcp.auth.jwt_manager import JWTAudienceMismatchError, JWTManager  # noqa: F401  (re-export surface)


# ---------------------------------------------------------------------------
# API-0021b: scope-aware tools/list filter + tools/call dispatch gate
#
# Re-registers the SDK's ListToolsRequest and CallToolRequest handlers so that
# JWT-authenticated callers only see (and can only invoke) tools whose registered
# scope is in the token's scope set. API-key callers bypass entirely.
#
# The lowlevel server captures handler references at FastMCP.__init__ time,
# so re-registration must call the SDK's own decorator (which rebuilds the
# request_handlers entry) rather than monkey-patching `mcp.list_tools`.
#
# These handlers read ``_scopes_from_request`` / ``_profile_toolset_from_request``
# out of THIS module's namespace; the profile-tier tests monkeypatch those names
# on ``mcp_sdk_server`` directly, so this re-registration MUST stay in this module.
# ---------------------------------------------------------------------------


def _request_from_context() -> StarletteRequest | None:
    """Best-effort resolve the StarletteRequest for the active MCP request.

    Returns None when called outside an HTTP request (e.g. the in-memory test
    transport). Tests that exercise the scope filter monkeypatch
    `_scopes_from_request` directly.
    """
    try:
        ctx = mcp.get_context()
        return ctx.request_context.request
    except (LookupError, ValueError, AttributeError):
        return None


_orig_list_tools = mcp.list_tools
_orig_call_tool = mcp.call_tool


# ---------------------------------------------------------------------------
# BE-9084: default-HITL launch fence.
#
# The human Implement gate is enforced by DEFAULT for every jwt/OAuth session,
# regardless of a declared ``giljo_tool_profile="full"`` (which widens the
# profile to the full surface via _profile_toolset_from_state and would otherwise
# re-expose ``launch_implementation``). This closes that self-unlock bypass
# WITHOUT touching the operator-widening resolver: the fence is an INDEPENDENT
# check layered on top of the scope + profile filters, keyed on the authenticated
# session's tenant Headless toggle (security.allow_headless_launch, default OFF).
#
# Unfenced (behavior unchanged):
#   - ``auth_method == "api_key"``: the operator/CLI full bypass — never fenced.
#   - ``request is None``: the in-memory test transport (no real session).
# Fails SAFE: any error resolving the setting, or a jwt session with no resolvable
# tenant_key, is treated as HITL (blocked) — the gate must never open on a failed
# lookup. ADR-009: the toggle is tenant-scoped, resolved off the session's tenant.
#
# BE-9085 residual (accepted, documented — NOT closed here): HITL guarantees the
# SERVER will not AUTHORIZE implementation early — it withholds the launch gate. It
# cannot prevent a non-compliant LOCAL orchestrator from inlining its self-authored
# mission into an in-process Task() subagent and working off the books; that is an
# accepted residual of in-process subagent execution, and detecting it is a separate
# future build. This fence closes the server-side authorization hole only.
# ---------------------------------------------------------------------------


async def _headless_launch_allowed(tenant_key: str) -> bool:
    """Read the tenant's Headless toggle (``security.allow_headless_launch``).

    ``True`` == the tenant opted a trusted CLI/OAuth agent into self-advancing the
    implement gate. Defaults to ``False`` (HITL) when the row/key is unset, and
    fails SAFE to ``False`` on any read error.
    """
    from api.app_state import state as app_state
    from giljo_mcp.services.settings_service import SettingsService

    try:
        async with app_state.db_manager.get_session_async() as db:
            svc = SettingsService(db, tenant_key)
            return bool(await svc.get_setting_value("security", "allow_headless_launch", default=False))
    except Exception:  # noqa: BLE001 — safe-by-default gate: ANY failure must resolve to HITL (blocked)
        logger.warning("BE-9084: headless-toggle lookup failed; defaulting to HITL (blocked)", exc_info=True)
        return False


async def _launch_gate_blocked(request: StarletteRequest | None) -> bool:
    """Whether the default-HITL fence should block a launch-gate tool for this request.

    Returns ``True`` to BLOCK. Only a jwt session whose tenant has NOT opted into
    Headless is blocked; the api_key operator path and the request-less test
    transport are never fenced. A jwt session with no resolvable tenant_key fails
    SAFE (blocked).
    """
    if request is None:
        return False
    state = request.scope.get("state", {}) if hasattr(request, "scope") else {}
    if state.get("auth_method") != "jwt":
        return False
    tenant_key = state.get("tenant_key")
    if not tenant_key:
        return True
    return not await _headless_launch_allowed(tenant_key)


async def _scope_filtered_list_tools():
    """Replacement for FastMCP.list_tools that filters by token scope AND profile.

    WO-8003k: the effective advertised set is the INTERSECTION scope-filter ∩
    profile. The scope filter is the auth boundary (which tools this token MAY
    touch); the profile is the capability-tier lens (which tools this session
    SHOULD see). ``None`` from either resolver means "no restriction from this
    axis" — a ``full`` profile is byte-identical to the pre-profile surface.
    """
    tools = await _orig_list_tools()
    # SEC-9126 (fail-closed): a registered-but-unmapped tool is never advertised,
    # independent of scopes/profile. Applied FIRST and unconditionally so the
    # scopes-None / profile-None (API-key) posture can no longer expose it.
    tools = [t for t in tools if t.name in TOOL_SCOPES]
    request = _request_from_context()
    scopes = _scopes_from_request(request)
    if scopes is not None:
        tools = [t for t in tools if TOOL_SCOPES.get(t.name) in scopes]
    profile_toolset = _profile_toolset_from_request(request)
    if profile_toolset is not None:
        tools = [t for t in tools if t.name in profile_toolset]
    # BE-9084: default-HITL — hide the launch gate from a jwt session unless its
    # tenant opted into Headless. The DB read only fires when a launch-gate tool
    # survived the scope + profile filters (a full-declaring jwt session), so the
    # common path (every non-full jwt / api-key session) stays free.
    if any(t.name in _LAUNCH_GATE_TOOLS for t in tools) and await _launch_gate_blocked(request):
        tools = [t for t in tools if t.name not in _LAUNCH_GATE_TOOLS]
    return tools


async def _scope_gated_call_tool(name, arguments):
    """Replacement for FastMCP.call_tool that rejects out-of-scope / out-of-profile dispatches.

    Defense-in-depth: the tools/list filter hides tools from the advertised
    list, but a caller can still craft a tools/call against a hidden name. This
    gate ensures such calls fail with a transport-layer error rather than
    silently executing — for BOTH the auth scope (API-0021b) and the WO-8003k
    profile (e.g. a ``standard`` session calling ``launch_implementation`` is
    server-rejected exactly like an out-of-scope call, closing the advisory-only
    implement-gate hole).
    """
    from mcp.server.fastmcp.exceptions import ToolError

    # SEC-9126 (fail-closed): a tool that IS registered but has no TOOL_SCOPES
    # entry is refused on EVERY auth path, before the scope/profile checks and
    # independent of auth method (closes the scopes-None / profile-None bypass).
    # A name that is not registered at all falls through untouched so the SDK's
    # own unknown-tool error is preserved.
    if name in {t.name for t in mcp._tool_manager.list_tools()} and name not in TOOL_SCOPES:
        raise ToolError(f"Tool '{name}' has no authorization scope mapping; dispatch refused (fail-closed)")

    request = _request_from_context()
    scopes = _scopes_from_request(request)
    if scopes is not None:
        tool_scope = TOOL_SCOPES.get(name)
        if tool_scope not in scopes:
            raise ToolError(f"Tool '{name}' not authorized for this token's scope")
    profile_toolset = _profile_toolset_from_request(request)
    if profile_toolset is not None and name not in profile_toolset:
        raise ToolError(f"Tool '{name}' not available in this session's tool profile")
    # BE-9084: default-HITL launch fence — independent of profile. A jwt session
    # that declared the full profile still cannot self-cross the human Implement
    # gate unless its tenant opted into Headless mode (security.allow_headless_launch).
    if name in _LAUNCH_GATE_TOOLS and await _launch_gate_blocked(request):
        raise ToolError(
            f"Tool '{name}' is gated by the human Implement step (HITL mode is the default). "
            "Enable Headless mode in Settings to let a CLI agent self-advance staging to implementation."
        )
    # TSK-9309: when a required argument is absent because a neighbouring string
    # argument absorbed it, say so instead of letting pydantic blame the missing
    # field. A genuine omission keeps the ordinary validation error.
    #
    # BE-9348: this also runs on calls that would otherwise SUCCEED. Absorption of an
    # OPTIONAL argument leaves every required one present, so nothing rejects it and
    # the residue is persisted verbatim. Refusing such a call is therefore a real
    # behaviour change, bounded on that path by conclusive evidence plus a tail that
    # is pure call syntax carrying an actual serialized value.
    absorbed = _describe_absorbed_argument_for(name, arguments)
    if absorbed is not None:
        raise ToolError(absorbed)
    return await _orig_call_tool(name, arguments)


def _describe_absorbed_argument_for(name: str, arguments) -> str | None:
    """Resolve the tool's advertised schema and diagnose an absorbed argument."""
    if not isinstance(arguments, dict):
        return None
    try:
        schema = mcp._tool_manager.get_tool(name).parameters
    except Exception:  # noqa: BLE001 - an unknown/odd tool keeps the SDK's own error path
        return None
    if not isinstance(schema, dict):
        return None
    return describe_absorbed_argument(
        tool_name=name,
        arguments=arguments,
        required=list(schema.get("required") or []),
        parameter_names=list((schema.get("properties") or {}).keys()),
    )


# Re-register against the lowlevel MCP server. _setup_handlers() ran during
# FastMCP.__init__ and bound `self.list_tools` / `self.call_tool` into
# request_handlers; calling the SDK decorators again replaces those entries.
mcp._mcp_server.list_tools()(_scope_filtered_list_tools)
mcp._mcp_server.call_tool(validate_input=False)(_scope_gated_call_tool)


def _assert_tool_scope_completeness() -> None:
    """SEC-9126: single-source-of-truth completeness guard, enforced at boot.

    Fails the server at import (and every test session at collection) if the set
    of registered tools and ``TOOL_SCOPES`` disagree in EITHER direction — the
    same two directions the S12 CI test checks (``missing`` = registered but
    unmapped; ``orphaned`` = mapped but not registered) — so a future unmapped
    tool aborts the server + the dispatch chokepoint's own module load, not just
    one CI test. Raises ``RuntimeError`` naming the offending tool(s).
    """
    registered = {t.name for t in mcp._tool_manager.list_tools()}
    mapped = set(TOOL_SCOPES)
    missing = registered - mapped
    orphaned = mapped - registered
    if missing or orphaned:
        raise RuntimeError(
            "SEC-9126 fail-closed invariant violated: MCP tool authorization registry is incomplete. "
            f"registered-but-unmapped={sorted(missing)}; mapped-but-unregistered={sorted(orphaned)}"
        )


# SEC-9126: enforce the completeness invariant at import (server boot / test
# collection). A future unmapped/orphaned tool now fails the server at startup,
# not just the S12 CI test.
_assert_tool_scope_completeness()


# ---------------------------------------------------------------------------
# Build the mountable Starlette app with auth middleware
# ---------------------------------------------------------------------------


def get_mcp_asgi_app():
    """
    Build the MCP ASGI app with auth middleware applied.

    Returns a pure ASGI callable: MCPAuthMiddleware → StreamableHTTPASGIApp.
    Called from app.py via a direct FastAPI route (not app.mount, to avoid
    the 307 trailing-slash redirect).

    Lifecycle: Call start_mcp_session_manager() / stop_mcp_session_manager()
    in the FastAPI lifespan (see app.py).
    """
    # Ensure session manager is created
    if mcp._session_manager is None:
        mcp.streamable_http_app()

    # Build the SDK's ASGI handler directly
    from mcp.server.fastmcp.server import StreamableHTTPASGIApp

    asgi_handler = StreamableHTTPASGIApp(mcp._session_manager)

    # Wrap with auth middleware — pure ASGI chain
    return MCPAuthMiddleware(asgi_handler)


# ---------------------------------------------------------------------------
# Lifecycle management — called from FastAPI lifespan in app.py
# ---------------------------------------------------------------------------

_session_manager_cm = None


async def start_mcp_session_manager():
    """Start the SDK's session manager task group. Call during FastAPI startup."""
    global _session_manager_cm  # noqa: PLW0603
    if not hasattr(mcp, "_session_manager") or mcp._session_manager is None:
        # Force creation by building the app (idempotent if already built)
        mcp.streamable_http_app()
    _session_manager_cm = mcp._session_manager.run()
    await _session_manager_cm.__aenter__()
    logger.info("MCP SDK session manager started")


async def stop_mcp_session_manager():
    """Stop the SDK's session manager task group. Call during FastAPI shutdown."""
    global _session_manager_cm  # noqa: PLW0603
    if _session_manager_cm:
        await _session_manager_cm.__aexit__(None, None, None)
        _session_manager_cm = None
        logger.info("MCP SDK session manager stopped")
