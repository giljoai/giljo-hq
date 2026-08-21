# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
MCP transport-layer helpers -- Streamable HTTP edge handling for the MCP SDK server.

BE-9060 (item 1): these transport primitives were split out of
``api.endpoints.mcp_sdk_server`` (the hottest file in the repo) into this module.
They are the pre-auth / wire-level helpers the ASGI auth middleware composes:
body buffer-and-replay, the raw-ASGI status emitters (405 / 413), JSON-RPC body
peeking, protocol-version validation, the Mcp-Session-Id send wrapper, the
WWW-Authenticate + JSON-RPC error response builders, and the best-effort session
"stamp" helpers that surface a declared tool profile / detected harness onto ASGI
state. Behavior is unchanged -- these were extracted verbatim; ``mcp_sdk_server``
re-exports every name so existing importers keep working.
"""

import json
from typing import Any
from urllib.parse import parse_qs

from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

# One-way imports (no cycle): oauth exposes the supported-spec list; mcp_tools owns
# the shared logger + the tool-profile registry. Neither imports this module.
from api.endpoints.mcp_tools import TOOL_PROFILES, logger
from api.endpoints.oauth import MCP_SPEC_VERSIONS_SUPPORTED
from giljo_mcp.http.url_resolver import get_canonical_mcp_resource_uri_from_scope


# INF-9371: keep new codes at the LOW end of this range. The 2026-07-28 spec
# reserves -32020..-32099, and that is not theoretical any more -- mcp 2.0.0 emits
# -32020 itself ("mcp-method header does not match the request body's method"),
# observed on the wire 2026-08-14. -32001 below is clear of it.
#
# JSON-RPC implementation-defined server-error code (reserved -32000..-32099) for
# a tenant whose subscription is not active. Surfaces the canonical activation
# copy to the MCP client as the error message.
_SUBSCRIPTION_REQUIRED_CODE = -32001


def _subscription_required_response(message: str, request_id=None) -> JSONResponse:
    """Build a JSON-RPC-compatible 403 for a tenant with no active subscription.

    The body is a JSON-RPC 2.0 error envelope so an MCP client renders ``message``
    (the canonical "Please activate your subscription to keep working." copy) as
    the tool error text rather than a cryptic transport failure. ``id`` is echoed
    when known, else ``null`` (valid per JSON-RPC for an undeterminable id).
    """
    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": _SUBSCRIPTION_REQUIRED_CODE, "message": message},
        },
        status_code=403,
    )


def _build_www_authenticate_header(scope: Scope) -> str:
    """Construct the RFC 6750 WWW-Authenticate value for /mcp 401s.

    Includes the RFC 9728 `resource_metadata` parameter pointing at the
    protected-resource document. Spec-compliant clients (Claude.ai, MCP CLI)
    use it to bootstrap themselves after a 401 instead of failing closed.
    """
    canonical = get_canonical_mcp_resource_uri_from_scope(scope)
    base, _, _ = canonical.rpartition("/mcp")
    metadata_url = f"{base}/.well-known/oauth-protected-resource"
    return f'Bearer realm="MCP", resource_metadata="{metadata_url}"'


def _unauthenticated_response(scope: Scope, error: str, status_code: int = 401) -> JSONResponse:
    """Build a 401/403 JSONResponse with the spec-required WWW-Authenticate header."""
    return JSONResponse(
        {"error": error},
        status_code=status_code,
        headers={"WWW-Authenticate": _build_www_authenticate_header(scope)},
    )


# ---------------------------------------------------------------------------
# API-0021j: MCP-Protocol-Version + Mcp-Session-Id transport-layer helpers
#
# Streamable HTTP spec requires:
#   - Non-initialize requests with an unsupported MCP-Protocol-Version → 400
#     (NOT 401 — clients use this to negotiate; auth is downstream of it).
#   - Initialize responses carry an Mcp-Session-Id; subsequent requests echo
#     it and the server MUST return 404 on unknown / expired / cross-tenant
#     ids (matches SDK behavior at streamable_http.py:498).
#
# Single source of truth: import MCP_SPEC_VERSIONS_SUPPORTED from
# api.endpoints.oauth — locked by tests/api/test_spec_conformance.py. The
# frozenset below is a derived O(1) membership view, not a parallel constant.
# ---------------------------------------------------------------------------


_SUPPORTED_VERSIONS: frozenset[str] = frozenset(MCP_SPEC_VERSIONS_SUPPORTED)
_DEFAULT_SPEC_VERSION = "2025-03-26"
_INITIALIZE_METHOD = "initialize"


async def _read_full_body(receive: Receive, *, max_bytes: int | None = None) -> bytes:
    """Drain the ASGI request body in full, optionally capping the total size.

    Returns the concatenated bytes. The middleware buffers the body once so the
    JSON-RPC method can be peeked before the inner ASGI app is invoked; the
    buffered bytes are then replayed via :func:`_replay_receive`.

    BE-6060a: when ``max_bytes`` is set, a running counter aborts the read with
    :class:`_BodyTooLargeError` as soon as the streamed total exceeds the cap
    (Layer 2 of the two-layer guard; Layer 1 is the Content-Length pre-check in
    the middleware). This keeps an unauthenticated oversize body from being
    buffered in full before auth.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            break
        if message["type"] != "http.request":
            break
        chunk = message.get("body", b"")
        if max_bytes is not None:
            total += len(chunk)
            if total > max_bytes:
                raise _BodyTooLargeError
        chunks.append(chunk)
        if not message.get("more_body", False):
            break
    return b"".join(chunks)


