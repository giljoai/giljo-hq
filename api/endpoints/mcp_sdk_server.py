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

from contextvars import ContextVar

from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import CallToolResult, TextContent
from starlette.requests import Request as StarletteRequest

# Importing the wrapper subpackage registers all @mcp.tool wrappers (count
# roster-locked by tests/unit/test_be6042d_mcp_tool_registry_surface.py) on the
# shared ``mcp`` instance (decorator side effect at import time). The names below
# are re-exported so existing importers of ``mcp_sdk_server`` keep working.
import api.endpoints.mcp_tools  # noqa: F401  (import for registration side effect)

# INF-9463: moved out of mcp_transport.py (which sat at the 800-line file cap)
# into its own module; this is its one external caller.
from api.endpoints.mcp_absorption_diagnosis import describe_absorbed_argument

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

# Re-export every @mcp.tool wrapper function (and the _PLACEHOLDER_JOB_IDS
# constant) by name. Existing code imports these straight from mcp_sdk_server
# (``from api.endpoints.mcp_sdk_server import spawn_job`` /
# ``mcp_sdk_server.report_progress`` / ``_PLACEHOLDER_JOB_IDS``); the wrappers
# moved into the mcp_tools subpackage in BE-6042d, so re-export to preserve the
# import surface.
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
)

# Re-export JWT symbols external tests patch/reference off this module
# (``mcp_sdk_server.JWTManager`` / ``mcp_sdk_server.JWTAudienceMismatchError``).
from giljo_mcp.auth.jwt_manager import JWTAudienceMismatchError, JWTManager  # noqa: F401  (re-export surface)


# ---------------------------------------------------------------------------
# API-0021b: scope-aware tools/list filter + tools/call dispatch gate
#
# JWT-authenticated callers only see (and can only invoke) tools whose registered
# scope is in the token's scope set. API-key callers bypass entirely.
#
# INF-9371 (SDK 2.0): this gate used to be installed by re-calling the SDK's
# lowlevel decorators, which replaced our handlers into the private
# ``request_handlers`` dict. 2.0 removes those decorators and hardcodes
# MCPServer's own handlers into the lowlevel slots, so the gate now rides the
# PUBLIC ``MCPServer.middleware`` seam instead -- documented by the SDK as the
# place to "observe, refuse, or rewrite messages before they reach a handler".
# That is a net improvement: the authorization boundary is no longer implemented
# by reaching into SDK internals.
#
# The gate still reads ``_scopes_from_request`` / ``_profile_toolset_from_request``
# out of THIS module's namespace; the profile-tier tests monkeypatch those names
# on ``mcp_sdk_server`` directly, so the gate MUST stay in this module.
# ---------------------------------------------------------------------------

# INF-9371: ``mcp.get_context()`` is gone in 2.0. The middleware seam is where the
# SDK hands us the per-request context, so ``_scope_gate`` publishes that request
# here and the resolver below reads it. The zero-argument signature and the
# "None outside an HTTP request" contract are preserved DELIBERATELY: the
# in-memory test transport has no HTTP request (the 78 boundary tests and
# SEC-9423's unpatched posture both depend on resolving to None), and
# tests/integration/test_be9084_headless_hitl_gate.py monkeypatches this very
# function with a zero-arg lambda. A ContextVar is per-task, so concurrent
# requests cannot see each other's.
_current_request: ContextVar[StarletteRequest | None] = ContextVar("giljo_mcp_current_request", default=None)


def _request_from_context() -> StarletteRequest | None:
    """Best-effort resolve the StarletteRequest for the active MCP request.

    Returns None when called outside an HTTP request (e.g. the in-memory test
    transport). Tests that exercise the scope filter monkeypatch
    `_scopes_from_request` directly.
    """
    return _current_request.get()


# The SDK's own unfiltered tool lister, which _scope_filtered_list_tools narrows.
# INF-9371: the companion ``_orig_call_tool`` binding is gone — under the
# middleware seam nothing replaces the SDK's call handler, so a name implying an
# "original" we swapped out would be a lie. Dispatch now continues via call_next.
_orig_list_tools = mcp.list_tools


