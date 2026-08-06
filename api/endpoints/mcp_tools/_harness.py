# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Harness + session-capability detection for the MCP render path.

Extracted from ``_base.py`` (BE-9035d) so the shared wrapper base stays under the
800-line guardrail: this is a cohesive unit — resolve WHICH harness / capabilities
drive per-session RENDERING (spawn syntax, preset). Detection is a RENDERING hint,
never an auth/authz signal; a wrong or absent detection degrades ergonomics only.

``_base`` re-exports these names, so callers keep importing them from ``_base``.
Edition Scope: Both.
"""

from mcp.server.fastmcp import Context
from starlette.requests import Request as StarletteRequest

from giljo_mcp.harness_resolver import preset_from_client_info
from giljo_mcp.platform_registry import GENERIC_HARNESS, harness_from_client_info, select_effective_preset


def _persisted_harness(ctx: Context) -> str | None:
    """Read the DETECTED harness the middleware stamped onto scope state (BE-9035d).

    ``_stamp_resolved_harness`` (transport) surfaces ``session_data['resolved_harness']``
    onto ``scope['state']`` so the render can recover it after ``stateless_http`` drops
    the live clientInfo. ``None`` when there is no HTTP request (in-memory transport) or
    nothing stamped. Never raises — a render hint, not a gate.
    """
    try:
        request: StarletteRequest = ctx.request_context.request
        value = request.scope.get("state", {}).get("resolved_harness")
        return value if isinstance(value, str) and value else None
    except Exception:  # noqa: BLE001 - detection is a render hint, never raise into the tool
        return None


def _detected_harness(ctx: Context) -> str:
    """Resolve the DETECTED harness token, live clientInfo first with a persisted fallback.

    The live ``ctx.session.client_params.clientInfo`` (BE-9035b) wins when it yields a
    CONCRETE harness. But ``FastMCP(stateless_http=True)`` drops ``client_params`` on
    every non-``initialize`` tools/call — the exact render path — so on a generic/absent
    live read fall back to the harness persisted at initialize and stamped onto scope
    state (:func:`_persisted_harness`, BE-9035d). Degrades to ``generic``; never raises.
    """
    try:
        client_info = ctx.session.client_params.clientInfo
        live = harness_from_client_info(getattr(client_info, "name", None), getattr(client_info, "version", None))
    except Exception:  # noqa: BLE001 - detection is a render hint, never raise into the tool
        live = GENERIC_HARNESS
    if live != GENERIC_HARNESS:
        return live
    return _persisted_harness(ctx) or GENERIC_HARNESS


def _persisted_preset(ctx: Context) -> str | None:
    """Read the DETECTED harness preset the middleware stamped onto scope state (BE-9327).

    The preset-axis twin of :func:`_persisted_harness`; see
    ``_stamp_resolved_preset`` (transport) for why the persisted copy is the only one
    a tools/call can see. ``None`` when there is no HTTP request (in-memory transport)
    or nothing stamped. Never raises — a render hint, not a gate.
    """
    try:
        request: StarletteRequest = ctx.request_context.request
        value = request.scope.get("state", {}).get("resolved_preset")
        return value if isinstance(value, str) and value else None
    except Exception:  # noqa: BLE001 - detection is a render hint, never raise into the tool
        return None


def _detected_preset(ctx: Context) -> str | None:
    """Resolve the DETECTED harness PRESET, live clientInfo first with a persisted fallback.

    Mirrors :func:`_detected_harness` exactly, and for the same reason: the live
    ``ctx.session.client_params.clientInfo`` is authoritative when present (the
    ``initialize`` request and the in-memory transport), but ``stateless_http`` drops
    it on every tools/call — the render path — so fall back to the preset persisted at
    initialize. Degrades to ``None`` (no preset applies); never raises.
    """
    try:
        client_info = ctx.session.client_params.clientInfo
        live = preset_from_client_info(getattr(client_info, "name", None), getattr(client_info, "version", None))
    except Exception:  # noqa: BLE001 - detection is a render hint, never raise into the tool
        live = None
    return live or _persisted_preset(ctx)


def get_session_capabilities(ctx: Context) -> dict[str, bool | str | None]:
    """Generalized per-session capability read (INF-8003d; BE-9035b harness axis).

    Wraps the ``ClientCapabilities`` probes already used ad hoc by the two
    dormant NO-SHIP-UNTIL-GA prototypes (``_tasks_prototype._client_supports_tasks``,
    ``_inline_approval._client_supports_elicitation``) into one reusable map, so
    future callers (the (e)/(f) chain steps) have a single capability read
    instead of re-deriving the probe. Each boolean entry defaults to ``False`` on any
    probe failure (no session, older SDK, malformed capabilities) -- this must
    never raise into a tool caller.

    BE-9035b adds the ``"harness"`` key: the DETECTED harness token (claude-code /
    codex / ... / generic) resolved from the session clientInfo. It is the capability
    vector ``effective_harness`` consumes to apply the DETECTED-beats-declared render
    precedence. Absent/unknown clientInfo → ``"generic"`` (the fail-safe floor).

    BE-9327 adds the ``"preset"`` key: the DETECTED harness PRESET (web_sandbox / chat)
    for a hosted surface, else ``None``. ``select_effective_preset`` has always read
    this key, but nothing produced it, so the whole preset axis was reachable only by
    an explicit declaration — which no hosted client sends. The key is ALWAYS present
    (``None`` when no preset applies) so the vector stays one fixed shape rather than
    two its readers would have to tell apart.
    """
    from mcp.types import ClientCapabilities, ElicitationCapability

    def _probe(cap: ClientCapabilities) -> bool:
        try:
            return bool(ctx.session.check_client_capability(cap))
        except Exception:  # noqa: BLE001 - capability probe must never raise into the tool
            return False

    return {
        "elicitation": _probe(ClientCapabilities(elicitation=ElicitationCapability())),
        "tasks": _probe(ClientCapabilities(experimental={"io.modelcontextprotocol/tasks": {}})),
        "harness": _detected_harness(ctx),
        "preset": _detected_preset(ctx),
    }


# BE-8003f (D2 activation): one-sentence routing description for the harness param,
# shared by every @mcp.tool wrapper that accepts it, so the advertised values can
# never drift between wrappers. BE-8003g: moved here from _job_tools.py once
# giljo_setup (_setup_tools.py) became a second wrapper module resolving it.
_HARNESS_PARAM_DESCRIPTION = (
    "Optional session harness preset: web_sandbox|desktop_app|chat (omit for a terminal-capable CLI)."
)


def _resolve_preset_name(harness: str, ctx: Context) -> str | None:
    """Resolve the effective harness preset name for an MCP-boundary call (BE-8003f D2).

    DECLARED harness beats DETECTED capability (``select_effective_preset``). A ctx-less
    call or an unknown/empty harness token degrades to ``None`` — the CLI path, which
    renders byte-identically to today (D1). Never raises into the tool caller.
    """
    capabilities = get_session_capabilities(ctx) if ctx is not None else None
    preset = select_effective_preset(harness, capabilities)
    return preset.execution_mode if preset is not None else None