def _replay_receive(body: bytes, original_receive: Receive) -> Receive:
    """Build a ``receive`` that yields ``body`` once, then delegates to the real stream.

    BE-6060a: the prior implementation synthesized ``{"type": "http.disconnect"}``
    on every call after the first. For a long-lived GET/SSE stream the SDK's
    ``await receive()`` then observed an immediate fake disconnect and
    sse_starlette closed the stream instantly — spec-compliant TS SDK clients
    re-polled every 1000ms forever. Delegating to ``original_receive`` after the
    buffered frame restores the real client-driven backpressure: the inner app
    blocks on the actual connection instead of a fabricated disconnect.
    """
    sent = {"done": False}

    async def _receive() -> dict:
        if not sent["done"]:
            sent["done"] = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await original_receive()

    return _receive


# BE-6060a: pre-auth body-size cap. _read_full_body buffered the request body
# UNBOUNDED before auth ran, so an unauthenticated client could pin worker
# memory (DoS). 5 MB comfortably exceeds any legitimate JSON-RPC tool call.
_MAX_MCP_BODY_BYTES = 5 * 1024 * 1024


class _BodyTooLargeError(Exception):
    """Raised by _read_full_body when the streaming body exceeds the cap."""


async def _send_raw_status(send: Send, *, status: int, headers: list[tuple[bytes, bytes]] | None = None) -> None:
    """Emit a bodyless raw-ASGI response.

    Used for the pre-auth 405 / 413 edges: the middleware is RAW ASGI here, so
    we cannot raise HTTPException and expect FastAPI to catch it — we drive
    ``send`` directly. The response carries NO body and is NOT text/event-stream,
    so a spec-compliant client treats it as terminal (no SSE re-poll).
    """
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": headers or [],
        }
    )
    await send({"type": "http.response.body", "body": b""})


async def _send_method_not_allowed(send: Send) -> None:
    """Emit 405 for GET /mcp with ``Allow: POST, DELETE`` and no SSE retry hint.

    The TS SDK special-cases 405 in ``_startOrAuthSse`` and permanently stops
    GET polling, which is exactly what kills the re-poll storm. Critically this
    response must NOT be ``text/event-stream`` and must NOT carry a ``retry:``
    field, or the client would treat it as a transient SSE close and retry.
    """
    await _send_raw_status(
        send,
        status=405,
        headers=[(b"allow", b"POST, DELETE")],
    )


def _peek_jsonrpc_method(body: bytes) -> str | None:
    """Return the JSON-RPC ``method`` if the body decodes cleanly, else ``None``.

    Malformed bodies are tolerated — the inner SDK will respond with the
    canonical JSON-RPC error, and the middleware short-circuits no further
    on its own. Header-version + session-id flows treat missing-method as
    'not initialize' (the safe default).
    """
    if not body:
        return None
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None
    if isinstance(payload, dict):
        method = payload.get("method")
        return method if isinstance(method, str) else None
    return None