# ---------------------------------------------------------------------------
# Headless-launch fence.
#
# Invariants this block exists to hold:
#   - Admission to the launch gate is decided solely by an operator-authored,
#     tenant-scoped setting, evaluated independently of anything the client
#     declares. See the settings docs for the current default.
#   - ``clientInfo`` and any client-declared tool profile are untrusted: a
#     declared profile may narrow a session's toolset, never widen it.
#   - The fence is an independent check that duplicates the admission decision
#     rather than trusting it, so the two cannot disagree.
#   - It is conservative by construction. ADR-009: the setting is tenant-scoped
#     and resolved off the session's tenant.
#
# Scope note: the human-in-the-loop posture guarantees the SERVER will not
# AUTHORIZE implementation early — it withholds the launch gate. It is a
# server-side authorization control and does not attempt to constrain
# client-local execution.
# ---------------------------------------------------------------------------


async def _headless_launch_allowed(tenant_key: str) -> bool:
    """Resolve the tenant's Headless setting.

    ``True`` == the tenant allows a trusted CLI/OAuth agent to self-advance the
    implement gate. An explicitly stored value is always honored, so a tenant's
    recorded choice is never silently changed. Unresolved values are treated
    conservatively.
    """
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
    """Whether the fence blocks a fenced tool for this request.

    Returns ``True`` to BLOCK. Resolves conservatively when the tenant setting
    cannot be read.
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


async def _orchestrator_toggle_admits_launch(
    request: StarletteRequest | None, profile_toolset: frozenset[str] | None
) -> bool:
    """Whether the tenant setting admits the launch gate into an
    orchestrator-profile session.

    Fires only for the auth-derived ``orchestrator`` toolset, never for a session
    that explicitly narrowed itself further: a deliberate self-narrowing is not
    something a tenant-level setting should override. Where there is no tenant to
    consult, it does not admit.

    Keyed exclusively on the operator-authored tenant setting via the existing
    :func:`_launch_gate_blocked` fence — never on anything client-declared.
    Admission depends on what the OPERATOR authorized out-of-band, not on what a
    client claims about itself.
    """
    if request is None or profile_toolset != _ORCHESTRATOR_PROFILE_TOOLS:
        return False
    return not await _launch_gate_blocked(request)


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
    launch_blocked: bool | None = None
    if profile_toolset is not None:
        # BE-9499c: hold onto any launch-gate tool the profile filter is about to
        # strip -- an orchestrator-profile jwt session whose tenant opted into
        # Headless gets it back below, admitted by the TOGGLE, never by a
        # client-declared profile (the declared-profile resolver can no longer
        # produce anything wider than `orchestrator` for such a session; see
        # `_profile_toolset_from_state`).
        removed_launch_tools = [t for t in tools if t.name in _LAUNCH_GATE_TOOLS and t.name not in profile_toolset]
        tools = [t for t in tools if t.name in profile_toolset]
        if removed_launch_tools and await _orchestrator_toggle_admits_launch(request, profile_toolset):
            launch_blocked = False
            tools.extend(removed_launch_tools)
    # BE-9084: default-HITL — hide a fenced tool from a jwt session unless its
    # tenant opted into Headless. The DB read only fires when a fenced tool
    # survived the scope + profile filters (an unrestricted/full session, or —
    # BE-9499d — an ordinary orchestrator-profile session for decide_approval, which
    # is NOT excluded from that profile's static allow-set), so the common path
    # (every non-full jwt / api-key session touching launch_implementation) stays free.
    # Reuses `launch_blocked` if the toggle admission above already resolved it
    # (tenant-scoped, not tool-scoped), so a single tenant is never read twice.
    if any(t.name in _HITL_FENCED_TOOLS for t in tools):
        if launch_blocked is None:
            launch_blocked = await _launch_gate_blocked(request)
        if launch_blocked:
            tools = [t for t in tools if t.name not in _HITL_FENCED_TOOLS]
    return tools


async def _dispatch_refusal_reason(name, arguments) -> str | None:
    """Why this ``tools/call`` must be refused, or ``None`` to let it dispatch.

    Defense-in-depth: the tools/list filter hides tools from the advertised
    list, but a caller can still craft a tools/call against a hidden name. This
    gate ensures such calls fail rather than silently executing — for BOTH the
    auth scope (API-0021b) and the WO-8003k profile (e.g. a ``standard`` session
    calling ``launch_implementation`` is server-rejected exactly like an
    out-of-scope call, closing the advisory-only implement-gate hole).

    INF-9371: these five checks used to ``raise ToolError``, which the SDK turned
    into an ``isError`` CallToolResult. On 2.0 the gate runs as middleware, ABOVE
    the handler that does that conversion — an exception raised here escapes as a
    JSON-RPC protocol error instead, with ``isError``/``content`` null. That is a
    wire-contract change, so the refusals return their reason and ``_scope_gate``
    builds the CallToolResult. Returning a reason (rather than raising) is what
    keeps every refusal shaped exactly as it was on 1.28.1.
    """
    # SEC-9126 (fail-closed): a tool that IS registered but has no TOOL_SCOPES
    # entry is refused on EVERY auth path, before the scope/profile checks and
    # independent of auth method (closes the scopes-None / profile-None bypass).
    # A name that is not registered at all falls through untouched so the SDK's
    # own unknown-tool error is preserved.
    #
    # INF-9371: ``_tool_manager.list_tools()`` stays private-but-sync here. The
    # public ``MCPServer.list_tools()`` is a coroutine, and the completeness guard
    # below (``_assert_tool_scope_completeness``) runs synchronously at import, so
    # a single accessor cannot serve both without an event loop at module import.
    if name in {t.name for t in mcp._tool_manager.list_tools()} and name not in TOOL_SCOPES:
        return f"Tool '{name}' has no authorization scope mapping; dispatch refused (fail-closed)"

    request = _request_from_context()
    scopes = _scopes_from_request(request)
    if scopes is not None:
        tool_scope = TOOL_SCOPES.get(name)
        if tool_scope not in scopes:
            return f"Tool '{name}' not authorized for this token's scope"
    profile_toolset = _profile_toolset_from_request(request)
    # BE-9499c: the ONE carve-out — a launch-gate tool excluded ONLY because this is
    # the auth-derived `orchestrator` profile, on a REAL request (a tenant to
    # consult), defers to the BE-9084 fence below, which is the sole authority on
    # whether the tenant Headless toggle admits it. Any OTHER out-of-profile call
    # (core/standard, a narrower explicitly-declared profile, or the request-less
    # test transport with no tenant to check) is rejected here, unchanged.
    defers_to_fence = (
        name in _LAUNCH_GATE_TOOLS and profile_toolset == _ORCHESTRATOR_PROFILE_TOOLS and request is not None
    )
    if profile_toolset is not None and name not in profile_toolset and not defers_to_fence:
        return f"Tool '{name}' not available in this session's tool profile"
    # BE-9084: default-HITL fence — independent of profile. A jwt session that
    # declared the full profile (or, for decide_approval, an ordinary orchestrator
    # session) still cannot cross this gate unless its tenant opted into Headless
    # mode (security.allow_headless_launch). This is now the SOLE decider for a
    # launch-gate tool that reached this point (whether the profile filter above
    # let it through outright, or deferred to the fence per BE-9499c) — a
    # stale/inert client-declared profile can no longer change the outcome.
    # BE-9499d extended the SAME fence (same toggle, same api_key/request-less
    # carve-outs) to decide_approval — answering an approval from the harness is
    # exactly as consequential as self-advancing to implementation.
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
    # TSK-9309: when a required argument is absent because a neighbouring string
    # argument absorbed it, say so instead of letting pydantic blame the missing
    # field. A genuine omission keeps the ordinary validation error.
    #
    # BE-9348: this also runs on calls that would otherwise SUCCEED. Absorption of an
    # OPTIONAL argument leaves every required one present, so nothing rejects it and
    # the residue is persisted verbatim. Refusing such a call is therefore a real
    # behaviour change, bounded on that path by conclusive evidence plus a tail that
    # is pure call syntax carrying an actual serialized value.
    return _describe_absorbed_argument_for(name, arguments)


def _describe_absorbed_argument_for(name: str, arguments) -> str | None:
    """Resolve the tool's advertised schema and diagnose an absorbed argument."""
    if not isinstance(arguments, dict):
        return None
    # INF-9371: 2.0's get_tool() returns ``Tool | None`` where 1.x raised on an
    # unknown name. The None is checked explicitly rather than left to the
    # except-clause below to catch the resulting AttributeError — an unknown tool
    # must keep the SDK's own error path, and that should not depend on which
    # exception a miss happens to produce.
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


