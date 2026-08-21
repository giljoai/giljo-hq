# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""MCP tool SCOPE registry + exposure PROFILES — the two authorization lenses.

Split out of ``_base.py`` verbatim (BE-9253) to keep that module under the
800-line guardrail, exactly as ``oauth_well_known.py`` was split out of
``oauth.py`` and ``mcp_transport.py`` out of ``mcp_sdk_server.py``. Nothing here
changed in the move; ``_base`` re-exports every name, so existing importers
(``from api.endpoints.mcp_tools._base import TOOL_SCOPES``) keep working.

The dependency runs one way — this module imports nothing from ``_base`` — so
there is no import cycle.

Edition Scope: Both.
"""

from __future__ import annotations

from starlette.requests import Request as StarletteRequest


# ---------------------------------------------------------------------------
# Tool scope registry (API-0021b): scope-aware MCP tool gating
#
# Single source of truth for both list_tools advertise filter and call_tool
# dispatch gate. Three scopes:
#   - mcp:read   : pure-read tools, no DB writes, no agent-state mutation
#   - mcp:write  : writes confined to user-owned product/project/task/memory
#   - mcp:agent  : orchestration primitives (spawn, complete_job, post_to_thread,
#                  status mutations, mission edits, …). Privilege surface.
#                  BE-6168: now grantable through OAuth /authorize (OAuth is the
#                  default auth → parity with an API key), guarded by the
#                  localhost-only redirect-URI allowlist + user consent, NOT by
#                  withholding the scope. Every state-mutating orchestration tool
#                  MUST map here — a mis-map to read/write degrades enforcement
#                  (an OAuth read-only token could then mutate). See the BE-6168 guard test.
#                  SEC-9126: a tool with NO entry at all now fails CLOSED (hidden
#                  from tools/list AND rejected at dispatch), and the startup
#                  assert _assert_tool_scope_completeness() (mcp_sdk_server) aborts
#                  boot on any unmapped/orphaned tool. The mis-map-to-wrong-scope
#                  caution above still stands — SEC-9126 gates registry MEMBERSHIP,
#                  it does not police scope VALUES.
#
# Defense-in-depth: the dispatch gate enforces server-side. Hiding from
# tools/list alone is insufficient — a JWT caller can still craft tools/call.
# ---------------------------------------------------------------------------

SCOPE_READ = "mcp:read"
SCOPE_WRITE = "mcp:write"
SCOPE_AGENT = "mcp:agent"

TOOL_SCOPES: dict[str, str] = {
    "create_project": SCOPE_WRITE,
    "list_projects": SCOPE_READ,
    "update_project": SCOPE_WRITE,
    "update_project_mission": SCOPE_AGENT,
    # BE-6111c: read-only orchestrator self-healing diagnostic.
    "diagnose_project_state": SCOPE_READ,
    # INF-6049b: project-lifecycle driving tools. mcp:agent because they drive
    # orchestration (stage_project creates the orchestrator job; implement_project
    # exposes the execution prompt gated on agent + launch state).
    "stage_project": SCOPE_AGENT,
    "implement_project": SCOPE_AGENT,
    # BE-6115a: CLI door of the two-door implement gate. mcp:agent (privilege
    # surface) — its dispatch-gate scope + its deliberate exclusion from the
    # orchestrator auto-tool bundle (_canonical_tool_list) mean a spawned agent
    # cannot self-unlock; the MCP permission prompt is the human authorization.
    "launch_implementation": SCOPE_AGENT,
    # BE-6221a: headless chain-start (the dashboard "Run Sequential" equivalent).
    # mcp:agent — it mints the project-less conductor + creates a sequence run
    # (an orchestration mutation), so a read/write-only token must not reach it.
    "start_chain_run": SCOPE_AGENT,
    "update_job_mission": SCOPE_AGENT,
    # BE-6167: was SCOPE_READ, but the BE-5122 CTX self-close path inside
    # get_staging_instructions writes project.status=COMPLETED (a terminal
    # orchestration mutation). A read-only token must NOT be able to complete a
    # project — reclassify to mcp:agent alongside stage/implement_project. It is
    # an orchestration-driving tool, not a pure read.
    "get_staging_instructions": SCOPE_AGENT,
    # BE-6054b: Agent Message Hub (BBS) thread tools. Writes drive the board
    # (agent callers) = mcp:agent; pure reads = mcp:read (mirrors send/get above).
    "create_thread": SCOPE_AGENT,
    "join_thread": SCOPE_AGENT,
    "post_to_thread": SCOPE_AGENT,
    "pass_baton": SCOPE_AGENT,
    "get_my_turn": SCOPE_READ,
    # BE-9296a: the blocking form of get_my_turn. Same scope for the same reason —
    # it reads the same baton state and stamps the same liveness column.
    "await_my_turn": SCOPE_READ,
    # BE-9296a: read-only view over the participant directory a conductor already
    # has REST access to; the derived band is computed, never stored.
    "get_participant_liveness": SCOPE_READ,
    "list_threads": SCOPE_READ,
    "get_thread_history": SCOPE_READ,
    "search_threads": SCOPE_READ,
    "create_task": SCOPE_WRITE,
    "update_task": SCOPE_WRITE,
    "list_tasks": SCOPE_READ,
    "update_roadmap_metadata": SCOPE_WRITE,
    "get_roadmap": SCOPE_READ,
    "request_approval": SCOPE_AGENT,
    "health_check": SCOPE_READ,
    "get_giljo_guide": SCOPE_READ,
    "giljo_setup": SCOPE_WRITE,
    "report_progress": SCOPE_AGENT,
    "complete_job": SCOPE_AGENT,
    "close_job": SCOPE_AGENT,
    # BE-9012b (BE-6225e): reactivate_job + dismiss_reactivation merged into the single
    # resolve_reactivation tool surface. The two names remain in TOOL_DISPATCH below as
    # internal dispatch targets (resolve_reactivation branches to them by action), but
    # they are no longer agent-facing tools — so they carry no TOOL_SCOPES entry.
    "resolve_reactivation": SCOPE_AGENT,
    "set_agent_status": SCOPE_AGENT,
    "get_job_mission": SCOPE_AGENT,
    "spawn_job": SCOPE_AGENT,
    "get_agent_result": SCOPE_AGENT,
    "get_workflow_status": SCOPE_AGENT,
    "get_context": SCOPE_READ,
    # BE-6225b: keyword search over 360 memory. Pure read (no writes, no agent-state
    # mutation) — same scope as get_context, the other 360-memory read.
    "search_memory": SCOPE_READ,
    "write_project_closeout": SCOPE_AGENT,
    "write_memory_entry": SCOPE_AGENT,
    # BE-6225c: renamed from propose_product_context_update (it APPLIES tuning
    # directly, no propose step). Scope unchanged (mcp:write).
    "apply_context_tuning": SCOPE_WRITE,
    "get_vision_doc": SCOPE_READ,
    "update_product_context": SCOPE_WRITE,
    # BE-9201: agent-side product bootstrap (establish the row + write the agent-
    # authored vision doc). Same scope as update_product_context — user-owned
    # product writes confined to the caller's tenant.
    "create_product": SCOPE_WRITE,
    "create_vision_document": SCOPE_WRITE,
}


def _scopes_from_request(request: StarletteRequest | None) -> set[str] | None:
    """Resolve the caller's effective scope set from the ASGI request state.

    Returns:
        - None if the caller authenticated via API key (full bypass). BE-6168:
          OAuth is no longer scope-limited away from mcp:agent — an OAuth token
          granted mcp:agent reaches the same surface; this bypass is just the
          API-key path that skips per-scope filtering entirely.
        - set[str] of scope tokens otherwise. Empty set means "no scopes
          granted" (advertise nothing, gate everything).
    """
    if request is None:
        # In-memory test transport has no HTTP request. Tests monkeypatch this
        # function directly when they want scope filtering exercised.
        return None
    state = request.scope.get("state", {}) if hasattr(request, "scope") else {}
    if state.get("auth_method") == "api_key":
        return None
    scopes = state.get("scopes")
    if not scopes:
        return set()
    return set(scopes)


# ---------------------------------------------------------------------------
# Tool exposure PROFILES (WO-8003k): a curated tool-name subset evaluated
# ALONGSIDE the 3 auth scopes above, never replacing them. A profile is the
# capability-tier lens (a small/literal model sees a tight, disambiguated
# surface; a full CLI sees everything); the scope filter is the auth boundary.
# The effective visible/dispatchable set is the INTERSECTION: scope-filter ∩
# profile. This is purely additive on the API-0021b plumbing — no new filtering
# architecture (see the reuse map in project BE-8003k).
#
#   core     — the "one tool per intent" guided loop (exact 14 tools, incl.
#              health_check). What a small/literal model needs to run the
#              project→task→closeout loop without tripping over the confusable
#              update_*/messaging/completion clusters the small-model ergonomics
#              audit flagged.
#   standard — core + the Hub/BBS suite, messaging, roadmap, product-context /
#              vision reads+tuning, and the read-only project diagnostic (~30).
#              The JWT default for a session WITHOUT mcp:agent: a capable session
#              that is not the operator's own full-privilege orchestrator.
#   orchestrator — (BE-9017) the FULL surface MINUS launch_implementation. The
#              default for a JWT/OAuth session carrying mcp:agent (Claude Desktop /
#              claude.ai connector / OAuth CLI). Includes get_staging_instructions /
#              spawn_job / update_project_mission / stage_project (the human-ferried
#              flow needs them) but NOT the launch gate.
#   full     — the entire registered surface (sentinel ``None`` == NO profile
#              restriction, so a full session is BYTE-IDENTICAL to pre-profile
#              behavior and a profile can NEVER block a scope-allowed tool for it).
#
# SECURITY (WO-8003k DoD #3): stage_project / implement_project /
# launch_implementation are absent from BOTH core and standard, turning today's
# prompt-side-only advisory implement-gate exclusion into a server-enforced one —
# a core/standard tools/call on them is rejected exactly like an out-of-scope call.
# BE-9017: the orchestrator profile excludes launch_implementation ONLY — the sole
# writer of the human gate flag — so an mcp:agent session cannot self-unlock
# implementation, while implement_project (read-only, already gate-gated) stays
# reachable for the post-gate connector flow.
# ---------------------------------------------------------------------------

PROFILE_CORE = "core"
PROFILE_STANDARD = "standard"
PROFILE_FULL = "full"

# The exact 14-tool guided loop (EM decision, BE-8003k project description; BE-9017
# added ``health_check``). This set is roster-locked by the regression test —
# changing it is a deliberate act.
#
# BE-9017: ``health_check`` belongs in EVERY profile — every rendered prompt's step 1
# calls it as the fresh-connect probe. It was previously in the scope registry only,
# so a core/standard session's tools/list filtered it out and the guided loop broke
# at step 1 (field-confirmed on a Desktop OAuth session). Adding it to core flows it
# up to standard (superset), orchestrator (all-minus-launch — health_check is
# registered, so already included), and full (no restriction).
_CORE_PROFILE_TOOLS: frozenset[str] = frozenset(
    {
        "health_check",
        "get_giljo_guide",
        "get_context",
        "list_projects",
        "create_project",
        "create_task",
        "update_task",
        "list_tasks",
        "search_memory",
        "get_job_mission",
        "report_progress",
        "complete_job",
        "write_project_closeout",
        "post_to_thread",
    }
)

# standard = core + the mid-tier surface. Additions grouped as the WO enumerates
# them: the Hub/BBS thread suite, direct messaging, roadmap, product-context /
# vision, and the read-only project-state diagnostic. Deliberately EXCLUDES the
# orchestration/lifecycle privilege tools (spawn/stage/implement/chains/
# reactivation/mission edits) — those are full-only.
#
# BE-9452 — READ THIS BEFORE REMOVING A NAME FROM ``_CORE_PROFILE_TOOLS``:
# ``standard`` is DERIVED from ``core``, so a core removal is ALSO a standard
# removal, and ``standard`` is the auth-derived default for a JWT/OAuth session
# without ``mcp:agent`` (see _profile_toolset_from_state) — a live client tier.
# A ``core <= standard`` subset assertion cannot see that: a smaller set is still
# a subset. If a name must leave ``core`` but stay in ``standard``, add it to the
# additions block below in the SAME change. The name-list lock in
# tests/integration/test_be9452_standard_profile_roster_lock.py is what makes
# forgetting that fail loudly instead of silently narrowing a shipped tier.
_STANDARD_PROFILE_TOOLS: frozenset[str] = _CORE_PROFILE_TOOLS | frozenset(
    {
        # Hub / BBS thread suite (post_to_thread is already in core)
        "create_thread",
        "join_thread",
        "pass_baton",
        "get_my_turn",
        "await_my_turn",
        "get_participant_liveness",
        "list_threads",
        "get_thread_history",
        "search_threads",
        # Roadmap
        "get_roadmap",
        "update_roadmap_metadata",
        # Product context / vision (BE-9201 added the two bootstrap writes: the
        # onboarding prompts run in the same non-agent-scope session tier that
        # already carries update_product_context)
        "get_vision_doc",
        "update_product_context",
        "apply_context_tuning",
        "create_product",
        "create_vision_document",
        # Read-only orchestrator self-healing diagnostic
        "diagnose_project_state",
    }
)

PROFILE_ORCHESTRATOR = "orchestrator"

# BE-9017: the orchestrator profile — the default for an OAuth/JWT session carrying
# the ``mcp:agent`` scope (Claude Desktop / claude.ai connector / OAuth CLI). It is
# the FULL surface MINUS the launch-gate tool(s), so a legitimate orchestrator sees
# everything it needs for the human-ferried flow — health_check, get_staging_
# instructions, spawn_job, update_project_mission, stage_project — but still cannot
# unilaterally LAUNCH implementation from the session.
#
# Excluded = ``launch_implementation`` ONLY: it is the SOLE MCP door that writes
# ``implementation_launched_at`` (the sacred human gate). ``implement_project`` is
# deliberately KEPT IN — it is read-only + already server-gated (returns
# gate_not_passed until the human presses Implement, never sets the flag, no bypass),
# so excluding it would add zero security while breaking the post-gate connector flow.
# ``stage_project`` is reversible prep and stays in (the generic_mcp orchestrator
# needs it). Computed from TOOL_SCOPES so new tools are auto-included (no roster to rot).
_LAUNCH_GATE_TOOLS: frozenset[str] = frozenset({"launch_implementation"})
_ORCHESTRATOR_PROFILE_TOOLS: frozenset[str] = frozenset(TOOL_SCOPES) - _LAUNCH_GATE_TOOLS

PROFILE_LISTING = "listing"

# BE-9253: the bespoke lens for the PUBLIC MARKETPLACE connector listing — the one
# coherent loop a lone reviewer completes end to end in a single session against a
# seeded demo tenant: connect → read the guide → read context → create/list/update
# a project → create/list/update a task → search memory → read the roadmap. Every
# member returns a real result with no agent fleet, no ``job_id``, and no gate
# rejection. Roster-locked by name in the regression test — changing it is a
# deliberate act.
#
# Why not ``core`` and not ``standard``: core carries four agent-job tools a
# reviewer cannot exercise without a spawned job (and write_project_closeout's
# deliberate CLOSEOUT_BLOCKED rejection reads as a failure under functional test);
# standard adds the whole Hub/thread suite, which shows nothing with a single
# participant. Both, critically, OMIT ``update_project`` — the first thing anyone
# tries after creating one — so neither can complete the project CRUD loop.
#
# Two properties the resolver relies on: the set uses only mcp:read + mcp:write
# (never the privileged mcp:agent), and it is a strict subset of
# ``orchestrator`` — the connector's auth-derived default — so selecting it can
# only ever NARROW a connector session, never widen one.
_LISTING_PROFILE_TOOLS: frozenset[str] = frozenset(
    {
        "health_check",
        "get_giljo_guide",
        "get_context",
        "list_projects",
        "create_project",
        "update_project",
        "list_tasks",
        "create_task",
        "update_task",
        "search_memory",
        "get_roadmap",
    }
)

# Profile name -> the allowed tool-name set, or ``None`` for "no restriction"
# (the full surface). ``None`` is the sentinel the filter/gate short-circuit on,
# guaranteeing byte-identity for a full session.
TOOL_PROFILES: dict[str, frozenset[str] | None] = {
    PROFILE_CORE: _CORE_PROFILE_TOOLS,
    PROFILE_STANDARD: _STANDARD_PROFILE_TOOLS,
    PROFILE_ORCHESTRATOR: _ORCHESTRATOR_PROFILE_TOOLS,
    PROFILE_LISTING: _LISTING_PROFILE_TOOLS,
    PROFILE_FULL: None,
}


def _normalize_scopes(scopes: object) -> set[str]:
    """Normalize a request's stamped scopes to a set of tokens.

    ``state['scopes']`` is stamped as a ``list[str]`` (mcp_sdk_server.py, from
    ``principal.scopes`` or a split raw-scope string), but tolerate a raw
    space-delimited string too so a future auth path can't silently break the
    membership check. Mirrors :func:`_scopes_from_request`'s handling.
    """
    if not scopes:
        return set()
    if isinstance(scopes, str):
        return {s for s in scopes.split() if s}
    return {str(s) for s in scopes}


def _profile_toolset_from_state(state: dict) -> frozenset[str] | None:
    """Resolve the effective tool-profile allow-set from a request's ASGI state.

    Returns the frozenset of tool names the profile permits, or ``None`` for the
    ``full`` profile (NO restriction). ``None`` is reachable ONLY for a declared
    ``full`` profile or an ``api_key`` caller; every other outcome is a bounded
    allow-set, so the profile axis can never *widen* an unrecognized caller to
    the full surface.

    Precedence (WO-8003k DoD #2 — declared always wins):
      1. explicit selected profile — ``state['tool_profile']``; honored only when
         it names a known profile. Two middleware stamps write that one slot: the
         session-DECLARED profile from the (d) client_info capture (WO-8003k —
         may widen, deliberately, and independently fenced by BE-9084), and the
         BE-9253 URL vehicle (``/mcp?profile=...``), which is structurally
         narrow-only and can never reach the ``full`` sentinel.
      2. auth-derived default (BE-9017 — keys on token SCOPE, not just method):
         * a JWT/OAuth session carrying ``mcp:agent`` ⇒ ``orchestrator`` (Claude
           Desktop / claude.ai connector / OAuth CLI — the human-ferried
           orchestrator surface, minus the launch gate);
         * a JWT/OAuth session WITHOUT ``mcp:agent`` ⇒ ``standard`` (unchanged);
         * an API key ⇒ ``full`` (today's behavior for every existing CLI user,
           unchanged — the only recognized signal that resolves to full).
      3. SEC-9126 fail-CLOSED floor: any unknown/absent ``auth_method`` ⇒ the
         empty allow-set (``frozenset()``) — advertise nothing, dispatch nothing.
         ``api_key`` and ``jwt`` are the only signals the middleware ever stamps,
         so this branch is a dead path on every live HTTP request today; it was
         formerly the fail-OPEN ``full`` default, and is converted here into an
         enforced invariant so a future auth path can never silently inherit the
         full surface.

    ADR-009: the default keys on the token's SCOPE (+ tenant_key elsewhere), never
    on per-user identity.
    """
    declared = state.get("tool_profile")
    if isinstance(declared, str) and declared in TOOL_PROFILES:
        return TOOL_PROFILES[declared]
    if state.get("auth_method") == "jwt":
        # BE-9017: an OAuth/JWT orchestrator token carries mcp:agent by default
        # (DEFAULT_OAUTH_SCOPE). Keying the default on the SCOPE — not the auth
        # method alone — is what stops the blanket jwt→standard downgrade from
        # tool-blocking every legitimate connector orchestrator session.
        if "mcp:agent" in _normalize_scopes(state.get("scopes")):
            return TOOL_PROFILES[PROFILE_ORCHESTRATOR]
        return TOOL_PROFILES[PROFILE_STANDARD]
    # SEC-9126: api_key is the ONLY recognized signal that resolves to full (no
    # restriction) — today's operator/CLI behavior, byte-identical.
    if state.get("auth_method") == "api_key":
        return TOOL_PROFILES[PROFILE_FULL]
    # SEC-9126: fail-closed floor for any unknown/absent auth signal.
    return frozenset()


def _profile_toolset_from_request(request: StarletteRequest | None) -> frozenset[str] | None:
    """Resolve the tool-profile allow-set for an MCP request (``None`` == full).

    Mirrors :func:`_scopes_from_request`: with no HTTP request (the in-memory test
    transport) there is no session/auth state, so ``None`` (full — no profile
    restriction) is returned and behavior is byte-identical to pre-profile. Tests
    that exercise a specific profile monkeypatch this function directly.
    """
    if request is None:
        return None
    state = request.scope.get("state", {}) if hasattr(request, "scope") else {}
    return _profile_toolset_from_state(state)
