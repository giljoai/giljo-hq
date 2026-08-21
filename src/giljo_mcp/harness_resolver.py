# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Runtime harness identity resolver (BE-9035b) — pure detection from clientInfo.

The HARNESS is *which CLI / agent app* drives an MCP session (claude-code / codex /
gemini / antigravity / opencode / ...), resolved at runtime from the ``initialize``
handshake's clientInfo and NEVER declared by the user. This module is the PURE,
leaf-level detection layer (token vocabulary + the seed table + the resolver
functions); the two-axis registry, the HARNESSES knowledge table, and the
``effective_harness`` precedence helper live in :mod:`giljo_mcp.platform_registry`,
which imports and re-exports these names. Split out of platform_registry (BE-9035c)
purely for the 800-line file-size guardrail; it stays a clean seam (detection vs the
static registry) with no dependency back on platform_registry.

SECURITY FRAMING (load-bearing): detection drives per-harness RENDERING only —
spawn syntax, wake / reactivation prose, launch commands, autonomy flags. It is
NEVER an authentication or authorization signal; auth stays tenant/scope-based. A
wrong or absent detection degrades ergonomics only, and the declared CLI hint can
correct it. clientInfo is client-supplied and trivially spoofable, so it must never
gate access.

WHAT DETECTION RESCUES: it upgrades harnesses that send a RICH clientInfo —
claude-code (``name=="claude-code"``), codex (``name=="codex-mcp-client"``),
opencode (``name=="opencode"``), gemini (``name=="gemini-cli-mcp-client"``), and
antigravity (``name=="antigravity-client"``), the identifiers confirmed by
harvest/verification. gemini and antigravity were seeded in TSK-9088 from a live
capture sweep (Gemini CLI, and the Antigravity desktop app / CLI which share the one
``antigravity-client`` string). Empty/unrecognized clientInfo resolves to ``generic``
BY DESIGN; the universal generic subagent prose (BE-9035c) carries it.
The seed table is SELF-IMPROVING: an unrecognized non-empty name is logged (raw
name+version) at INFO so the table grows from observed traffic, never guessed
literals. Conservative always: ambiguous -> generic.

KNOWN-GENERIC ROWS: a handful of observed names are hosted chat/connector surfaces
or connection-test probes, NOT terminal CLIs — they map to ``generic`` EXPLICITLY so
the self-improve INFO log stays quiet for known-benign, high-frequency traffic. See
``_KNOWN_GENERIC_CLIENT_NAMES``.

