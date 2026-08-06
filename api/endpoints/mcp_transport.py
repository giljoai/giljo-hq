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
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, NamedTuple
from urllib.parse import parse_qs

from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

# One-way imports (no cycle): oauth exposes the supported-spec list; mcp_tools owns
# the shared logger + the tool-profile registry. Neither imports this module.
from api.endpoints.mcp_tools import TOOL_PROFILES, logger
from api.endpoints.oauth import MCP_SPEC_VERSIONS_SUPPORTED
from giljo_mcp.http.url_resolver import get_canonical_mcp_resource_uri_from_scope


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


# ---------------------------------------------------------------------------
# TSK-9309: absorbed-argument diagnosis.
#
# A caller's tool-call serialization can merge one argument into the string value
# of a neighbouring one: the following argument never leaves the caller, and the
# server sees a payload genuinely missing a required field. The bare pydantic
# "key_outcomes / Field required" that results is TRUE about the payload received
# and WRONG about the cause — it sends the caller off to rewrite an argument it
# supplied correctly (one real session spent eight tool calls doing exactly that,
# on a write_project_closeout whose summary ended '...</key_outcomes>...</invoke>').
#
# Measured, so the diagnosis below is not guesswork: the FastMCP argument boundary
# validates a 180 KB payload with the field intact, and _read_full_body/
# _replay_receive replay 2 MB byte-identically in one frame and in 17-byte frames.
# Nothing server-side drops the field, and there is no cap to raise.
#
# BE-9348 widened this. It no longer runs ONLY once a required argument is absent:
# when absorption swallows an OPTIONAL argument, every required one is still present,
# the call is ACCEPTED, and the residue is persisted verbatim — the same defect with
# no error at all. So the scan now runs on well-formed-looking calls too, and it CAN
# refuse one. That is a deliberate trade, and it is what the two extra conditions on
# the nothing-missing path exist to bound: conclusive evidence only, plus a tail that
# is pure call syntax AND carries an actual serialized value.
# ---------------------------------------------------------------------------

# Unparsed tool-call markup sitting inside a string value: the caller's own call
# syntax, which no legitimate prose argument contains.
_TOOLCALL_MARKUP_RESIDUE = re.compile(r"</\w*:?invoke>|<parameter\s+name=", re.IGNORECASE)

# The named form of that markup, used to recover WHICH argument was absorbed so the
# rejection can name it (BE-9348).
_PARAMETER_NAME_TAG = re.compile(r"<parameter\s+name=\"(\w+)\"", re.IGNORECASE)

# The tail of an absorbed JSON list ('..."]'), left behind when a list-valued
# argument is swallowed into the preceding string.
_ABSORBED_ARRAY_TAIL = ('"]', "']")

# Structural leftovers of a serialized tool call: tags, quoted strings, and JSON
# punctuation. What survives stripping these from a tail is ordinary prose.
_MARKUP_TAG = re.compile(r"<[^>]*>")
_QUOTED_STRING = re.compile(r'"(?:[^"\\]|\\.)*"')
_JSON_PUNCTUATION = re.compile(r"[\[\]{}:,\s]")

# The opening character of a STRUCTURED argument value ('["docs", "chore"]'). A bare
# angle-bracket PLACEHOLDER in ordinary prose ("Usage: giljo close <project_id>") leaves
# nothing once the tag is stripped. Without this, stripping the tag alone reduces the
# placeholder to empty and the tail reads as "pure call syntax" with no absorbed value
# present at all — which refused ordinary sentences across 117 parameter names, among
# them 'name', 'title', 'status' and 'description'.
_VALUE_OPENER = re.compile(r"[\[{\"]")

