# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""FE-9500: the Connect surface must report WHICH tool connected, not "any credential".

THE DEFECT: connecting any single tool marked EVERY card on Tools -> Connect
green, including tools not installed on that machine at all. Removing a tool did
not turn it red.

Two independent causes, both pinned here:

1. The BACKEND emitted ``tool_name="mcp_connected"`` -- a hardcoded placeholder --
   even though ``harness_resolver.harness_from_client_info`` already existed and the
   ``initialize`` clientInfo was in scope at the emit site. The identity was
   available and discarded.

2. ``credential-status`` answered one WORKSPACE-wide question ("does this tenant
   hold a live API key or OAuth grant?") and the frontend painted that single
   boolean onto every tool card.

The fix keeps the workspace flags (they are correct for what they are) and adds
``connected_harnesses``, derived on the fly from EXISTING ``mcp_sessions`` rows --
the same no-new-table idiom FE-9274 established.

HONEST LIMIT, pinned below so nobody "fixes" it later: Claude Desktop and claude.ai
web send byte-identical initialize payloads, so they are one harness and cannot
be separated.
"""

from __future__ import annotations

import pathlib
import re

from giljo_mcp.harness_resolver import harness_from_client_info


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
MIDDLEWARE = REPO_ROOT / "api" / "endpoints" / "mcp_auth_middleware.py"
SETUP_TOOLS_JS = REPO_ROOT / "frontend" / "src" / "config" / "setupTools.js"
HARNESS_RESOLVER = REPO_ROOT / "src" / "giljo_mcp" / "harness_resolver.py"


class TestEventNamesTheHarness:
    """Cause 1: the announcement must carry the resolved harness, not a placeholder."""

    def test_placeholder_tool_name_is_gone(self) -> None:
        src = MIDDLEWARE.read_text(encoding="utf-8")
        # Target the EMIT, not any mention: the comment above the fix names the old
        # placeholder on purpose, and a substring check would ban explaining the bug.
        assert 'tool_name="mcp_connected"' not in src, (
            "mcp_auth_middleware still emits the hardcoded 'mcp_connected' placeholder. "
            "The resolved harness is available at that line via harness_from_client_info; "
            "emitting a placeholder is what made every tool card light up."
        )
        assert "tool_name=harness" in src, "the emit must pass the RESOLVED harness"

    def test_emit_site_resolves_the_harness_from_client_info(self) -> None:
        src = MIDDLEWARE.read_text(encoding="utf-8")
        assert "harness_from_client_info" in src
        # client_info must actually be threaded to the announcer, not just imported.
        assert "_announce_client_connected(tenant_key, user_id, client_info)" in src, (
            "client_info is not passed to _announce_client_connected -- the resolver "
            "would receive nothing and every connect would report 'generic'."
        )

    def test_resolver_maps_the_real_client_names(self) -> None:
        assert harness_from_client_info("opencode") == "opencode"
        assert harness_from_client_info("claude-code") == "claude-code"
        assert harness_from_client_info("antigravity-client") == "antigravity"

    def test_unidentified_client_degrades_to_generic_not_to_a_guess(self) -> None:
        # A real connect that self-identifies with nothing must report 'generic'
        # rather than being attributed to whichever tool the user is looking at.
        assert harness_from_client_info(None) == "generic"
        assert harness_from_client_info("") == "generic"
        assert harness_from_client_info("some-client-we-have-never-seen") == "generic"


class TestCredentialStatusCarriesPerToolTruth:
    """Cause 2: the response must distinguish workspace credential from per-tool connect."""

    def test_schema_exposes_connected_harnesses(self) -> None:
        from giljo_mcp.schemas.responses.auth import CredentialStatusResult

        fields = CredentialStatusResult.model_fields
        assert "connected_harnesses" in fields, (
            "credential-status has no per-tool field, so the frontend can only fall back "
            "to the workspace-wide flags -- the exact defect."
        )
        # The workspace flags must SURVIVE: they are correct for what they describe.
        for flag in ("has_valid_api_key", "has_valid_oauth", "has_expired_oauth"):
            assert flag in fields

    def test_connected_harnesses_defaults_to_empty_not_none(self) -> None:
        from giljo_mcp.schemas.responses.auth import CredentialStatusResult

        result = CredentialStatusResult(has_valid_api_key=True, has_valid_oauth=False, has_expired_oauth=False)
        # A tenant holding a credential but with no completed handshake must report
        # NO connected tools -- credential existence is not a connection.
        assert result.connected_harnesses == {}

    def test_repository_derives_from_sessions_without_a_new_table(self) -> None:
        import inspect

        from giljo_mcp.repositories.auth_repository import AuthRepository

        src = inspect.getsource(AuthRepository.connected_harnesses)
        assert "MCPSession" in src, "per-tool truth must come from the existing session rows"
        assert "tenant_key" in src, "the query must be tenant-scoped (ADR-009)"


class TestFrontendBackendSeam:
    """The two sides use DIFFERENT vocabularies. A silent mismatch = a dead card.

    Backend tokens: claude-code / codex / gemini / antigravity / opencode / generic.
    Frontend ids:   claude_code / codex_cli / gemini_cli / antigravity_cli / opencode / generic.

    Nothing at runtime would fail loudly if these drifted -- a real connect would just
    never light its card, which is indistinguishable from "the tool did not connect".
    So the map is pinned from BOTH directions here.
    """

    def _js_map(self) -> dict[str, str]:
        js = SETUP_TOOLS_JS.read_text(encoding="utf-8")
        block = re.search(r"HARNESS_TO_TOOL_ID\s*=\s*\{(.*?)\}", js, re.S)
        assert block, "HARNESS_TO_TOOL_ID not found in setupTools.js"
        pairs = re.findall(r"'?([a-zA-Z][\w.-]*)'?\s*:\s*'([\w-]+)'", block.group(1))
        return dict(pairs)

    def _backend_tokens(self) -> set[str]:
        src = HARNESS_RESOLVER.read_text(encoding="utf-8")
        return set(re.findall(r'^HARNESS_[A-Z_]+ = "([\w-]+)"', src, re.M))

    def test_every_backend_harness_token_has_a_frontend_tool_id(self) -> None:
        missing = sorted(self._backend_tokens() - set(self._js_map()))
        assert not missing, (
            f"backend can emit harness token(s) {missing} that setupTools.js cannot map. "
            "A user connecting that tool would see NOTHING light up."
        )

    def test_generic_is_mapped_deliberately(self) -> None:
        # 'generic' is a REAL connect (client identified itself with nothing), not an
        # error case -- it must have a home rather than being silently dropped.
        assert self._js_map().get("generic") == "generic"

    def test_every_mapped_tool_id_actually_exists_in_the_picker(self) -> None:
        js = SETUP_TOOLS_JS.read_text(encoding="utf-8")
        known = set(re.findall(r"\{ id: '([\w]+)'", js))
        bogus = sorted(set(self._js_map().values()) - known)
        assert not bogus, f"HARNESS_TO_TOOL_ID points at tool id(s) {bogus} that SETUP_TOOLS lacks"

    def test_claude_desktop_and_web_share_one_harness_by_design(self) -> None:
        # Pinned so a future change does not try to split them: production measurement
        # showed byte-identical initialize payloads. If this ever becomes possible the
        # resolver's docstring is the place to revisit, deliberately.
        assert harness_from_client_info("Anthropic/ClaudeAI") == harness_from_client_info("Anthropic/ClaudeAI", "1.0")
