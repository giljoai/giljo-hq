# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Shared base for the MCP @mcp.tool wrapper subpackage (BE-6042d).

Holds the single ``MCPServer`` instance every wrapper registers against, the tool
scope registry, and the helpers each domain wrapper module delegates through.
Both the wrapper modules (``mcp_tools/_*_tools.py``) and the transport layer
(``mcp_sdk_server.py``) import from here, which is what keeps the import graph
acyclic: this module imports neither the wrappers nor the transport.

Extracted verbatim from the pre-split ``mcp_sdk_server.py`` — behavior unchanged.
"""

import functools
import hashlib
import inspect
import logging
import os
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from mcp.server.caching import CacheHint
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import MCPServerError
from mcp.server.request_state import RequestStateSecurity
from pydantic import BaseModel
from starlette.requests import Request as StarletteRequest

# Harness + session-capability detection (BE-9035d) lives in the sibling ``_harness``
# module to keep this shared base under the file-size guardrail. Re-exported here so
# the wrapper modules (_job_tools / _setup_tools) keep importing them from ``_base``.
from api.endpoints.mcp_tools._harness import (  # noqa: F401
    _HARNESS_PARAM_DESCRIPTION,
    _detected_harness,
    _persisted_harness,
    _resolve_preset_name,
    get_session_capabilities,
)

# BE-9303: silence-clearing tool classification — same seam, same reason.
from api.endpoints.mcp_tools._silence_scope import NON_SILENCE_CLEARING_TOOLS, SILENCE_CLEARING_TOOLS  # noqa: F401
from giljo_mcp import __version__ as _giljo_version
from giljo_mcp import branding
from giljo_mcp.exceptions import BaseGiljoError, ValidationError
from giljo_mcp.services._mcp_wire_bounds import CursorRejectedError
from giljo_mcp.services.debounce import should_run
from giljo_mcp.services.memory_entry_write_validator import MemoryEntryWriteValidationError
from giljo_mcp.tenant_guard import TenantIsolationError
from giljo_mcp.tools.slash_command_templates import SKILLS_VERSION as _SKILLS_VERSION


# BE-3006d: agent-facing message for a sanitized (unexpected) tool failure. Carries
# no SQL, bind parameters, or traceback — the full detail goes to the server log only.
_SANITIZED_TOOL_ERROR = (
    "The server hit an unexpected internal error handling this request. "
    "Full details were logged server-side (no SQL, parameters, or stack trace are "
    "exposed to agents). Retry the call; if it persists, report the tool name."
)

# BE-3006d (CE-mode fix-forward): a cross-tenant access trips
# giljo_mcp.tenant_guard.TenantIsolationError (a plain RuntimeError). It is a
# KNOWN security-boundary rejection, not an unexpected error — but its str()
# leaks internal guard phrasing + the model name ("...ORM statement touching:
# Project..."). Surface a fixed, clean not-found message instead: production's
# tenant-scoped query simply sees no row, so "not found" is the truthful,
# non-leaking agent-facing contract. The word "not found" must remain present
# (an agent-facing contract the lifecycle tools' tests assert).
_NOT_FOUND_TOOL_ERROR = "The requested resource was not found, or you do not have access to it."

# BE-3006d: exception types that are ALREADY clean, agent-facing 422-style
# rejections and must surface verbatim (never sanitized). pydantic.ValidationError
# subclasses ValueError in v2, so the membership/length validators in
# jsonb_validators.py surface through here. MemoryEntryWriteValidationError is the
# structured memory-write cap rejection (its str() carries only field/size/guidance).
_CLEAN_VALIDATION_ERRORS: tuple[type[Exception], ...] = (
    ValueError,
    TypeError,
    MemoryEntryWriteValidationError,
)

# TSK-9134: defense-in-depth signature for a SQL/bind-param leak riding a plain
# ValueError/TypeError through the _CLEAN_VALIDATION_ERRORS verbatim path (real
# SQLAlchemyError & friends are already sanitized by the catch-all below). Narrow so
# a pydantic v2 message ("[type=.../input_value=...]") passes through UNCHANGED.
# Matches the SQLAlchemy dump ("[SQL: ...] [parameters: ...]") or a naive DML+params wrapper.
_SQL_LEAK_SIGNATURE = re.compile(
    r"\[SQL:"  # SQLAlchemy statement dump
    r"|\[SQL parameters:"  # driver variant
    r"|\[parameters:"  # SQLAlchemy bind-parameter dump
    r"|Background on this error at: https://sqlalche\.me"  # SQLAlchemy DBAPIError help suffix
    r"|(?:INSERT\s+INTO|UPDATE\s+\S+\s+SET|DELETE\s+FROM|SELECT\b.+?\bFROM)"  # DML statement...
    r"\b.*?\b(?:parameters|params|bind[_ ]?params?)\b\s*[=:]",  # ...paired with a params dump
    re.IGNORECASE | re.DOTALL,
)


# ---------------------------------------------------------------------------
# Agent-input length caps (BE-3006d)
#
# Bounded so a runaway agent cannot OOM Postgres TOAST or balloon a JSONB
# column, while staying well above any legitimate value. Surfaced on the
# @mcp.tool wrappers via ``Field(max_length=...)`` so an over-length param is
# rejected at the SDK arg-validation boundary (a clean 422-style ToolError)
# rather than reaching the service layer / a DB constraint (a 500). The wrapper
# descriptions cite these same constants so the advertised cap can never drift
# from the enforced one.
# ---------------------------------------------------------------------------
MCP_ID_MAX = 64  # a single UUID-ish identifier (project_id, from_agent, agent_id)
MCP_NAME_MAX = 200  # a name / title / assignee label
MCP_SHORT_TEXT_MAX = 2_000  # a reason / note / short summary line
MCP_MESSAGE_MAX = 20_000  # one inter-agent message body
MCP_DESCRIPTION_MAX = 20_000  # a task/project description blob
MCP_MISSION_MAX = 100_000  # an orchestrator mission / execution plan
MCP_LIST_ITEMS_MAX = 100  # recipients list, etc. (per-call item count)

# BE-9083c: per-tool inline-result size hint advertised on tools/list via the
# SDK ``meta`` kwarg (surfaces as ``_meta["anthropic/maxResultSizeChars"]``).
# Claude Code reads it to raise its inline-truncation ceiling for THESE heavy read
# tools (mission/staging/thread-history/projects), so a large-but-legitimate payload
# is delivered whole instead of being tail-truncated (the BE-9083a incident). It is
# a HINT: inert on every other harness (unknown _meta keys are ignored) and never a
# server-side cap. 500K is generous headroom over the largest real payload
# (full_protocol ~25KB + mission up to MCP_MISSION_MAX=100K).
MCP_MAX_RESULT_SIZE_CHARS = 500_000
MCP_HEAVY_TOOL_META: dict[str, int] = {"anthropic/maxResultSizeChars": MCP_MAX_RESULT_SIZE_CHARS}

# BE-6070 (F9): in-process debounce window for the per-call post-hooks
# (silent-clear probe + heartbeat). A looping agent fires many tool calls in a
# burst; only the first within this window pays the DB visit. The first call for
# a job_id always runs (check-and-set), and the silent-clear it would perform is
# already done by that first call -- so a silent->working transition is never
# delayed by the gate (an agent is only 'silent' after 10+ min of no activity).
_POSTHOOK_DEBOUNCE_SECONDS = 30


def _parse_iso_datetime_param(s: str) -> datetime | None:
    """Parse an ISO-8601 string from an MCP boundary param into a tz-aware datetime.

    CE-0034: date-only ISO strings (e.g. "2026-04-17") parse as naive datetimes.
    Coerce to UTC-aware so downstream comparisons against Postgres TIMESTAMPTZ
    don't raise ``TypeError: can't compare offset-naive and offset-aware datetimes``.
    Mirrors ``ProjectService._parse_iso_datetime``.

    Returns None for empty / falsy input. Raises ValidationError on unparseable input.
    """
    if not s:
        return None
    try:
        parsed = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise ValidationError(f"Invalid ISO-8601 datetime '{s}'. Expected e.g. '2026-01-01T00:00:00Z'.") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MCP Server instance
# ---------------------------------------------------------------------------
# INF-9371 (SDK 2.0): FastMCP is renamed MCPServer, and the four transport kwargs
# (stateless_http, json_response, streamable_http_path, transport_security) moved
# off the constructor onto streamable_http_app(). They now live with the app
# factory in mcp_sdk_server.py — the layer that owns the ASGI surface — including
# the deliberate DNS-rebinding opt-out and its rationale.
#
# INF-9115: serverInfo.version must report the GiljoAI product version, not the
# installed `mcp` package version (without it, create_initialization_options()
# falls back to the SDK's own version and every client's initialize handshake
# reports the SDK release). 1.x had no version= kwarg, so this was a
# post-construction patch of mcp._mcp_server.version; 2.0 declares the kwarg and
# makes MCPServer.version read-only, so the same guarantee is now stated at
# construction instead of patched in afterwards.
# INF-9371: tools/list is cacheable per the 2026-07-28 spec, and the SDK applies
# these hints after the handler returns. `private` is not a default we accepted but
# a requirement: the advertised roster is per-session (token scope ∩ tool profile ∩
# the BE-9084 HITL fence), so a shared cache could serve one session's roster to
# another -- an authorization leak, not a staleness bug. The TTL is deliberately
# short: a tenant flipping Headless mode in Settings changes which launch-gate tools
# are advertised, and that must take effect in about a minute, not after a long
# cache life. tools/list is cheap, so the win here is suppressing repeated calls
# inside one burst of agent activity, not long-lived caching.
_TOOLS_LIST_CACHE_TTL_MS = 60_000


def _request_state_security() -> RequestStateSecurity:
    """Seal the multi-round-trip ``requestState`` under a key EVERY worker shares.

    BE-8003l. The SDK installs ``RequestStateBoundary`` unconditionally, and when
    ``request_state_security=`` is omitted it defaults to
    ``RequestStateSecurity.ephemeral()`` -- ``keys=[os.urandom(32)]``, held only by
    the minting process. Its own docstring says the limit outright: *"Suits
    single-process deployments ... state minted by another worker is rejected.
    Multi-instance deployments must share a key."*

    Prod runs multiple uvicorn workers behind ``stateless_http=True``, so nothing
    guarantees a client's round-2 retry routes back to the worker that minted its
    token. Under the ephemeral default, a retry that lands on a different worker
    is refused with -32602 *above* the tool -- so ``request_approval``'s own
    fallback would never run. Sharing the key is what makes the MRTR round-trip
    work at all in a multi-worker deployment, and it also stops a restart
    invalidating an approval that is mid-flight.

    The key is DERIVED from the app's existing JWT secret, never reused as one. We
    hash it under our own label here, and ``AESGCMRequestStateCodec`` then runs the
    result through HKDF under the SDK's label (``mcp/request-state/v1/aes-256-gcm``),
    so the AES key is cryptographically unrelated to the one JWT signs with. That
    secret is already required at boot (``api/app.py``) and is identical across
    workers by construction, so this adds no new configuration for a self-hoster.

    Hashing is also what makes this safe to ship: the SDK REQUIRES >= 32 bytes and
    raises at construction otherwise. Secrets in the wild are routinely shorter
    than that, and this module is imported at app start -- so handing the raw
    secret over would refuse to boot the whole server on a short one. The digest
    is always 32 bytes, whatever the operator set.

    No secret configured (a bare import, a half-configured box) falls back to the
    SDK default rather than hard-failing: a single-process deployment is exactly
    the case ``ephemeral()`` is correct for.
    """
    secret = os.getenv("JWT_SECRET") or os.getenv("GILJO_MCP_SECRET_KEY") or os.getenv("SECRET_KEY")
    if not secret:
        logger.warning(
            "No JWT_SECRET/GILJO_MCP_SECRET_KEY/SECRET_KEY set; sealing MCP requestState under a "
            "per-process ephemeral key. Multi-worker deployments will refuse cross-worker retries."
        )
        return RequestStateSecurity.ephemeral()
    derived = hashlib.sha256(b"giljo/mcp/request-state/v1|" + secret.encode()).digest()
    return RequestStateSecurity(keys=[derived])


mcp = MCPServer(
    name=branding.MCP_ALIAS,
    instructions=f"{branding.DESCRIPTOR}. {branding.TWO_HUB_DISAMBIGUATION}",
    version=_giljo_version,
    cache_hints={"tools/list": CacheHint(ttl_ms=_TOOLS_LIST_CACHE_TTL_MS, scope="private")},
    request_state_security=_request_state_security(),
)


# ---------------------------------------------------------------------------
# Tool scope registry (API-0021b) + exposure profiles (WO-8003k / BE-9253) live
# in ``_scopes.py`` to keep this module under the 800-line guardrail. Re-exported
# here so every existing ``from ..._base import TOOL_SCOPES`` importer is
# unaffected (one-way import; no cycle).
# ---------------------------------------------------------------------------
from api.endpoints.mcp_tools._scopes import (  # noqa: E402,F401  (re-export surface)
    _CORE_PROFILE_TOOLS,
    _LAUNCH_GATE_TOOLS,
    _LISTING_PROFILE_TOOLS,
    _ORCHESTRATOR_PROFILE_TOOLS,
    _STANDARD_PROFILE_TOOLS,
    PROFILE_CORE,
    PROFILE_FULL,
    PROFILE_LISTING,
    PROFILE_ORCHESTRATOR,
    PROFILE_STANDARD,
    SCOPE_AGENT,
    SCOPE_READ,
    SCOPE_WRITE,
    TOOL_PROFILES,
    TOOL_SCOPES,
    _normalize_scopes,
    _profile_toolset_from_request,
    _profile_toolset_from_state,
    _scopes_from_request,
)


# ---------------------------------------------------------------------------
# Helpers: resolve app-level state inside tool handlers
# ---------------------------------------------------------------------------


def _get_tool_accessor():
    """Lazy import to avoid circular dependency with api.app at module load."""
    from api.app_state import state

    if not state.tool_accessor:
        raise RuntimeError("Tool accessor not initialized")
    return state.tool_accessor


def _get_tenant_manager():
    from api.app_state import state

    return state.tenant_manager


def _resolve_tenant(ctx: Context) -> str:
    """Extract tenant_key from ASGI scope state (set by MCPAuthMiddleware)."""
    request: StarletteRequest = ctx.request_context.request
    tenant_key = request.scope.get("state", {}).get("tenant_key")
    if not tenant_key:
        raise RuntimeError("No tenant_key in request state -- auth middleware missing")
    return tenant_key


def _resolve_user_id(ctx: Context) -> str | None:
    """Extract user_id from ASGI scope state (set by MCPAuthMiddleware).

    Returns None if the request was authenticated by an API key whose session
    has no user_id back-reference (legacy keys). Callers must treat None as
    "skip user-scoped side effects".
    """
    request: StarletteRequest = ctx.request_context.request
    return request.scope.get("state", {}).get("user_id")


def _set_tenant_context(tenant_key: str) -> None:
    """Set the current tenant for downstream DB queries."""
    _get_tenant_manager().set_current_tenant(tenant_key)


# ---------------------------------------------------------------------------
# Bound-method dispatch registry (BE-3010b)
#
# Maps an MCP tool's dispatch name to a resolver that, given the live
# ToolAccessor, returns the TERMINAL bound service method the @mcp.tool wrapper
# should call. This removes the ToolAccessor mixin's hand-copied signature from
# the parameter path for these "pure" tools: a parameter added to such a tool now
# touches exactly two non-test files (the @mcp.tool wrapper that advertises it +
# the service method that consumes it) — the registry entry is param-agnostic.
#
# Only PURE pass-throughs (forward args straight to one service method, possibly
# with bound construction deps supplied via functools.partial) live here. The ~14
# ADAPTER tools (reshape results, build envelopes, inject deps into standalone
# tool-functions, map params) are deliberately ABSENT: _call_tool falls back to
# ``getattr(accessor, method_name)`` for them, preserving their mixin logic
# verbatim. The ToolAccessor mixins remain as a thin shim for the ~50 test
# importers (deletion deferred per the WO).
#
# The dep-injecting project/task entries use functools.partial to supply the
# bound ``websocket_manager`` / ``db_manager`` the ``*_for_mcp`` methods accept —
# inspect.signature() on the partial still reports ``tenant_key`` so the
# tenant-injection below is unaffected.
# ---------------------------------------------------------------------------

ToolResolver = Callable[[Any], Callable[..., Awaitable[Any]]]

TOOL_DISPATCH: dict[str, ToolResolver] = {
    # Project tools (inject the bound websocket_manager the _for_mcp methods take)
    "create_project": lambda acc: functools.partial(
        acc._project_service.create_project_for_mcp, websocket_manager=acc._websocket_manager
    ),
    "list_projects": lambda acc: functools.partial(
        acc._project_service.list_projects_for_mcp, websocket_manager=acc._websocket_manager
    ),
    "update_project_metadata": lambda acc: functools.partial(
        acc._project_service.update_project_metadata_for_mcp, websocket_manager=acc._websocket_manager
    ),
    # Task tools
    "create_task": lambda acc: functools.partial(
        acc._task_service.create_task_for_mcp,
        db_manager=acc.db_manager,
        websocket_manager=acc._websocket_manager,
    ),
    "update_task": lambda acc: acc._task_service.update_task_for_mcp,
    "list_tasks": lambda acc: acc._task_service.list_tasks_for_mcp,
    # Roadmap tools
    "update_roadmap_metadata": lambda acc: acc._roadmap_service.upsert_metadata,
    "get_roadmap": lambda acc: acc._roadmap_service.get_roadmap,
    # Comm-thread (Agent Message Hub) tools
    "create_thread": lambda acc: acc._comm_thread_service.create_thread,
    "post_to_thread": lambda acc: acc._comm_thread_service.post_to_thread,
    "get_my_turn": lambda acc: acc._comm_thread_service.get_my_turn,
    "await_my_turn": lambda acc: acc._comm_thread_service.await_my_turn,
    "get_participant_liveness": lambda acc: acc._comm_thread_service.get_participant_liveness,
    "pass_baton": lambda acc: acc._comm_thread_service.pass_baton,
    "list_threads": lambda acc: acc._comm_thread_service.list_threads,
    "get_thread_history": lambda acc: acc._comm_thread_service.get_thread_history,
    "search_threads": lambda acc: acc._comm_thread_service.search_threads,
    # Mission / job tools
    "get_staging_instructions": lambda acc: acc._mission_service.get_staging_instructions,
    "get_job_mission": lambda acc: acc._mission_service.get_agent_mission,
    "update_job_mission": lambda acc: acc._mission_service.update_agent_mission,
    "get_workflow_status": lambda acc: acc._workflow_status_service.get_workflow_status,
    "report_progress": lambda acc: acc._progress_service.report_progress,
    "complete_job": lambda acc: acc._job_completion_service.complete_job,
    "close_job": lambda acc: acc._agent_state_service.close_job,
    "reactivate_job": lambda acc: acc._agent_state_service.reactivate_job,
    "dismiss_reactivation": lambda acc: acc._agent_state_service.dismiss_reactivation,
    "spawn_job": lambda acc: acc._orchestration_service.spawn_job,
}


def _resolve_tool_func(accessor: Any, method_name: str) -> Callable[..., Awaitable[Any]]:
    """Resolve the callable for a dispatched tool.

    Pure tools resolve to their terminal bound service method via TOOL_DISPATCH;
    every other (ADAPTER) tool falls back to the ToolAccessor mixin method, exactly
    as before BE-3010b.
    """
    resolver = TOOL_DISPATCH.get(method_name)
    if resolver is not None:
        return resolver(accessor)
    return getattr(accessor, method_name)


async def _call_tool(ctx: Context, method_name: str, kwargs: dict[str, Any]) -> Any:
    """
    Central dispatch: resolve tenant, inject tenant_key, call the tool's bound
    service method (BE-3010b: pure tools dispatch straight to the terminal service
    via TOOL_DISPATCH; adapter tools fall back to the ToolAccessor mixin).

    Mirrors the security logic from validate_and_override_tenant_key():
    - Inspects method signature to decide whether tenant_key is accepted
    - Always injects session tenant_key (never trust client-supplied value)
    - Strips tenant_key from kwargs if the method doesn't accept it

    After successful execution, auto-clears 'silent' status if the calling
    agent was marked silent (restores to 'working' + updates last_progress_at).
    """
    tenant_key = _resolve_tenant(ctx)
    _set_tenant_context(tenant_key)

    # Per-tool MCP call counting (feeds dashboard statistics badge)
    from api.app_state import state as app_state

    app_state.mcp_call_count[tenant_key] = app_state.mcp_call_count.get(tenant_key, 0) + 1

    accessor = _get_tool_accessor()
    tool_func = _resolve_tool_func(accessor, method_name)

    # Signature-based tenant_key injection
    sig = inspect.signature(tool_func)
    if "tenant_key" in sig.parameters:
        kwargs["tenant_key"] = tenant_key
    else:
        kwargs.pop("tenant_key", None)

    # BE-3006d: sanitizing catch-all at the single dispatch chokepoint.
    #
    # The SDK wraps ANY exception escaping the tool wrapper and serialises
    # ``str(e)`` straight onto the wire (isError=True). An unexpected DB error
    # therefore leaks ``[SQL: ...] [parameters: ...]`` to the calling agent.
    # INF-9371: still true on SDK 2.0 — MCPServer._handle_call_tool catches every
    # non-MCPError exception and returns ``CallToolResult(is_error=True,
    # content=[TextContent(str(e))])``, so this chokepoint remains the only thing
    # standing between a driver string and the agent. We classify here:
    #   - Curated client errors (BaseGiljoError < 500) carry actionable,
    #     agent-authored context (valid_types, blockers, ...) -> surface verbatim.
    #   - Validation/tool rejections (pydantic.ValidationError is a ValueError in
    #     v2; MCPServerError; the structured memory-write rejection) are already
    #     clean 422-style and never contain SQL -> surface verbatim.
    #   - Server-side BaseGiljoError (>= 500) may embed a raw driver string in
    #     ``.context`` (e.g. OrchestrationError(context={'error': str(db_err)})),
    #     and every other unexpected exception (SQLAlchemyError & friends) carries
    #     SQL text + bind params in ``str()`` -> log full detail server-side and
    #     raise a generic, sanitized ToolError that exposes none of it.
    try:
        result = await tool_func(**kwargs)
    except CursorRejectedError as exc:
        # BE-9469: a refused continuation cursor is a Tier-2 DELIBERATE REJECTION, not an
        # error -- see the two-tier contract below. It is raised deep in the read layer
        # (where the filter fingerprint is known) and converted to the structured response
        # HERE, at the one boundary both list tools pass through, so the two tools cannot
        # drift into two different refusal shapes.
        #
        # Why a return and not an isError: the agent can FIX this by restarting the walk,
        # and the message says exactly how. A transport error makes it guess whether the
        # server is broken; a structured rejection on the success path hands it a remedy it
        # can read like any other tool content.
        logger.info("MCP tool '%s' refused a continuation cursor: %s", method_name, exc.code)
        return {"success": False, "error": exc.code, "message": str(exc)}
    except BaseGiljoError as exc:
        if exc.default_status_code < 500:
            raise
        logger.exception("MCP tool dispatch '%s' failed with a server-side error", method_name)
        raise MCPServerError(_SANITIZED_TOOL_ERROR) from exc
    except MCPServerError:
        raise
    except TenantIsolationError as exc:
        # Cross-tenant access: a known security-boundary rejection. Log the full
        # guard detail server-side, but never surface its str() (it embeds the
        # model name + internal guard phrasing) and never sanitize it to the
        # generic 500 — re-raise the clean, fixed not-found contract instead.
        logger.warning("MCP tool dispatch '%s' blocked by tenant isolation guard", method_name)
        raise MCPServerError(_NOT_FOUND_TOOL_ERROR) from exc
    except _CLEAN_VALIDATION_ERRORS as exc:
        # pydantic ValidationError + clean 422-style rejections surface VERBATIM.
        # TSK-9134: unless the message carries a SQL/bind-param leak signature ->
        # log full detail server-side, sanitize before the wire.
        if _SQL_LEAK_SIGNATURE.search(str(exc)):
            logger.exception(
                "MCP tool dispatch '%s' raised a ValueError/TypeError carrying a "
                "SQL/bind-parameter leak signature; sanitizing before it reaches the agent",
                method_name,
            )
            raise MCPServerError(_SANITIZED_TOOL_ERROR) from exc
        raise
    except Exception as exc:
        logger.exception("MCP tool dispatch '%s' raised an unexpected error", method_name)
        raise MCPServerError(_SANITIZED_TOOL_ERROR) from exc

    # ------------------------------------------------------------------
    # BE-6081: the TWO-TIER MCP-boundary error contract — the single
    # reconciled rule for post-0480 ("all Python layers raise on error,
    # never return {success: False}") vs the BE-5028 structured-response
    # contract. They are NOT in tension; they govern different cases:
    #
    #   Tier 1 — ERRORS RAISE (post-0480). Service-layer failures and any
    #   unexpected tool error propagate as exceptions and are classified by
    #   the try/except above into an MCPServerError -> the SDK serialises them as
    #   isError on the wire. No tool RETURNS {success: False} for an error.
    #
    #   Tier 2 — DELIBERATE domain REJECTIONS RETURN (BE-5028). A few tool
    #   implementations return a structured ``{"success": False, "error":
    #   <CODE>, ...}`` dict for an EXPECTED, agent-actionable declined request
    #   that carries fields the agent needs to self-correct — a *response*,
    #   not an error. No exception is raised, so it flows through the success
    #   path below UNCHANGED and reaches the agent as normal tool content
    #   (NOT isError). Known sites: write_memory_entry (GIT_COMMITS_REQUIRED,
    #   CLOSEOUT_BLOCKED, ORCHESTRATOR_ONLY_ENTRY_TYPE), get_context
    #   (agent-execution not-found), request_approval
    #   (ORCHESTRATOR_ONLY_APPROVAL — BE-9054 worker rejection), and
    #   post_to_thread's wrapper (FROM_AGENT_REQUIRED /
    #   FROM_AGENT_AS_USER_EXCLUSIVE — BE-9379 attribution fail-closed,
    #   returned before dispatch so a refused post writes nothing), and
    #   update_task's convert_to_project branch (CONVERT_FIELD_CONFLICT /
    #   USER_CONTEXT_REQUIRED — BE-9382, returned before the conversion runs
    #   so a refused promotion writes nothing), and list_projects/list_tasks'
    #   continuation cursor (CURSOR_MALFORMED / CURSOR_FILTER_MISMATCH /
    #   CURSOR_AXIS_MISMATCH / CURSOR_VERSION_UNSUPPORTED — BE-9469; raised in
    #   the read layer where the filter fingerprint is known, converted to this
    #   shape by the except clause above, and returned before any fetch runs so a
    #   refused cursor costs no query), and apply_context_tuning
    #   (NO_SECTIONS_APPLIED — BE-9473 F3; every drift-flagged proposal failed
    #   to resolve to a real product field, returned before any DB write or
    #   tuning_state stamp so a failed write cannot be mistaken for a
    #   completed review).
    #
    # The post-0480 raise-rule governs Tier-1 internal errors ONLY; it does
    # not forbid these intentional Tier-2 rejection responses. Regression:
    # tests/integration/test_be6081_mcp_boundary_contract.py.
    # ------------------------------------------------------------------

    # BE-6070 (F9): post-hooks on any successful MCP interaction -- silent-clear
    # probe + server-side heartbeat. Both pay a DB round-trip every call today.
    # Gate them behind ONE in-process monotonic debounce per job_id (skip BOTH
    # with zero DB touch in the rapid-call common case), and when they DO run,
    # share ONE session for both hooks instead of opening two.
    job_id = kwargs.get("job_id")
    if job_id and should_run("mcp_posthooks", job_id, _POSTHOOK_DEBOUNCE_SECONDS):
        try:
            from api.app_state import state as app_state
            from giljo_mcp.services.heartbeat import touch_heartbeat
            from giljo_mcp.services.silence_detector import auto_clear_silent

            ws_manager = getattr(app_state, "websocket_manager", None)
            async with app_state.db_manager.get_session_async() as db:
                # Auto-clear silent (~0.1% case). BE-9303: only when job_id is the
                # CALLER'S OWN job — a bystander read ABOUT a stalled job used to
                # disarm close_job's recovery hint. Classification: _silence_scope.
                if method_name in SILENCE_CLEARING_TOOLS:
                    try:
                        await auto_clear_silent(db, job_id, ws_manager, tenant_key=tenant_key)
                    except (OSError, RuntimeError, ValueError, TypeError, AttributeError, KeyError):
                        logger.warning("auto_clear_silent failed for job_id=%s (non-blocking)", job_id)

                # Server-side heartbeat: last_activity_at (its own WHERE-debounce).
                try:
                    await touch_heartbeat(db, job_id, tenant_key=tenant_key)
                except (OSError, RuntimeError, ValueError, TypeError, AttributeError, KeyError):
                    logger.debug("heartbeat update failed for job_id=%s (non-blocking)", job_id)
        except (OSError, RuntimeError, ValueError, TypeError, AttributeError, KeyError):
            logger.debug("post-hooks failed for job_id=%s (non-blocking)", job_id)

    # Wire-contract normalisation: every @mcp.tool wrapper in this module is
    # annotated `-> dict[str, Any]`, but service-layer methods return typed
    # Pydantic response models (MissionResponse, ProgressResult, SpawnResult,
    # SendMessageResult, etc.). The SDK validates the return against the
    # annotation and rejects Pydantic instances with a DictModel error, which
    # surfaces to MCP clients while server-side state has already been
    # persisted. Normalise here so every tool produces a JSON-safe dict
    # regardless of which service layer it delegates to.
    if isinstance(result, BaseModel):
        result = result.model_dump(mode="json")

    # IMP-6038: echo the server's bundled SKILLS_VERSION on every dict tool
    # response. The installed skills read this from `_meta` and, once per
    # session, advise the user to re-run /giljo_setup if their bundle is older.
    # Single shared response path -- no per-tool hand-editing.
    if isinstance(result, dict):
        meta = result.get("_meta")
        if not isinstance(meta, dict):
            meta = {}
        meta["skills_version"] = _SKILLS_VERSION
        result["_meta"] = meta
    return result