# A bare JSON scalar ('3', 'true', 'null'). An absorbed argument does NOT always bring a
# bracket: a scalar-valued parameter leaves a bare token behind, and 15 string->scalar
# adjacencies exist on the live surface (e.g. spawn_job mission->phase). The scalar
# allowance is gated on the serializer's own <parameter name="..."> markup — NOT because
# prose cannot contain that markup (it demonstrably can: post_to_thread.content,
# spawn_job.mission and write_memory_entry.summary all legitimately quote it), but
# because the gate is strictly cheaper there. Ungated, a bare digit would refuse
# "…<project_id> 2026"; gated, the refusals are confined to text that already carries
# the harness's own call syntax.
_JSON_SCALAR = re.compile(r"\b(?:true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
_VALUE_TOKEN = re.compile(r"[\[{\"]|\b(?:true|false|null)\b|-?\d")


class _Residue(NamedTuple):
    """Evidence that a string argument absorbed a following one.

    ``absorbed`` is the parameter name the residue names when it can be recovered
    (``None`` when the markup is anonymous, e.g. a bare ``</invoke>``). ``start`` is
    where the residue begins, so the tail after it can be examined.
    """

    description: str
    conclusive: bool
    absorbed: str | None
    start: int


def _absorption_residue(
    value: str,
    parameter_names: Iterable[str],
    *,
    self_param: str | None = None,
) -> _Residue | None:
    """Describe the evidence that ``value`` absorbed a following argument, else ``None``.

    Markup residue and an inline parameter tag are the caller's own call syntax sitting
    inside a string value, which no legitimate prose contains — those are conclusive. A
    bare JSON-list tail is suggestive but not proof: a summary CAN legitimately end that
    way. TSK-9309b keeps that signal (it costs nothing on an already-failing call) but
    the caller is told so, because asserting a cause on the weakest evidence available is
    a smaller version of the defect this whole diagnosis exists to correct.

    BE-9348: ``self_param`` is skipped when matching inline tags. A value that contains
    its OWN closing tag says nothing about a FOLLOWING argument, and treating it as
    evidence produced advice as useless as "re-send with a shorter 'project_id'" for a
    64-character UUID.
    """
    match = _TOOLCALL_MARKUP_RESIDUE.search(value)
    if match:
        named = _PARAMETER_NAME_TAG.search(value)
        absorbed = named.group(1) if named else None
        if absorbed is not None and (absorbed == self_param or absorbed not in parameter_names):
            absorbed = None
        return _Residue(
            description="unparsed tool-call markup",
            conclusive=True,
            absorbed=absorbed,
            start=match.start(),
        )
    for param in parameter_names:
        if param == self_param:
            continue
        for tag in (f"</{param}>", f"<{param}>"):
            index = value.find(tag)
            if index != -1:
                return _Residue(
                    description=f"an inline '{param}' tag",
                    conclusive=True,
                    absorbed=param,
                    start=index,
                )
    if value.rstrip().endswith(_ABSORBED_ARRAY_TAIL):
        return _Residue(
            description="the tail of an unterminated JSON list",
            conclusive=False,
            absorbed=None,
            start=len(value),
        )
    return None


def _tail_is_pure_call_syntax(tail: str) -> bool:
    """True when the tail is leftover call syntax AND carries a serialized value.

    Absorption appends a serialized argument and stops, so what follows the residue is
    a tag, then a JSON value, then nothing. Two things must both hold, and the second
    is not redundant:

    1. Nothing but markup, quoted strings and JSON punctuation survives to
       end-of-string. Prose that merely QUOTES markup keeps talking afterwards and
       fails here.
    2. A serialized value is actually present. Stripping ``<project_id>`` from
       "Usage: giljo close <project_id>" leaves an empty string, which satisfies (1)
       vacuously — so condition (1) ALONE refused ordinary prose containing an
       angle-bracket placeholder. There are 117 distinct parameter names across the
       tool surface, including 'name', 'title', 'status' and 'description', so that
       was not a corner case but "a developer wrote a placeholder in a sentence".

    Checking only that something survives the tag strip is not enough either: a
    trailing "<name>," leaves a lone comma, which JSON punctuation then removes. The
    test is therefore for a VALUE, which a placeholder never carries.

    A value is NOT always bracketed. A scalar-valued parameter is absorbed as a bare
    token ('<parameter name="phase">3'), and 15 string->scalar adjacencies exist on the
    live surface. The scalar allowance is gated on the serializer's own
    ``<parameter name="...">`` markup, which narrows it but does NOT make it exact:

        Confirmed the residue shape: <parameter name="requires_action">true
        Status update: worker mid-task.<parameter name="requires_action">true

    have BYTE-IDENTICAL tails. No tail-based gate can separate them, because the
    distinguishing information is not in the tail. Legitimate prose CAN contain this
    markup — ``post_to_thread.content``, ``spawn_job.mission`` and
    ``write_memory_entry.summary`` all quote it — so the gate is a cost reduction, not a
    proof. Ungated, a bare digit would additionally refuse "…<project_id> 2026".

    The residual is therefore real and accepted: text ending mid-air on raw markup with
    no terminal punctuation is refused (a trailing period, backtick or quote makes it
    pass). That is tolerable only because refusal is RECOVERABLE and silent persistence
    is not — the message names the parameter and states nothing was written, so the
    caller rewords and proceeds.
    """
    without_tags = _MARKUP_TAG.sub(" ", tail)
    scalars_are_credible = _PARAMETER_NAME_TAG.search(tail) is not None
    if not (_VALUE_TOKEN if scalars_are_credible else _VALUE_OPENER).search(without_tags):
        return False
    stripped = _QUOTED_STRING.sub(" ", without_tags)
    if scalars_are_credible:
        stripped = _JSON_SCALAR.sub(" ", stripped)
    return _JSON_PUNCTUATION.sub("", stripped) == ""


def _absorbed_required_message(
    tool_name: str, param: str, value: str, residue: _Residue, missing: Sequence[str]
) -> str:
    """TSK-9309's rejection: a required argument is absent because a neighbour ate it."""
    missing_list = ", ".join(repr(field) for field in missing)
    # Confident wording only where the evidence is conclusive; otherwise the
    # message states a possibility, so the caller is not sent to fix the wrong
    # thing on a hunch.
    claim = (
        f"{missing_list} was absorbed into '{param}' by the caller's tool-call serialization "
        f"and never arrived as a separate argument"
        if residue.conclusive
        else (
            f"{missing_list} MAY have been absorbed into '{param}' by the caller's tool-call "
            f"serialization rather than genuinely omitted -- that tail is suggestive, not proof, "
            f"so check whether '{param}' ends with content that belongs to {missing_list}"
        )
    )
    return (
        f"Tool '{tool_name}' arrived without required argument(s) {missing_list}, but its "
        f"'{param}' argument is {len(value)} characters long and ends with {residue.description}. "
        f"{claim} -- the field itself is not wrong, and no "
        f"server-side payload limit was reached (every field was within its documented cap). "
        f"Re-send the call with a SHORTER '{param}' so the next argument boundary is not "
        f"swallowed, keeping {missing_list} as its own argument. Nothing was written."
    )


def _absorbed_optional_message(tool_name: str, param: str, value: str, residue: _Residue) -> str:
    """BE-9348's rejection: nothing REQUIRED is missing, so this call would otherwise
    have succeeded and written the caller's raw markup into the permanent record."""
    absorbed = f"'{residue.absorbed}'" if residue.absorbed else "a later optional argument"
    return (
        f"Tool '{tool_name}' arrived with every required argument present, but its '{param}' "
        f"argument is {len(value)} characters long and contains {residue.description}, after which "
        f"nothing but tool-call syntax follows. {absorbed} was absorbed into '{param}' by the "
        f"caller's tool-call serialization and never arrived as its own argument -- so this call "
        f"would have been ACCEPTED, {absorbed} silently dropped, and the raw markup stored verbatim "
        f"in the permanent record. No server-side payload limit was reached (every field was within "
        f"its documented cap). Re-send the call with a SHORTER '{param}' so the next argument "
        f"boundary is not swallowed, keeping {absorbed} as its own argument. Nothing was written."
    )


def describe_absorbed_argument(
    *,
    tool_name: str,
    arguments: Mapping[str, Any],
    required: Sequence[str],
    parameter_names: Sequence[str],
) -> str | None:
    """Return an agent-actionable rejection naming the real cause, or ``None``.

    ``None`` means "no absorption evidence" — the caller simply omitted the field,
    and the ordinary validation error is the honest answer. Returning a message
    here would repeat the original defect in the opposite direction: naming a
    cause that is not the real one.

    BE-9348: the scan is no longer gated on a required argument already being absent.
    When absorption swallows an OPTIONAL argument, every required one is still present,
    validation passes, and the residue is PERSISTED — the same defect with no error at
    all, which is strictly worse. That path is the only one here that can turn a
    currently-succeeding call into a rejection, so it is held to two extra conditions:
    the evidence must be conclusive (never the weak JSON-list tail), and the tail after
    the residue must be pure call syntax.
    """
    missing = [field for field in required if field not in arguments]
    for param in parameter_names:
        value = arguments.get(param)
        if not isinstance(value, str):
            continue
        residue = _absorption_residue(value, parameter_names, self_param=param)
        if residue is None:
            continue
        if missing:
            return _absorbed_required_message(tool_name, param, value, residue, missing)
        if not residue.conclusive:
            continue
        # The residue must name an argument THIS tool actually has. When it does not
        # (e.g. '<parameter name="phase">' on write_project_closeout), `absorbed` is
        # already None and the rejection would claim "a later optional argument was
        # absorbed" -- false, because the tool has no such argument to lose. On a change
        # whose whole risk axis is false positives, refusing to guess is free.
        if residue.absorbed is None:
            continue
        if not _tail_is_pure_call_syntax(value[residue.start :]):
            continue
        return _absorbed_optional_message(tool_name, param, value, residue)
    return None


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
    """
    session_data = getattr(session_row, "session_data", None)
    if not isinstance(session_data, dict):
        return
    resolved = session_data.get("resolved_preset")
    if isinstance(resolved, str) and resolved:
        scope.setdefault("state", {})["resolved_preset"] = resolved