def _peek_jsonrpc_client_info(body: bytes) -> dict[str, Any] | None:
    """Return the JSON-RPC ``params.clientInfo`` dict for an ``initialize`` body, else ``None``.

    Same tolerate-malformed-body policy as :func:`_peek_jsonrpc_method` — a
    parse failure or missing/malformed field yields ``None`` rather than
    raising; the inner SDK owns the authoritative error path. This is a hint
    for session bookkeeping, never a security boundary (INF-8003d DoD #3's
    out-of-scope note).
    """
    if not body:
        return None
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    params = payload.get("params")
    if not isinstance(params, dict):
        return None
    client_info = params.get("clientInfo")
    return client_info if isinstance(client_info, dict) else None


def _peek_jsonrpc_protocol_version(body: bytes) -> str | None:
    """Return the JSON-RPC ``params.protocolVersion`` for an ``initialize`` body, else ``None``.

    INF-9371: the protocol revision a client asks for is decided once, at
    ``initialize``, and never restated on later requests. Without capturing it here
    every question about which revision the live fleet actually speaks can only be
    answered by INFERENCE from the client's generation (TSK-9425 hit exactly that
    wall). Persisting it makes the next such question observable.

    Same tolerate-malformed-body policy as the sibling peeks: a parse failure or a
    missing/malformed field yields ``None``. Bookkeeping, never a security boundary —
    the authoritative version gate is :func:`_validate_protocol_version`.
    """
    if not body:
        return None
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    params = payload.get("params")
    if not isinstance(params, dict):
        return None
    version = params.get("protocolVersion")
    return version if isinstance(version, str) else None


def _peek_jsonrpc_capabilities(body: bytes) -> dict[str, Any] | None:
    """Return the JSON-RPC ``params.capabilities`` dict for an ``initialize`` body, else ``None``.

    BE-9449: what a client DECLARES it can do is stated once, at ``initialize``, and
    never restated. It is also the only signal that separates Claude Desktop from
    claude.ai web — two client surfaces can send byte-identical clientInfo, so the
    desktop-vs-chat axis cannot come from clientInfo and must come from the
    capability vector.

    Returned VERBATIM and unfiltered, by design: the point is seeing what clients
    actually send, including keys no spec declares. A filtered copy cannot answer
    a question about client behavior nobody anticipated when the filter was written.

    Same tolerate-malformed-body policy as the sibling peeks: a parse failure or a
    missing/malformed field yields ``None``. Bookkeeping, never a security boundary —
    nothing here gates auth, and the declared vector is a hint about the client, not a
    claim this server trusts.
    """
    if not body:
        return None
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    params = payload.get("params")
    if not isinstance(params, dict):
        return None
    capabilities = params.get("capabilities")
    return capabilities if isinstance(capabilities, dict) else None


def _unsupported_version_response(version: str) -> JSONResponse:
    """Build the 400 response for an unsupported MCP-Protocol-Version header."""
    return JSONResponse(
        {
            "error": "Unsupported MCP-Protocol-Version",
            "requested": version,
            "supported": list(MCP_SPEC_VERSIONS_SUPPORTED),
        },
        status_code=400,
    )


def _not_found_response(detail: str) -> JSONResponse:
    """Build the 404 response for an invalid / expired / cross-tenant session id."""
    return JSONResponse({"error": detail}, status_code=404)


def _validate_protocol_version(request: StarletteRequest, method: str | None) -> JSONResponse | None:
    """Phase 1 validator. Returns a 400 response if the header is unsupported, else ``None``.

    Initialize requests are exempt because negotiation lives in JSON-RPC
    params (spec 2025-06-18 §Transport). Missing header on non-initialize
    SHOULD-defaults to 2025-03-26 — accepted with a debug log.
    """
    if method == _INITIALIZE_METHOD:
        return None
    version = request.headers.get("mcp-protocol-version")
    if version is None:
        logger.debug(
            "No MCP-Protocol-Version header on %s; defaulting to %s per spec",
            method or "<no-method>",
            _DEFAULT_SPEC_VERSION,
        )
        return None
    if version not in _SUPPORTED_VERSIONS:
        logger.info("Rejecting unsupported MCP-Protocol-Version=%r on method=%r", version, method)
        return _unsupported_version_response(version)
    return None


