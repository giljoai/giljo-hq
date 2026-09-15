# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import json
from typing import Any
from urllib.parse import parse_qs

from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from api.endpoints.mcp_tools import TOOL_PROFILES, logger
from api.endpoints.oauth import MCP_SPEC_VERSIONS_SUPPORTED
from giljo_mcp.http.url_resolver import get_canonical_mcp_resource_uri_from_scope


_SUBSCRIPTION_REQUIRED_CODE = -32001


def _subscription_required_response(message: str, request_id=None) -> JSONResponse:
    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": _SUBSCRIPTION_REQUIRED_CODE, "message": message},
        },
        status_code=403,
    )


def _build_www_authenticate_header(scope: Scope) -> str:
    canonical = get_canonical_mcp_resource_uri_from_scope(scope)
    base, _, _ = canonical.rpartition("/mcp")
    metadata_url = f"{base}/.well-known/oauth-protected-resource"
    return f'Bearer realm="MCP", resource_metadata="{metadata_url}"'


def _unauthenticated_response(scope: Scope, error: str, status_code: int = 401) -> JSONResponse:
    return JSONResponse(
        {"error": error},
        status_code=status_code,
        headers={"WWW-Authenticate": _build_www_authenticate_header(scope)},
    )




_SUPPORTED_VERSIONS: frozenset[str] = frozenset(MCP_SPEC_VERSIONS_SUPPORTED)
_DEFAULT_SPEC_VERSION = "2025-03-26"
_INITIALIZE_METHOD = "initialize"

_DISCOVER_METHOD = "server/discover"
_CLIENT_ANNOUNCING_METHODS = frozenset({_INITIALIZE_METHOD, _DISCOVER_METHOD})

_CLIENT_INFO_META_KEY = "io.modelcontextprotocol/clientInfo"


def announces_client(method: str | None) -> bool:
    return method in _CLIENT_ANNOUNCING_METHODS


async def _read_full_body(receive: Receive, *, max_bytes: int | None = None) -> bytes:
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
    sent = {"done": False}

    async def _receive() -> dict:
        if not sent["done"]:
            sent["done"] = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await original_receive()

    return _receive


_MAX_MCP_BODY_BYTES = 5 * 1024 * 1024


class _BodyTooLargeError(Exception):
    pass


async def _send_raw_status(send: Send, *, status: int, headers: list[tuple[bytes, bytes]] | None = None) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": headers or [],
        }
    )
    await send({"type": "http.response.body", "body": b""})


async def _send_method_not_allowed(send: Send) -> None:
    await _send_raw_status(
        send,
        status=405,
        headers=[(b"allow", b"POST, DELETE")],
    )


def _peek_jsonrpc_method(body: bytes) -> str | None:
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
    if isinstance(client_info, dict):
        return client_info
    meta = params.get("_meta")
    if isinstance(meta, dict):
        from_meta = meta.get(_CLIENT_INFO_META_KEY)
        if isinstance(from_meta, dict):
            return from_meta
    return None


def _peek_jsonrpc_protocol_version(body: bytes) -> str | None:
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
    return JSONResponse(
        {
            "error": "Unsupported MCP-Protocol-Version",
            "requested": version,
            "supported": list(MCP_SPEC_VERSIONS_SUPPORTED),
        },
        status_code=400,
    )


def _not_found_response(detail: str) -> JSONResponse:
    return JSONResponse({"error": detail}, status_code=404)


def _validate_protocol_version(request: StarletteRequest, method: str | None) -> JSONResponse | None:
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

    async def _send(message: dict) -> None:
        if message["type"] == "http.response.start":
            headers = list(message.get("headers", []))
            headers.append((b"mcp-session-id", session_id.encode("ascii")))
            message = {**message, "headers": headers}
        await send(message)

    return _send


_DECLARED_PROFILE_CLIENT_INFO_KEY = "giljo_tool_profile"


def _stamp_declared_profile(scope: Scope, session_row: Any) -> None:
    session_data = getattr(session_row, "session_data", None)
    if not isinstance(session_data, dict):
        return
    client_info = session_data.get("client_info")
    if not isinstance(client_info, dict):
        return
    declared = client_info.get(_DECLARED_PROFILE_CLIENT_INFO_KEY)
    if isinstance(declared, str) and declared in TOOL_PROFILES:
        scope.setdefault("state", {})["tool_profile"] = declared


_URL_PROFILE_QUERY_PARAM = "profile"


def _stamp_url_profile(scope: Scope) -> None:
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
        return
    state = scope.setdefault("state", {})
    baseline = _profile_toolset_from_state(state)
    if baseline is not None and not candidate <= baseline:
        return
    state["tool_profile"] = requested


def _stamp_resolved_harness(scope: Scope, session_row: Any) -> None:
    from giljo_mcp.platform_registry import GENERIC_HARNESS

    session_data = getattr(session_row, "session_data", None)
    if not isinstance(session_data, dict):
        return
    resolved = session_data.get("resolved_harness")
    if isinstance(resolved, str) and resolved and resolved != GENERIC_HARNESS:
        scope.setdefault("state", {})["resolved_harness"] = resolved


def _stamp_resolved_preset(scope: Scope, session_row: Any) -> None:
    session_data = getattr(session_row, "session_data", None)
    if not isinstance(session_data, dict):
        return
    resolved = session_data.get("resolved_preset")
    if isinstance(resolved, str) and resolved:
        scope.setdefault("state", {})["resolved_preset"] = resolved