def _tool_name(tool) -> str | None:
    """Name of an advertised tool, whether it arrives as a dict or a model."""
    return tool.get("name") if isinstance(tool, dict) else getattr(tool, "name", None)


def _filter_advertised_tools(result, allowed: set[str]):
    """Apply the advertised-tool allowlist to a ``tools/list`` result.

    INF-9371 — read this before "simplifying" it. SDK 2.0 declares what middleware
    may observe as ``HandlerResult = BaseModel | dict[str, Any] | None``
    (``mcp/server/context.py``: "What a request handler (or middleware) may
    return. ServerRunner serializes all three to a result dict."). In practice our
    ``tools/list`` can arrive as a plain ``dict`` rather than a typed
    ``ListToolsResult``.

    That is why this handles BOTH arms of the declared union. An
    ``isinstance(result, ListToolsResult)`` filter alone silently stops filtering
    the moment the result arrives as a dict instead — it type-checks and raises
    nothing, so nothing signals the gap. A bare ``result["tools"]`` has the
    mirror-image bug if the SDK's provisional middleware rework starts handing
    back typed models. Both arms are pinned by tests.
    """
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
    """SEC-9126 / API-0021b authorization gate, on the public middleware seam.

    Ordering matters and is not incidental: the chain runs outermost-first and
    the SDK's own ``RequestStateBoundary`` is what populates ``ctx.request``, so
    this gate is APPENDED (innermost) and depends on that boundary having
    already run to see the HTTP request at all.

    Refusals RETURN a ``CallToolResult(isError=True)`` rather than raising: an
    exception raised at this layer escapes as a JSON-RPC protocol error with
    ``isError``/``content`` null, which is not the refusal shape 1.28.1 put on
    the wire (see ``_dispatch_refusal_reason``).
    """
    token = _current_request.set(getattr(ctx, "request", None))
    try:
        if ctx.method == "tools/call":
            params = ctx.params or {}
            reason = await _dispatch_refusal_reason(params.get("name"), params.get("arguments") or {})
            if reason is not None:
                return CallToolResult(content=[TextContent(type="text", text=reason)], isError=True)
            return await call_next(ctx)

        result = await call_next(ctx)
        if ctx.method == "tools/list":
            allowed = {t.name for t in await _scope_filtered_list_tools()}
            result = _filter_advertised_tools(result, allowed)
        return result
    finally:
        _current_request.reset(token)