def _wrap_send_with_session_id(send: Send, session_id: str) -> Send:
    """Return a Send that injects ``Mcp-Session-Id`` into the first response start frame."""

    async def _send(message: dict) -> None:
        if message["type"] == "http.response.start":
            headers = list(message.get("headers", []))
            headers.append((b"mcp-session-id", session_id.encode("ascii")))
            message = {**message, "headers": headers}
        await send(message)

    return _send


# WO-8003k: the well-known key inside the (d)-captured ``client_info`` blob a
# session uses to DECLARE its tool profile (core/standard/full). Reusing the
# client_info vehicle keeps this out of a second declaration mechanism; the value
# is validated against TOOL_PROFILES before it is trusted (a garbage value is
# ignored, degrading to the auth-derived default).
_DECLARED_PROFILE_CLIENT_INFO_KEY = "giljo_tool_profile"


def _stamp_declared_profile(scope: Scope, session_row: Any) -> None:
    """Stamp a session-declared tool profile from ``client_info`` onto ASGI state.

    Reads the declared profile out of the loaded session's
    ``session_data['client_info']`` (the INF-8003d capture) and, when it names a
    known profile, writes it to ``scope['state']['tool_profile']`` so
    :func:`_profile_toolset_from_request` can honor "declared wins". Best-effort:
    any missing/malformed field leaves state untouched (falls back to the
    auth-derived default). Never raises — a bookkeeping hint, not a security gate.
    """
    session_data = getattr(session_row, "session_data", None)
    if not isinstance(session_data, dict):
        return
    client_info = session_data.get("client_info")
    if not isinstance(client_info, dict):
        return
    declared = client_info.get(_DECLARED_PROFILE_CLIENT_INFO_KEY)
    if isinstance(declared, str) and declared in TOOL_PROFILES:
        scope.setdefault("state", {})["tool_profile"] = declared


# BE-9253: the query parameter on the PUBLISHED connector URL
# (``https://<host>/mcp?profile=listing``) that selects a narrower tool profile.
# We author the URL the marketplace directory publishes, so this is a
# server-controlled vehicle — unlike ``clientInfo``, which a third-party client
# authors. It resolves into the SAME ``state['tool_profile']`` slot rung 1 of
# ``_profile_toolset_from_state`` already reads: one selection mechanism, one
# filter path, no new resolver rung.
_URL_PROFILE_QUERY_PARAM = "profile"


def _stamp_url_profile(scope: Scope) -> None:
    """Stamp a URL-selected tool profile onto ASGI state — NARROWING ONLY.

    Reads ``?profile=<name>`` off the ASGI ``query_string`` and writes it to
    ``scope['state']['tool_profile']`` **only when doing so cannot enlarge the
    session's tool set**. The invariant this function guarantees:

        resolve(state after this call) ⊆ resolve(state before this call)

    which is enforced structurally, by resolving the baseline through the very
    same :func:`_profile_toolset_from_state` the request will later use and
    refusing any candidate that is not a subset of it. Two consequences worth
    naming:

    * ``?profile=full`` is refused outright. ``TOOL_PROFILES['full']`` IS the
      ``None`` "no restriction" sentinel, so the single ``candidate is None``
      test below rejects the unrestricted profile and an unknown profile name
      with one branch — a URL can never reach the full surface.
    * The check is a real subset test, not an allowlist of ``{listing}``:
      ``listing`` is NOT a subset of ``core`` or ``standard`` (it carries
      ``update_project``), so a name-only allowlist would have let the URL widen
      those sessions by a tool.

    This runs AFTER the declared-profile stamp, so a session that declared a
    profile has that declaration as its baseline and the URL may only narrow
    within it. With no ``profile`` parameter present, state is left untouched and
    resolution is byte-identical to pre-BE-9253.

    Deliberately does NOT touch the pre-existing declared-``full`` widening path
    (BE-8003k rung 1, fenced independently by BE-9084): that is a separate,
    load-bearing vehicle. The narrow-only rule governs this URL vehicle alone.
    """
    from api.endpoints.mcp_tools import _profile_toolset_from_state

    raw = scope.get("query_string") or b""
    if not raw:
        return
    query = raw.decode("latin-1") if isinstance(raw, bytes) else str(raw)
    values = parse_qs(query).get(_URL_PROFILE_QUERY_PARAM)
    if not values:
        return
    requested = values[0]
    candidate = TOOL_PROFILES.get(requested)
    if candidate is None:
        # Unknown profile name, or the unrestricted `full` sentinel. Neither may
        # ever be reached from a URL.
        return
    state = scope.setdefault("state", {})
    baseline = _profile_toolset_from_state(state)
    if baseline is not None and not candidate <= baseline:
        return
    state["tool_profile"] = requested