Edition Scope: Both.
"""

from __future__ import annotations

import logging


logger = logging.getLogger(__name__)


# Harness token vocabulary. The 4 CLI tokens equal their HARNESSES ``tool_type`` (so a
# declared-mode hint maps to a harness with no translation); ``GENERIC_HARNESS`` is the
# fail-safe floor. Defined here (the leaf) so both the registry table and the resolver
# reference one source.
HARNESS_CLAUDE_CODE = "claude-code"
HARNESS_CODEX = "codex"
HARNESS_GEMINI = "gemini"
HARNESS_ANTIGRAVITY = "antigravity"
HARNESS_OPENCODE = "opencode"
GENERIC_HARNESS = "generic"


# clientInfo.name (EXACT, case-sensitive) -> harness token. SEEDED from the BE-9035
# harvest: ``claude-code`` (rich identifier captured in prod), ``codex-mcp-client``
# (local Codex CLI + desktop app — auth-method-independent), and ``opencode`` (name+
# version, from the CE test-install chain trial). TSK-9088 added ``gemini-cli-mcp-client``
# (Gemini CLI) and ``antigravity-client`` (Antigravity desktop app AND CLI — one shared
# string) from a live capture sweep on the SaaS test stack. Matching is EXACT (never
# substring/prefix): a lookalike name (``"claude-code-proxy"``, ``"claudecode"``,
# ``"gemini-cli"``) MUST resolve to generic.
_HARNESS_BY_CLIENT_NAME: dict[str, str] = {
    "claude-code": HARNESS_CLAUDE_CODE,
    "codex-mcp-client": HARNESS_CODEX,
    "opencode": HARNESS_OPENCODE,
    "gemini-cli-mcp-client": HARNESS_GEMINI,
    "antigravity-client": HARNESS_ANTIGRAVITY,
}


# clientInfo.name (EXACT) values observed in live traffic that are hosted chat /
# connector surfaces or connection-test probes — NOT terminal CLIs. They map to
# ``generic`` EXPLICITLY (case (a) fast-path) so the self-improve INFO log stays quiet
# for known-benign, high-frequency traffic. Captured 2026-07-07 (TSK-9088 sweep):
#   - Anthropic/ClaudeAI   : Claude Desktop AND claude.ai web (identical string).
#   - Anthropic/Toolbox    : Anthropic's connector-validation probe.
#   - openai-mcp           : chatgpt.com steady-state (OpenAI-hosted, no terminal).
#   - openai-mcp (ChatGPT) : chatgpt.com connector validation/tool-discovery.
#   - openai-mcp (Codex)   : Codex hosted-connector surface (≠ the native codex-mcp-client).
#   - opencode-check       : opencode's connection-test probe (≠ the real ``opencode``).
# The desktop_app-vs-chat distinction for these comes from the capability vector, NEVER
# from clientInfo — do not try to split them here.
_KNOWN_GENERIC_CLIENT_NAMES: frozenset[str] = frozenset(
    {
        "Anthropic/ClaudeAI",
        "Anthropic/Toolbox",
        "openai-mcp",
        "openai-mcp (ChatGPT)",
        "openai-mcp (Codex)",
        "opencode-check",
    }
)


# Harness PRESET tokens (INF-8003e). Repeated as literals rather than imported
# because this module is the LEAF -- platform_registry imports it, never the
# reverse. A drift guard (tests/unit/test_be9327_preset_targeting.py) asserts every
# value below is a member of ``platform_registry.VALID_PRESETS``, so the duplication
# cannot rot into a token that resolves to no preset row.
_PRESET_WEB_SANDBOX = "web_sandbox"
_PRESET_CHAT = "chat"


# clientInfo.name (EXACT) -> harness PRESET token, for hosted surfaces whose name is
# UNAMBIGUOUS about the environment behind it (BE-9327). This is the producer of the
# ``capabilities["preset"]`` key ``select_effective_preset`` consumes; before it
# existed nothing wrote that key, so the preset axis was reachable only by an explicit
# declaration and a hosted chat client was handed filesystem install instructions for
# directories it cannot write to.
#
# WHY ONLY THE openai-mcp FAMILY (the BE-9327 targeting decision):
#   - ``openai-mcp`` / ``openai-mcp (ChatGPT)`` are chatgpt.com surfaces: no
#     filesystem workspace at all -> ``chat``.
#   - ``openai-mcp (Codex)`` is the HOSTED Codex connector (NOT the native
#     ``codex-mcp-client`` CLI): a web coding agent with an isolated PR workspace and
#     no OS terminals -> ``web_sandbox``, matching the PLATFORM_PRESETS row comment.
#   - ``Anthropic/ClaudeAI`` is DELIBERATELY ABSENT. Claude Desktop and claude.ai web
#     send the byte-identical string, and their environments differ in exactly the way
#     this map decides: Desktop has a real home directory (``shared_working_tree``) and
#     MUST keep its working file install; claude.ai web has none. Mapping the shared
#     name to a chat preset would regress Desktop; mapping it to desktop_app would gain
#     claude.ai nothing. It stays on the declared-only path until a signal that
#     actually separates the two exists (the capability vector carries no ``roots``
#     probe today). Those users still receive their agent identity through
#     ``get_job_mission`` and templates through ``get_context``, so nothing is lost.
#   - ``Anthropic/Toolbox`` and ``opencode-check`` are connection-test probes, not user
#     sessions -- nothing to target.
#
# Detection remains a RENDERING hint and never a gate (see the module docstring): a
# miss here costs the caller the declared-harness path, never access.
_PRESET_BY_CLIENT_NAME: dict[str, str] = {
    "openai-mcp": _PRESET_CHAT,
    "openai-mcp (ChatGPT)": _PRESET_CHAT,
    "openai-mcp (Codex)": _PRESET_WEB_SANDBOX,
}


def preset_from_client_info(name: str | None, version: str | None = None) -> str | None:
    """Resolve the session harness PRESET token from the ``initialize`` clientInfo (BE-9327).

    Returns ``web_sandbox`` / ``chat`` for a hosted client whose name unambiguously
    identifies its environment, or ``None`` for everything else -- every terminal CLI,
    every unrecognized name, an absent name, and the ambiguous ``Anthropic/ClaudeAI``
    (see :data:`_PRESET_BY_CLIENT_NAME` for why). ``None`` means "no preset applies",
    which leaves :func:`~giljo_mcp.platform_registry.select_effective_preset` on the
    declared-only path -- byte-identical to the pre-BE-9327 behaviour.

    Exact, case-sensitive matching and conservative by construction, mirroring
    :func:`harness_from_client_info`: a lookalike name resolves to ``None`` rather than
    guessing an environment. ``version`` is accepted for signature symmetry with the
    harness resolver only; it does not affect resolution, and it cannot -- see
    :func:`harness_from_client_info` for why no version-based tie-break is available.
    """
    return _PRESET_BY_CLIENT_NAME.get((name or "").strip())


def harness_from_client_info(name: str | None, version: str | None = None) -> str:
    """Resolve the session harness token from the MCP ``initialize`` clientInfo (BE-9035b).

    THREE cases (per the BE-9035 harvest design):
      (a) a RECOGNIZED ``name`` -> its harness token via the seeded table;
      (b) an ABSENT / empty / whitespace-only name -> ``generic`` (a real connect
          that self-identifies with nothing -- the common case; no log);
      (c) an UNRECOGNIZED non-empty name -> ``generic`` AND an INFO log of the raw
          name+version, so the seed table self-improves from observed traffic
          instead of from guessed literals.

    Pure and conservative: exact (case-sensitive) name match; anything ambiguous
    degrades to ``generic``. Detection drives RENDERING only, never auth.
    ``version`` is accepted for the observation log; it does not affect resolution.

    NO CLAUDE-FAMILY TIE-BREAK IS POSSIBLE -- do not try to build one on ``version``.
    An earlier revision of this docstring offered that as future work. It cannot be
    done: measured against production on 2026-08-16, Claude Desktop and claude.ai web
    send BYTE-IDENTICAL ``initialize`` payloads -- same ``name`` (``Anthropic/ClaudeAI``,
    already noted at :data:`_KNOWN_GENERIC_CLIENT_NAMES`), same ``version`` (``1.0.0``),
    same declared capabilities. There is no field that separates them, so there is
    nothing for a tie-break to read. Anthropic's own connector documentation says the
    same thing prescriptively: do not gate behaviour on an exact ``name`` or ``version``
    (both vary across surfaces and releases), and ``clientInfo`` is unauthenticated, so
    it must never feed an authorization decision. If you need "is this the CLI?", read
    the OAuth ``client_id`` -- Claude Code registers its own -- and accept that no
    mechanism separates Desktop from web, because they are one OAuth client by design.
    """
    key = (name or "").strip()
    if not key:
        return GENERIC_HARNESS  # (b) absent / {} / whitespace-only
    harness = _HARNESS_BY_CLIENT_NAME.get(key)
    if harness is not None:
        return harness  # (a) recognized
    if key in _KNOWN_GENERIC_CLIENT_NAMES:
        return GENERIC_HARNESS  # (a) recognized-as-generic: hosted surface / probe, no log
    # (c) unrecognized non-empty name -- observe it so the seed table can grow.
    logger.info(
        "[harness-detect] unrecognized MCP clientInfo name=%r version=%r -> generic "
        "(add a table row if this is a real harness)",
        key,
        (version or "").strip() or None,
    )
    return GENERIC_HARNESS


def _detected_harness_from_session(session: object | None) -> str | None:
    """Read a stamped ``resolved_harness`` from a tolerant session shape (BE-9035b).

    Accepts an ``MCPSession``-like row (reads ``.session_data``), a raw session_data
    dict (``resolved_harness`` key), or a capability vector carrying ``"harness"``
    (the shape :func:`get_session_capabilities` returns). Returns the harness token,
    or ``None`` when nothing is stamped. Never raises -- a bookkeeping read, not a gate.
    """
    if session is None:
        return None
    data = getattr(session, "session_data", None)
    if isinstance(data, dict):
        stamped = data.get("resolved_harness")
        if isinstance(stamped, str) and stamped:
            return stamped
    if isinstance(session, dict):
        for candidate_key in ("resolved_harness", "harness"):
            value = session.get(candidate_key)
            if isinstance(value, str) and value:
                return value
    return None