# INF-9371: install the gate on the public middleware seam. In 1.x this was a
# re-registration into the lowlevel server's private handler table; 2.0 hardcodes
# MCPServer's own handlers into those slots and offers `middleware` instead.
mcp.middleware.append(_scope_gate)

# INF-9371: opt OUT of the SDK's OpenTelemetry middleware, explicitly.
#
# Measured 2026-08-14 on mcp 2.0.0: it ships ON by default and is a genuine no-op
# for us today (no tracer provider is configured anywhere in this tree, so spans
# resolve to NonRecordingSpan / is_recording False). It is off by ABSENCE OF
# CONFIGURATION, not by decision — and it emits a SERVER span per MCP message on
# the hottest path we own. Anything that later configures a tracer provider would
# arm it silently in production, so re-enabling it should be a deliberate act --
# it is removed here rather than left to ambient configuration.
#
# Matched by class name to avoid importing the SDK's private `_otel` module, and
# asserted rather than assumed: a silently-unmatched filter would leave the
# middleware installed and this decision would quietly not have happened.
_chain_without_otel = [m for m in mcp.middleware if type(m).__name__ != "OpenTelemetryMiddleware"]
if len(_chain_without_otel) == len(mcp.middleware):
    raise RuntimeError(
        "INF-9371: expected the SDK's OpenTelemetryMiddleware in the default middleware chain "
        f"so it could be explicitly opted out; found {[type(m).__name__ for m in mcp.middleware]}. "
        "Re-check the SDK's default chain before assuming OTel is off."
    )