def _stamp_resolved_harness(scope: Scope, session_row: Any) -> None:
    """Stamp the persisted DETECTED harness onto ASGI state (BE-9035d).

    ``FastMCP(stateless_http=True)`` drops the ``initialize`` clientInfo on every
    non-initialize tools/call, so ``_detected_harness`` cannot read the live
    ``ctx.session.client_params`` on the render path — it always saw ``generic`` and
    a claude-code CLI got the ``<your-harness>`` generic ladder instead of the
    Claude-native ``Task(subagent_type=...)`` prose (FINDING #4). BE-9035b already
    persisted the resolved token to ``session_data['resolved_harness']`` at the
    initialize-time capture; this stamps it onto ``scope['state']`` off the
    already-loaded session row so the tool render can read it without a second DB
    hit (mirrors :func:`_stamp_declared_profile`). Only a CONCRETE (non-generic)
    token is stamped — a generic/absent value leaves state untouched so the declared
    CLI hint still governs. Best-effort, never raises — a render hint, not a gate.

    BE-9036 — WHY THIS SURVIVED THE SDK 2.0 CAPABILITY AXIS (stamp leg of three).
    SDK 2.0 carries client identity and capabilities per request, so this stamp looked
    like dead weight after INF-9371. It is not: the per-request carrier is the
    2026-07-28 reserved ``_meta`` envelope, and a handshake-era client never sends one.
    Measured on mcp 2.0.0 over the real ASGI stack with our shipped
    ``stateless_http=True``, a 2025-era ``tools/call`` arrives with client_capabilities
    None AND client_params None. The live fleet is exactly that. So this stamp is still
    the ONLY way the render path learns the harness, and it is load-bearing until the
    fleet moves to the modern era — at which point it becomes redundant rather than
    wrong. Pinned by ``tests/integration/test_be9036_capability_axis_by_era.py``.
    """
    from giljo_mcp.platform_registry import GENERIC_HARNESS

    session_data = getattr(session_row, "session_data", None)
    if not isinstance(session_data, dict):
        return
    resolved = session_data.get("resolved_harness")
    if isinstance(resolved, str) and resolved and resolved != GENERIC_HARNESS:
        scope.setdefault("state", {})["resolved_harness"] = resolved


def _stamp_resolved_preset(scope: Scope, session_row: Any) -> None:
    """Stamp the persisted DETECTED harness PRESET onto ASGI state (BE-9327).

    The preset axis has the same stateless_http problem :func:`_stamp_resolved_harness`
    solves for the harness axis: the preset is derivable only from the ``initialize``
    clientInfo, which ``FastMCP(stateless_http=True)`` drops on every later tools/call
    — and ``giljo_setup``, the tool that branches on it, is always a tools/call. Reads
    the token persisted at the initialize-time capture off the already-loaded session
    row, so no second DB hit is needed.

    A session row written before BE-9327 has no ``resolved_preset`` key, and a terminal
    CLI resolves to ``None``; both leave state untouched, so the declared-harness path
    still governs and the render is byte-identical to today. Best-effort, never raises
    — a render hint, not a gate.

    BE-9036: kept for the same measured reason as :func:`_stamp_resolved_harness` — a
    2025-era client sends no per-request envelope, so nothing about it reaches a
    ``tools/call`` except what was persisted at initialize and stamped here.
    """
    session_data = getattr(session_row, "session_data", None)
    if not isinstance(session_data, dict):
        return
    resolved = session_data.get("resolved_preset")
    if isinstance(resolved, str) and resolved:
        scope.setdefault("state", {})["resolved_preset"] = resolved