mcp.middleware[:] = _chain_without_otel


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


# INF-9371: SDK 2.0 moved the transport configuration off the server constructor
# onto streamable_http_app(). TWO call sites need it — the ASGI app factory and
# the session-manager lifecycle — so the kwargs live here ONCE. Repeating the list
# at both sites would let the two drift, and a session manager built with a
# different transport config than the ASGI app fails silently and surfaces much
# later as an inexplicable transport bug.
_STREAMABLE_HTTP_KWARGS = {
    "streamable_http_path": "/",
    "json_response": True,
    "stateless_http": True,
    # Disable the SDK's built-in DNS rebinding protection — our MCPAuthMiddleware
    # handles auth (Bearer token + tenant isolation). The server binds to
    # 127.0.0.1 (localhost HTTP) or LAN IP (HTTPS only), configured at install.
    # NOTE (2.0): passing this explicitly is now load-bearing. When
    # transport_security is None and host is localhost, the SDK ENABLES rebinding
    # protection for us — so dropping the kwarg would silently reverse this.
    "transport_security": TransportSecuritySettings(enable_dns_rebinding_protection=False),
}

_streamable_app_built = False


def _ensure_streamable_app() -> None:
    """Build the streamable-HTTP app exactly once, so the session manager exists.

    Build-once is required, not tidiness: each streamable_http_app() call
    constructs a NEW StreamableHTTPSessionManager and overwrites the server's
    reference to it, so a second call would orphan the manager whose run() the
    lifespan already entered. 1.x could guard on ``mcp._session_manager is None``;
    2.0's public ``session_manager`` property RAISES until the app is built, so
    the guard is a flag.
    """
    global _streamable_app_built  # noqa: PLW0603
    if _streamable_app_built:
        return
    mcp.streamable_http_app(**_STREAMABLE_HTTP_KWARGS)
    _streamable_app_built = True


def get_mcp_asgi_app():
    """
    Build the MCP ASGI app with auth middleware applied.

    Returns a pure ASGI callable: MCPAuthMiddleware → StreamableHTTPASGIApp.
    Called from app.py via a direct FastAPI route (not app.mount, to avoid
    the 307 trailing-slash redirect).

    Lifecycle: Call start_mcp_session_manager() / stop_mcp_session_manager()
    in the FastAPI lifespan (see app.py).
    """
    _ensure_streamable_app()

    # Build the SDK's ASGI handler directly
    from mcp.server.streamable_http_manager import StreamableHTTPASGIApp

    asgi_handler = StreamableHTTPASGIApp(mcp.session_manager)

    # Wrap with auth middleware — pure ASGI chain
    return MCPAuthMiddleware(asgi_handler)


# ---------------------------------------------------------------------------
# Lifecycle management — called from FastAPI lifespan in app.py
# ---------------------------------------------------------------------------

_session_manager_cm = None


async def start_mcp_session_manager():
    """Start the SDK's session manager task group. Call during FastAPI startup."""
    global _session_manager_cm  # noqa: PLW0603
    _ensure_streamable_app()
    _session_manager_cm = mcp.session_manager.run()
    await _session_manager_cm.__aenter__()
    logger.info("MCP SDK session manager started")


async def stop_mcp_session_manager():
    """Stop the SDK's session manager task group. Call during FastAPI shutdown."""
    global _session_manager_cm  # noqa: PLW0603
    if _session_manager_cm:
        await _session_manager_cm.__aexit__(None, None, None)
        _session_manager_cm = None
        logger.info("MCP SDK session manager stopped")
